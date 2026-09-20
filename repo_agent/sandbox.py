"""Execution backends. The agent never touches the host directly.

``LocalSandbox`` exists so the loop can be developed and tested without Docker;
``DockerSandbox`` is the production isolation boundary described in the design doc.
"""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

from .config import RunConfig
from .proc import run_bounded


@dataclass(slots=True)
class ExecResult:
    command: str
    exit_code: int
    output: str
    truncated: bool
    duration_s: float
    timed_out: bool = False

    def render(self) -> str:
        status = "timeout" if self.timed_out else f"exit_code={self.exit_code}"
        return f"$ {self.command}\n[{status}, {self.duration_s:.1f}s]\n{self.output}"


def truncate(text: str, limit: int) -> tuple[str, bool]:
    """Keep the head and the tail; the middle is noise and costs tokens."""
    if len(text) <= limit:
        return text, False
    head = int(limit * 0.6)
    tail = limit - head
    omitted = len(text) - limit
    return f"{text[:head]}\n... [{omitted} chars omitted] ...\n{text[-tail:]}", True


class Sandbox(Protocol):
    root: Path

    def run(self, command: str, timeout: float = 180.0) -> ExecResult: ...

    def close(self) -> None: ...


def _decode(raw: bytes | None) -> str:
    return (raw or b"").decode("utf-8", errors="replace")


class LocalSandbox:
    """Runs commands on the host inside the workspace directory.

    Development and unit-test backend only: there is no isolation here, so it must
    never be pointed at untrusted repositories that also hold real credentials.
    """

    def __init__(
        self,
        root: Path,
        max_output_bytes: int = 8_000,
        env: dict[str, str] | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.max_output_bytes = max_output_bytes
        self.extra_env = dict(env or {})

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(
            {
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                "GIT_PAGER": "cat",
                "PAGER": "cat",
                "NO_COLOR": "1",
            }
        )
        env.update(self.extra_env)
        return env

    def run(self, command: str, timeout: float = 180.0) -> ExecResult:
        start = time.time()
        result = run_bounded(command, cwd=self.root, env=self._env(), timeout=timeout)
        out, truncated = truncate(result.output, self.max_output_bytes)
        return ExecResult(
            command,
            result.exit_code,
            out,
            truncated,
            time.time() - start,
            result.timed_out,
        )

    def close(self) -> None:
        return None


class DockerSandbox:
    """One-shot container per run: no network by default, no host filesystem.

    The command is piped to the container shell over stdin, which sidesteps every
    host-shell quoting problem and keeps the payload out of the process table.
    """

    def __init__(self, cfg: RunConfig, max_output_bytes: int = 8_000) -> None:
        self.root = Path(cfg.workspace).resolve()
        self.image = cfg.image
        self.network = cfg.network
        self.shell: Sequence[str] = cfg.container_shell
        self.memory_limit = cfg.memory_limit
        self.cpu_limit = cfg.cpu_limit
        self.env = dict(cfg.env)
        self.max_output_bytes = max_output_bytes

    def _argv(self, name: str) -> list[str]:
        argv = [
            "docker",
            "run",
            "--rm",
            "-i",
            "--name",
            name,
            "--network",
            self.network,
            "--memory",
            self.memory_limit,
            "--cpus",
            self.cpu_limit,
            "--pids-limit",
            "512",
            "-v",
            f"{self.root}:/workspace",
            "-w",
            "/workspace",
            "-e",
            "PYTHONUTF8=1",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
        ]
        for key, value in self.env.items():
            argv.extend(["-e", f"{key}={value}"])
        argv.extend([self.image, *self.shell])
        return argv

    def run(self, command: str, timeout: float = 180.0) -> ExecResult:
        name = f"repo-agent-{uuid.uuid4().hex[:12]}"
        start = time.time()
        try:
            proc = subprocess.run(
                self._argv(name),
                input=command.encode("utf-8"),
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            # The docker client dies with the timeout; the container does not.
            subprocess.run(
                ["docker", "rm", "-f", name], capture_output=True, check=False
            )
            text = _decode(exc.stdout) + _decode(exc.stderr)
            out, truncated = truncate(text, self.max_output_bytes)
            return ExecResult(command, 124, out, truncated, time.time() - start, True)
        text = _decode(proc.stdout) + _decode(proc.stderr)
        out, truncated = truncate(text, self.max_output_bytes)
        return ExecResult(command, proc.returncode, out, truncated, time.time() - start)

    def close(self) -> None:
        return None


def make_sandbox(cfg: RunConfig) -> Sandbox:
    if cfg.sandbox == "docker":
        return DockerSandbox(cfg, max_output_bytes=cfg.max_output_bytes)
    if cfg.sandbox == "local":
        return LocalSandbox(
            cfg.workspace, max_output_bytes=cfg.max_output_bytes, env=cfg.env
        )
    raise ValueError(f"unknown sandbox backend: {cfg.sandbox!r}")
