"""Wires the sandbox, tools, graph and artifacts together: one call per task."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import RunConfig, resolve_run_dir
from .graph import GraphDeps, build_graph, finalize_artifacts
from .guard import Guard
from .llm import ChatClient, LiteLLMClient
from .prompts import build_task_message
from .sandbox import make_sandbox
from .state import AgentState, initial_state
from .task import repo_overview
from .tools import WorkspaceTools
from .trace import Tracer


@dataclass(slots=True)
class RunResult:
    task: str
    stop_reason: str
    steps: int
    tokens: int
    cost_usd: float
    duration_s: float
    submitted: bool
    patch: str
    patch_path: str
    run_dir: str
    touched_files: list[str] = field(default_factory=list)
    contract_violations: list[str] = field(default_factory=list)
    applies_cleanly: bool = False
    added_lines: int = 0
    removed_lines: int = 0
    notes_path: str = ""
    trace_path: str = ""
    error: str = ""

    @property
    def valid(self) -> bool:
        """A patch that is scoped correctly and applies to the base commit."""
        return bool(self.patch) and self.applies_cleanly and not self.contract_violations

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["valid"] = self.valid
        return data


def run_agent(
    cfg: RunConfig,
    llm: ChatClient | None = None,
    reference_repo: Path | None = None,
    keep_notes: bool = True,
) -> RunResult:
    started = time.time()
    run_dir = resolve_run_dir(cfg)
    run_dir.mkdir(parents=True, exist_ok=True)
    notes_path = run_dir / "NOTES.md"
    notes_path.write_text(f"# notes: {cfg.task.splitlines()[0][:80]}\n", encoding="utf-8")
    tracer = Tracer(run_dir / "trace.jsonl")

    sandbox = make_sandbox(cfg)
    guard = Guard(
        root=Path(cfg.workspace),
        protected_globs=cfg.protected_globs,
        forbidden_prefixes=cfg.forbidden_prefixes,
        editable_globs=cfg.editable_globs,
    )
    client = llm or LiteLLMClient(
        cfg.model,
        temperature=cfg.temperature,
        max_tokens=cfg.max_response_tokens,
    )
    deps = GraphDeps(
        cfg=cfg,
        llm=client,
        tools=WorkspaceTools(cfg, sandbox, guard),
        tracer=tracer,
        run_dir=run_dir,
        notes_path=notes_path,
        reference_repo=Path(reference_repo) if reference_repo else None,
    )

    tracer.event(
        "run_start",
        model=cfg.model,
        sandbox=cfg.sandbox,
        workspace=str(cfg.workspace),
        test_command=cfg.test_command,
        budget=asdict(cfg.budget),
    )
    graph = build_graph(deps)
    state = initial_state(cfg, build_task_message(cfg, repo_overview(Path(cfg.workspace)), str(notes_path)))
    error = ""
    try:
        final: AgentState = graph.invoke(
            state, config={"recursion_limit": 4 * cfg.budget.max_steps + 10}
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        tracer.event("run_error", error=error)
        carried = {**state, "stop_reason": "error"}
        final = {**carried, **finalize_artifacts(deps, carried)}  # never lose the diff
    finally:
        sandbox.close()

    result = RunResult(
        task=cfg.task,
        stop_reason=str(final.get("stop_reason", "")),
        steps=int(final.get("steps", 0)),
        tokens=int(final.get("tokens", 0)),
        cost_usd=float(final.get("cost_usd", 0.0)),
        duration_s=round(time.time() - started, 2),
        submitted=bool(final.get("submitted", False)),
        patch=str(final.get("final_patch", "")),
        patch_path=str(final.get("patch_path", "")),
        run_dir=str(run_dir),
        touched_files=list(final.get("touched_files", [])),
        contract_violations=list(final.get("contract_violations", [])),
        applies_cleanly=bool(final.get("applies_cleanly", False)),
        added_lines=int(final.get("added_lines", 0)),
        removed_lines=int(final.get("removed_lines", 0)),
        notes_path=str(notes_path) if keep_notes else "",
        trace_path=str(tracer.path) if tracer.path else "",
        error=error,
    )
    tracer.event(
        "run_end",
        stop_reason=result.stop_reason,
        steps=result.steps,
        tokens=result.tokens,
        cost_usd=result.cost_usd,
        duration_s=result.duration_s,
        valid=result.valid,
    )
    (run_dir / "result.json").write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result
