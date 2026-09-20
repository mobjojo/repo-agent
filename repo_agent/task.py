"""Task preparation: build the workspace checkout and the repo overview shown to the model."""

from __future__ import annotations

import subprocess
from collections import Counter
from pathlib import Path

OVERVIEW_FILE_LIMIT = 250

#: Workspace-local scratchpad for throwaway scripts. Excluded through .git/info/exclude,
#: which is local to the checkout, so nothing written here can reach the submitted patch.
SCRATCH_DIR = ".repo-agent"


def _git(cwd: Path, *args: str, timeout: float = 300.0) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def prepare_workspace(
    repo: str | Path, dest: str | Path, base_commit: str | None = None
) -> Path:
    """Clone ``repo`` into ``dest`` and check out ``base_commit`` (default: HEAD).

    ``core.autocrlf`` is forced off so that line endings - and therefore every diff we
    produce or validate - are byte-accurate on Windows as well as Linux. The setting has
    to be passed to ``git clone`` itself: if it is applied afterwards the checkout has
    already rewritten every LF in the working tree and the "clean" clone diffs as dirty.
    """
    dest = Path(dest).resolve()
    if dest.exists():
        raise FileExistsError(f"{dest} already exists; refusing to reuse a dirty checkout")
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            "git",
            "clone",
            "--quiet",
            "--no-hardlinks",
            "--config",
            "core.autocrlf=false",
            "--config",
            "core.eol=lf",
            str(repo),
            str(dest),
        ],
        capture_output=True,
        timeout=1_800,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git clone failed: {proc.stdout.decode('utf-8', 'replace')}"
            f"{proc.stderr.decode('utf-8', 'replace')}"
        )
    _git(dest, "config", "core.autocrlf", "false")
    _git(dest, "config", "user.email", "agent@localhost")
    _git(dest, "config", "user.name", "repo-agent")
    install_scratch_exclude(dest)
    if base_commit:
        checkout = _git(dest, "checkout", "--quiet", base_commit)
        if checkout.returncode != 0:
            raise RuntimeError(
                f"git checkout {base_commit} failed: "
                f"{checkout.stderr.decode('utf-8', 'replace')}"
            )
    status = _git(dest, "status", "--porcelain")
    if status.stdout.strip():
        raise RuntimeError(
            "fresh checkout is not clean; refusing to score against it (check "
            f"line-ending or filter configuration): {status.stdout.decode('utf-8', 'replace')[:400]}"
        )
    return dest


def install_scratch_exclude(workspace: Path) -> None:
    """Give the agent a scratchpad that is legal to write and invisible to the patch.

    The guard refuses every path outside the workspace, so the classic advice - "write your
    scratch script under %TEMP% / /tmp" - is an instruction the tools cannot carry out.
    Models then put the script in the repository root, and it ships in the diff: in the M3
    batch two click tasks submitted 91 lines of debug prints and nothing else. Excluding one
    directory locally removes the conflict instead of relying on model discipline.
    """
    info = Path(workspace) / ".git" / "info"
    info.mkdir(parents=True, exist_ok=True)
    exclude = info / "exclude"
    entry = f"/{SCRATCH_DIR}/"
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if entry in existing.splitlines():
        return
    with exclude.open("a", encoding="utf-8", newline="\n") as handle:
        if existing and not existing.endswith("\n"):
            handle.write("\n")
        handle.write(entry + "\n")


def head_commit(workspace: Path) -> str:
    proc = _git(workspace, "rev-parse", "HEAD")
    return proc.stdout.decode("utf-8", "replace").strip()


def tracked_files(workspace: Path, limit: int = OVERVIEW_FILE_LIMIT) -> list[str]:
    proc = _git(workspace, "ls-files")
    files = [line for line in proc.stdout.decode("utf-8", "replace").splitlines() if line.strip()]
    return files[:limit]


def repo_overview(workspace: Path, limit: int = OVERVIEW_FILE_LIMIT) -> str:
    """A cheap orientation aid: file list plus a language histogram, capped."""
    files = tracked_files(workspace, limit=limit)
    if not files:
        return "(empty repository)"
    suffixes = Counter(Path(name).suffix for name in files if Path(name).suffix)
    top = ", ".join(f"{suffix} x{count}" for suffix, count in suffixes.most_common(5))
    lines = [f"Tracked files ({len(files)} shown), dominant types: {top}", ""]
    lines.extend(f"- {name}" for name in files)
    return "\n".join(lines)
