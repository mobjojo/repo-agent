"""Configuration objects for the repository-level coding agent (M1 skeleton)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

# Files the agent may never modify. If it could edit tests it could "fix" an issue
# by weakening the very signal we score it with.
DEFAULT_PROTECTED_GLOBS: tuple[str, ...] = (
    "**/tests/**",
    "**/test/**",
    "**/test_*.py",
    "**/*_test.py",
    "**/conftest.py",
    "**/tox.ini",
    "**/pytest.ini",
    "**/setup.cfg",
)

# Version-control internals are write-forbidden (tamper resistance) and hidden
# from reads, so they never burn context either.
DEFAULT_FORBIDDEN_PREFIXES: tuple[str, ...] = (".git/",)

DEFAULT_TEST_COMMAND = "python -m unittest discover -s tests -t . -v"


@dataclass(slots=True)
class Budget:
    """Hard ceilings. Hitting any single one terminates the agent loop."""

    max_steps: int = 20
    max_tokens: int = 200_000
    max_cost_usd: float = 2.0
    max_wall_seconds: float = 900.0


@dataclass(slots=True)
class RunConfig:
    task: str
    workspace: Path
    test_command: str = DEFAULT_TEST_COMMAND
    model: str = "gpt-4o-mini"
    budget: Budget = field(default_factory=Budget)
    # "local" is the dev/CI backend; "docker" is the production isolation boundary.
    sandbox: str = "local"
    image: str = "python:3.11-slim"
    network: str = "none"
    container_shell: tuple[str, ...] = ("bash", "-s")
    memory_limit: str = "2g"
    cpu_limit: str = "2"
    protected_globs: tuple[str, ...] = DEFAULT_PROTECTED_GLOBS
    forbidden_prefixes: tuple[str, ...] = DEFAULT_FORBIDDEN_PREFIXES
    # When non-empty, the agent may only *write* to paths matching these patterns.
    editable_globs: tuple[str, ...] = ()
    # Task-level environment variables, injected into the sandbox and into every
    # verification command (e.g. {"PYTHONPATH": "src"} for src-layout repositories).
    env: dict[str, str] = field(default_factory=dict)
    max_output_bytes: int = 8_000
    max_file_bytes: int = 400_000
    bash_timeout_s: float = 90.0
    notes_max_chars: int = 4_000
    temperature: float = 0.0
    max_response_tokens: int = 4_096
    run_dir: Path | None = None


def resolve_run_dir(cfg: RunConfig) -> Path:
    """Artifacts live *outside* the workspace so they can never pollute the diff."""
    if cfg.run_dir is not None:
        return Path(cfg.run_dir)
    workspace = Path(cfg.workspace).resolve()
    return workspace.parent / f"{workspace.name}.runs" / time.strftime("%Y%m%d-%H%M%S")
