"""The LangGraph state machine: one agent loop, three nodes, explicit routing.

    START -> agent -> (tool_calls?) -> tools -> (keep going?) -> agent -> ... -> finalize
                   \\-> (done / budget / no tool call) ---------------------> finalize

Both hops are conditional on purpose. If `tools -> agent` were unconditional, every
termination (submit, budget, loop detection) would still burn one more model call before
the guard could fire.

The loop is deliberately boring. Everything interesting (retrieval, sub-agents, review
passes) plugs into this skeleton only once a measurement says it helps.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from .config import RunConfig
from .llm import ChatClient
from .patch import collect_patch, validate_patch
from .prompts import build_system_prompt
from .state import AgentState
from .tools import TOOL_SCHEMAS, WorkspaceTools
from .trace import Tracer

# The same tool call repeated this many times earns a warning, not a death sentence: a model
# that is still probing Python semantics is not stuck, and a hard stop returns an empty patch
# (the worst possible outcome) from a run that might have submitted one step later.
REPEAT_WARN = 3
# Repeating past the warning anyway means the model really is looping; kill it here.
REPEAT_LIMIT = 5
NOTES_STEP_CHARS = 1_200

LOOP_WARNING = (
    "[loop warning] That was the same tool call {warn} times in a row, so the result will not "
    "change. Do something different now: edit a file to fix the bug, or submit the patch you "
    "already have. A {limit}th identical call ends the run with an empty patch."
)


def _trailing_repeats(signatures: list[str]) -> int:
    """Length of the run of identical tool-call signatures at the end of the window."""
    if not signatures:
        return 0
    last = signatures[-1]
    count = 0
    for signature in reversed(signatures):
        if signature != last:
            break
        count += 1
    return count


@dataclass(slots=True)
class GraphDeps:
    cfg: RunConfig
    llm: ChatClient
    tools: WorkspaceTools
    tracer: Tracer
    run_dir: Path
    notes_path: Path
    reference_repo: Path | None = None


def budget_stop_reason(state: AgentState, cfg: RunConfig) -> str:
    """The only termination authority besides `submit` and loop detection."""
    if state.get("steps", 0) >= cfg.budget.max_steps:
        return "budget:steps"
    if state.get("tokens", 0) >= cfg.budget.max_tokens:
        return "budget:tokens"
    if state.get("cost_usd", 0.0) >= cfg.budget.max_cost_usd:
        return "budget:cost"
    elapsed = time.time() - state.get("started_at", time.time())
    if elapsed >= cfg.budget.max_wall_seconds:
        return "budget:wall_clock"
    return ""


def _signature(name: str, args: dict[str, Any]) -> str:
    raw = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    return f"{name}:{raw[:200]}"


def _trim_args(args: dict[str, Any], limit: int = 400) -> dict[str, Any]:
    trimmed: dict[str, Any] = {}
    for key, value in (args or {}).items():
        text = value if isinstance(value, str) else json.dumps(value, default=str)
        trimmed[key] = text if len(text) <= limit else text[:limit] + f"...(+{len(text) - limit})"
    return trimmed


def _read_notes(deps: GraphDeps) -> str:
    try:
        text = deps.notes_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    limit = deps.cfg.notes_max_chars
    return text[-limit:] if len(text) > limit else text


def _append_notes(deps: GraphDeps, step: int, text: str) -> None:
    text = text.strip()
    if not text:
        return
    if len(text) > NOTES_STEP_CHARS:
        text = text[:NOTES_STEP_CHARS] + " ..."
    with deps.notes_path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n## step {step}\n{text}\n")


def _agent_node(deps: GraphDeps) -> Callable[[AgentState], dict[str, Any]]:
    def node(state: AgentState) -> dict[str, Any]:
        cfg = deps.cfg
        prompt = [SystemMessage(content=build_system_prompt(cfg, _read_notes(deps)))]
        prompt.extend(state["messages"])
        started = time.time()
        try:
            reply, usage = deps.llm.complete(prompt, TOOL_SCHEMAS)
        except Exception as exc:  # a model outage must not lose the trace
            deps.tracer.event("llm_error", error=f"{type(exc).__name__}: {exc}")
            return {
                "messages": [AIMessage(content=f"model call failed: {exc}")],
                "stop_reason": "llm_error",
                "last_error": f"{type(exc).__name__}: {exc}",
                "steps": state.get("steps", 0) + 1,
            }
        steps = state.get("steps", 0) + 1
        calls = list(getattr(reply, "tool_calls", []) or [])
        deps.tracer.event(
            "llm_call",
            step=steps,
            duration_s=round(time.time() - started, 3),
            tokens=usage.tokens,
            cost_usd=usage.cost_usd,
            tools=[call["name"] for call in calls],
        )
        # Externalised memory: reasoning goes to NOTES.md, the window keeps a stub.
        text = reply.content if isinstance(reply.content, str) else ""
        if calls and text.strip():
            _append_notes(deps, steps, text)
            brief = text.strip().splitlines()[0][:200]
            reply = AIMessage(content=brief, tool_calls=calls)
        elif text.strip():
            _append_notes(deps, steps, text)
        return {
            "messages": [reply],
            "steps": steps,
            "tokens": state.get("tokens", 0) + usage.tokens,
            "cost_usd": round(state.get("cost_usd", 0.0) + usage.cost_usd, 6),
        }

    return node


def _tools_node(deps: GraphDeps) -> Callable[[AgentState], dict[str, Any]]:
    def node(state: AgentState) -> dict[str, Any]:
        last = state["messages"][-1]
        signatures = list(state.get("recent_calls", []))
        submitted = state.get("submitted", False)
        observations: list[ToolMessage] = []
        for call in list(getattr(last, "tool_calls", []) or []):
            name = call["name"]
            args = call.get("args") or {}
            signatures.append(_signature(name, args))
            started = time.time()
            outcome = deps.tools.dispatch(name, args)
            deps.tracer.event(
                "tool_call",
                step=state.get("steps", 0),
                tool=name,
                args=_trim_args(args),
                ok=outcome.ok,
                submitted=outcome.submitted,
                duration_s=round(time.time() - started, 3),
                observation=outcome.content[:2_000],
            )
            observations.append(ToolMessage(content=outcome.content, tool_call_id=call["id"]))
            submitted = submitted or outcome.submitted
        signatures = signatures[-8:]
        repeats = _trailing_repeats(signatures)
        stop = ""
        if repeats >= REPEAT_LIMIT:
            stop = "no_progress:repeated_tool_call"
            deps.tracer.event(
                "loop_detected",
                step=state.get("steps", 0),
                signature=signatures[-1],
                repeats=repeats,
            )
        elif repeats == REPEAT_WARN:
            deps.tracer.event(
                "loop_warning",
                step=state.get("steps", 0),
                signature=signatures[-1],
                repeats=repeats,
            )
            observations.append(
                HumanMessage(content=LOOP_WARNING.format(warn=REPEAT_WARN, limit=REPEAT_LIMIT))
            )
        update: dict[str, Any] = {
            "messages": observations,
            "recent_calls": signatures,
            "submitted": submitted,
        }
        if stop:
            update["stop_reason"] = stop
        return update

    return node


def finalize_artifacts(deps: GraphDeps, state: AgentState) -> dict[str, Any]:
    """Compute the deliverable and the contract verdict. Safe to call twice."""
    cfg = deps.cfg
    stop_reason = (
        state.get("stop_reason")
        or budget_stop_reason(state, cfg)
        or ("submitted" if state.get("submitted") else "agent_finished")
    )
    try:
        patch = collect_patch(cfg.workspace)
    except Exception as exc:
        deps.tracer.event("patch_error", error=f"{type(exc).__name__}: {exc}")
        patch = ""
    contract = validate_patch(patch, cfg.protected_globs, deps.reference_repo)
    patch_path = deps.run_dir / "patch.diff"
    # newline="" keeps the artifact byte-identical to what `git diff` produced.
    patch_path.write_text(patch, encoding="utf-8", newline="")
    deps.tracer.event(
        "finalize",
        stop_reason=stop_reason,
        touched_files=contract.touched_files,
        violations=contract.violations,
        applies_cleanly=contract.applies_cleanly,
        added_lines=contract.added_lines,
        removed_lines=contract.removed_lines,
    )
    return {
        "final_patch": patch,
        "touched_files": contract.touched_files,
        "contract_violations": contract.violations,
        "patch_path": str(patch_path),
        "applies_cleanly": contract.applies_cleanly,
        "added_lines": contract.added_lines,
        "removed_lines": contract.removed_lines,
        "stop_reason": stop_reason,
    }


def _finalize_node(deps: GraphDeps) -> Callable[[AgentState], dict[str, Any]]:
    def node(state: AgentState) -> dict[str, Any]:
        return finalize_artifacts(deps, state)

    return node


def _route_after_agent(deps: GraphDeps) -> Callable[[AgentState], str]:
    def route(state: AgentState) -> str:
        if state.get("submitted") or state.get("stop_reason"):
            return "finalize"
        reason = budget_stop_reason(state, deps.cfg)
        if reason:
            deps.tracer.event(
                "budget_stop",
                reason=reason,
                steps=state.get("steps", 0),
                tokens=state.get("tokens", 0),
                cost_usd=state.get("cost_usd", 0.0),
            )
            return "finalize"
        last = state["messages"][-1]
        if not getattr(last, "tool_calls", None):
            deps.tracer.event("stop", reason="no_tool_call")
            return "finalize"
        return "tools"

    return route


def _route_after_tools(deps: GraphDeps) -> Callable[[AgentState], str]:
    def route(state: AgentState) -> str:
        # The tools node is where submit, loop detection and (wall-clock) budget expiry
        # become knowable, so the decision has to be re-taken here.
        if state.get("submitted") or state.get("stop_reason"):
            return "finalize"
        reason = budget_stop_reason(state, deps.cfg)
        if reason:
            deps.tracer.event("budget_stop", reason=reason, steps=state.get("steps", 0))
            return "finalize"
        return "agent"

    return route


def build_graph(deps: GraphDeps) -> Any:
    graph = StateGraph(AgentState)
    graph.add_node("agent", _agent_node(deps))
    graph.add_node("tools", _tools_node(deps))
    graph.add_node("finalize", _finalize_node(deps))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        _route_after_agent(deps),
        {"tools": "tools", "finalize": "finalize"},
    )
    graph.add_conditional_edges(
        "tools",
        _route_after_tools(deps),
        {"agent": "agent", "finalize": "finalize"},
    )
    graph.add_edge("finalize", END)
    return graph.compile()
