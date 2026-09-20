"""A repository-level coding agent: the M1 walking skeleton.

The public surface is intentionally tiny: build a config, call `run_agent`, read the patch.
"""

from .config import Budget, RunConfig
from .llm import LiteLLMClient, ScriptedLLM
from .patch import validate_patch
from .runner import RunResult, run_agent
from .task import prepare_workspace, repo_overview

__all__ = [
    "Budget",
    "LiteLLMClient",
    "RunConfig",
    "RunResult",
    "ScriptedLLM",
    "prepare_workspace",
    "repo_overview",
    "run_agent",
    "validate_patch",
]
