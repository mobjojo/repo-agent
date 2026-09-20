"""The explicit graph state: the contract every node reads from and writes to."""

from __future__ import annotations

import time
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph.message import add_messages

from .config import RunConfig


class AgentState(TypedDict, total=False):
    # Conversation spine. The system prompt is re-prepended on every model call
    # instead of being stored, so it always reflects the current config.
    messages: Annotated[list[BaseMessage], add_messages]
    task: str
    steps: int
    tokens: int
    cost_usd: float
    started_at: float
    submitted: bool
    stop_reason: str
    # Rolling window of recent tool signatures, used to detect no-progress loops.
    recent_calls: list[str]
    final_patch: str
    touched_files: list[str]
    contract_violations: list[str]
    patch_path: str
    applies_cleanly: bool
    added_lines: int
    removed_lines: int


def initial_state(cfg: RunConfig, task_message: str) -> AgentState:
    return AgentState(
        messages=[HumanMessage(content=task_message)],
        task=cfg.task,
        steps=0,
        tokens=0,
        cost_usd=0.0,
        started_at=time.time(),
        submitted=False,
        stop_reason="",
        recent_calls=[],
        final_patch="",
        touched_files=[],
        contract_violations=[],
        patch_path="",
        applies_cleanly=False,
        added_lines=0,
        removed_lines=0,
    )
