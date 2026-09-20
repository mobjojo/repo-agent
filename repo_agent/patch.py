"""The deliverable contract: a unified diff that applies cleanly to the base commit.

Nothing the agent "says" counts as a result. The only artifact that is scored is the
patch produced here, and it is rejected outright if it touches protected files.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .guard import normalize, protected_files_in


@dataclass(slots=True)
class PatchContract:
    patch: str = ""
    touched_files: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    applies_cleanly: bool = False
    apply_error: str = ""
    added_lines: int = 0
    removed_lines: int = 0

    @property
    def ok(self) -> bool:
        return bool(self.patch) and self.applies_cleanly and not self.violations


def git(workspace: Path, *args: str, timeout: float = 120.0) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args], cwd=str(workspace), capture_output=True, timeout=timeout
    )
    return proc.returncode, (proc.stdout + proc.stderr).decode("utf-8", errors="replace")


def collect_patch(workspace: Path) -> str:
    """Unified diff of every change in the working tree, new files included."""
    code, out = git(workspace, "add", "-A", "-N")
    if code != 0:
        raise RuntimeError(f"git add -N failed: {out}")
    code, out = git(workspace, "diff", "--no-ext-diff", "--no-color", "--no-renames")
    if code != 0:
        raise RuntimeError(f"git diff failed: {out}")
    return out


def touched_files(patch: str) -> list[str]:
    files: set[str] = set()
    for line in patch.splitlines():
        if not line.startswith("+++ "):
            continue
        path = line[4:].strip()
        if path == "/dev/null":
            continue
        if path.startswith("b/"):
            path = path[2:]
        if path:
            files.add(normalize(path))
    return sorted(files)


def diff_stat(patch: str) -> tuple[int, int]:
    added = sum(
        1 for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++")
    )
    removed = sum(
        1 for line in patch.splitlines() if line.startswith("-") and not line.startswith("---")
    )
    return added, removed


def applies_cleanly(patch: str, reference_repo: Path) -> tuple[bool, str]:
    """``git apply --check`` against a pristine checkout of the base commit."""
    if not patch.strip():
        return False, "empty patch"
    proc = subprocess.run(
        ["git", "apply", "--check", "--verbose", "--whitespace=nowarn", "-"],
        cwd=str(reference_repo),
        input=patch.encode("utf-8"),
        capture_output=True,
        timeout=120.0,
    )
    return proc.returncode == 0, (proc.stdout + proc.stderr).decode("utf-8", errors="replace")


def validate_patch(
    patch: str,
    protected_globs: tuple[str, ...] = (),
    reference_repo: Path | None = None,
) -> PatchContract:
    files = touched_files(patch)
    added, removed = diff_stat(patch)
    contract = PatchContract(
        patch=patch, touched_files=files, added_lines=added, removed_lines=removed
    )
    if not patch.strip():
        contract.violations.append("no changes were produced")
        return contract
    if not files:
        contract.violations.append("patch does not touch any file")
    for name in protected_files_in(files, protected_globs):
        contract.violations.append(f"touched a protected file: {name}")
    if reference_repo is not None:
        contract.applies_cleanly, contract.apply_error = applies_cleanly(patch, reference_repo)
        if not contract.applies_cleanly:
            contract.violations.append("patch does not apply cleanly to the base commit")
    else:
        contract.applies_cleanly = True
    return contract
