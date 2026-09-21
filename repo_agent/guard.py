"""Path and scope guards: the single place that decides what the agent may touch.

All tool file access goes through :class:`Guard`; nothing else resolves paths.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


class GuardError(Exception):
    """Raised when a tool asks for something outside the agent's mandate."""


def normalize(rel: str) -> str:
    rel = rel.replace("\\", "/").strip()
    while rel.startswith("./"):
        rel = rel[2:]
    return rel.strip("/")


def matches(rel: str, patterns: Iterable[str]) -> bool:
    """Match a repo-relative POSIX path against a small, predictable glob dialect.

    - ``pkg/mod.py``  -> plain fnmatch on the full relative path
    - ``**/x.py``     -> also matches ``x.py`` at the repository root
    - ``**/tests/**`` -> also matches any path containing a ``tests`` directory
    """
    rel = normalize(rel)
    if not rel:
        return False
    segments = rel.split("/")
    for pattern in patterns:
        pat = normalize(pattern)
        if not pat:
            continue
        if fnmatch.fnmatch(rel, pat):
            return True
        if pat.startswith("**/") and fnmatch.fnmatch(rel, pat[3:]):
            return True
        if pat.endswith("/**"):
            core = pat[:-3]
            if core.startswith("**/"):
                core = core[3:]
            core = core.strip("/")
            if core and core in segments:
                return True
    return False


def has_prefix(rel: str, prefixes: Iterable[str]) -> bool:
    rel = normalize(rel)
    for prefix in prefixes:
        pat = normalize(prefix)
        if pat and (rel == pat or rel.startswith(pat + "/")):
            return True
    return False


@dataclass(slots=True)
class Guard:
    """Decides read/write permissions and resolves tool paths inside the workspace."""

    root: Path
    protected_globs: tuple[str, ...] = ()
    forbidden_prefixes: tuple[str, ...] = ()
    editable_globs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        self.root = Path(self.root).resolve()

    def rel(self, path: str) -> str:
        """Resolve a tool-supplied path to a repo-relative POSIX path."""
        raw = (path or "").strip().strip('"').strip("'")
        if not raw:
            raise GuardError("empty path")
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = candidate.resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise GuardError(f"path escapes the workspace: {path}")
        if resolved == self.root:
            return ""
        return resolved.relative_to(self.root).as_posix()

    def absolute(self, path: str) -> Path:
        rel = self.rel(path)
        return self.root / rel

    def is_protected(self, rel: str) -> bool:
        return matches(rel, self.protected_globs)

    def check_read(self, path: str) -> str:
        rel = self.rel(path)
        if not rel:
            raise GuardError("refusing to read the workspace root as a file")
        if has_prefix(rel, self.forbidden_prefixes):
            raise GuardError(f"'{rel}' is not readable by contract")
        return rel

    def check_write(self, path: str) -> str:
        rel = self.rel(path)
        if not rel:
            raise GuardError("refusing to write the workspace root")
        if has_prefix(rel, self.forbidden_prefixes):
            raise GuardError(
                f"'{rel}' is inside a write-forbidden area; version-control internals cannot be edited"
            )
        if self.is_protected(rel):
            raise GuardError(
                f"'{rel}' matches a protected pattern. Test files and test configuration are "
                "read-only by contract: fix the source, never the test."
            )
        if self.editable_globs and not matches(rel, self.editable_globs):
            raise GuardError(f"'{rel}' is outside the editable scope of this task")
        return rel


def protected_files_in(paths: Iterable[str], protected_globs: Iterable[str]) -> list[str]:
    """Used by the patch contract check: which touched files are off-limits."""
    return sorted({normalize(p) for p in paths if matches(p, protected_globs)})


#: pytest options that consume the next token. Without this list a `-k expr` value could be
#: read as a test target, and a target that happens to name a directory is exactly the thing
#: we are hunting for.
PYTEST_VALUE_OPTIONS = frozenset(
    {
        "-k", "-m", "-p", "-c", "-o", "-n", "-W",
        "--deselect", "--ignore", "--ignore-glob", "--rootdir", "--timeout", "--maxfail",
        "--junitxml", "--junit-prefix", "--log-file", "--log-level", "--tb", "--capture",
        "--durations", "--import-mode", "--basetemp", "--override-ini", "--dist", "--runtest",
    }
)

#: Options that make a whole-suite invocation cheap, so they are worth allowing.
PYTEST_CHEAP_FLAGS = frozenset({"--collect-only", "--co", "--version", "-h", "--help"})


def _split_segments(command: str) -> list[str]:
    """Split on `&&`, `||`, `;`, `|` while respecting quotes."""
    segments: list[str] = []
    current: list[str] = []
    quote = ""
    for char in command:
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
            current.append(char)
        elif char in ";&|":
            segments.append("".join(current))
            current = []
        else:
            current.append(char)
    segments.append("".join(current))
    return [segment for segment in segments if segment.strip()]


def _tokenize(segment: str) -> list[str]:
    return [token.strip("\"'") for token in re.findall(r'"[^"]*"|\'[^\']*\'|\S+', segment)]


def whole_suite_reason(
    command: str, root: Path, timeout_s: float, narrow: str
) -> str | None:
    """Why ``command`` would run an entire test suite, or ``None`` if it is fine.

    A whole-suite run is the one command shape the harness cannot make useful: on these
    repositories it takes minutes, so it is killed at ``timeout_s`` and returns nothing the
    model can act on - it only burns wall clock. The prompt asks for narrow runs; this is the
    part that does not depend on the model agreeing.

    Directory targets and bare ``pytest`` are refused. Several explicit files, node ids and
    ``-k`` filters stay available, as do collection-only runs (cheap, and the honest way to
    discover node ids).
    """
    root = Path(root)
    for segment in _split_segments(command):
        tokens = _tokenize(segment)
        for index, token in enumerate(tokens):
            if Path(token.replace("\\", "/")).name.lower() not in {"pytest", "pytest.exe"}:
                continue
            # `pytest` is also a perfectly good argument to `rg`/`grep`; only a token that
            # actually starts an invocation gets to decide what the command runs.
            if index and tokens[index - 1].lower() != "-m":
                previous = Path(tokens[index - 1].replace("\\", "/")).name.lower()
                if previous not in {"python", "python.exe", "python3", "python3.exe", "py", "py.exe"}:
                    continue
            targets: list[str] = []
            cheap = False
            skip_next = False
            for arg in tokens[index + 1 :]:
                if skip_next:
                    skip_next = False
                    continue
                if arg.startswith("-"):
                    if arg in PYTEST_VALUE_OPTIONS:
                        skip_next = True
                    if arg in PYTEST_CHEAP_FLAGS:
                        cheap = True
                    continue
                targets.append(arg)
            if cheap:
                continue
            directory = next((t for t in targets if (root / t).is_dir()), None)
            if directory is not None:
                return (
                    f"error: refusing to run the whole test suite - '{directory}' is a directory "
                    f"target. It takes minutes here, is killed after {timeout_s:.0f}s and returns "
                    "nothing you can act on. Run the task's test command instead:\n"
                    f"  {narrow}\n"
                    "Narrow it with file paths, node ids (path::Class::test) or -k. "
                    "Use --collect-only if you only need the list of tests."
                )
            if not targets:
                return (
                    "error: refusing to run pytest with no target - that is the whole suite. "
                    f"Run the task's test command instead:\n  {narrow}"
                )
    return None
