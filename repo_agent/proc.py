"""Bounded subprocess execution, shared by the sandbox and the harness.

Why this is a module instead of two calls to ``subprocess.run(timeout=...)``: on
Windows a timeout only reaps the *direct* child. With ``shell=True`` that child is
``cmd.exe``, so ``pytest`` is a grandchild - and a surviving grandchild keeps the
stdout pipe open, which makes the follow-up read block forever. The timeout then
stops bounding anything: the agent burns ten minutes on one tool call and the
harness books the wall time as if it were model latency.

Everything that shells out on a budget routes through here so the tree always dies.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

#: How long to wait for the pipes to drain after the tree has been killed.
DRAIN_GRACE_S = 10.0


@dataclass(slots=True)
class ProcResult:
    exit_code: int
    output: str
    timed_out: bool
    duration_s: float


def _kill_tree(pid: int) -> None:
    """Kill the shell *and* its descendants; a bare kill leaves orphans holding pipes."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            check=False,
        )
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _decode(raw: bytes | None) -> str:
    return (raw or b"").decode("utf-8", errors="replace")


def run_bounded(
    command: str,
    *,
    cwd: Path | str,
    env: dict[str, str],
    timeout: float,
) -> ProcResult:
    """Run ``command`` in its own process group and return within ~``timeout``."""
    start = time.time()
    group = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if os.name == "nt"
        else {"start_new_session": True}
    )
    proc = subprocess.Popen(
        command,
        shell=True,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        **group,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _kill_tree(proc.pid)
        try:
            stdout, stderr = proc.communicate(timeout=DRAIN_GRACE_S)
        except subprocess.TimeoutExpired:
            # Even the tree kill did not release the pipe: stop waiting, close our end
            # and keep whatever was already read.
            proc.kill()
            stdout, stderr = exc.output, exc.stderr
        except (OSError, ValueError):
            stdout, stderr = exc.output, exc.stderr
        return ProcResult(
            exit_code=124,
            output=_decode(stdout) + _decode(stderr),
            timed_out=True,
            duration_s=time.time() - start,
        )
    return ProcResult(
        exit_code=proc.returncode,
        output=_decode(stdout) + _decode(stderr),
        timed_out=False,
        duration_s=time.time() - start,
    )
