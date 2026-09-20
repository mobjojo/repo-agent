"""Path and scope guards: the single place that decides what the agent may touch.

All tool file access goes through :class:`Guard`; nothing else resolves paths.
"""

from __future__ import annotations

import fnmatch
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
