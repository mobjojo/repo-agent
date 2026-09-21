"""Batch evaluation: the harness is the judge, the agent never scores itself.

Task file format (one JSON object per line):

    {
      "id": "toy-001",
      "repo": "work/toyrepo",              # local path or clone URL
      "prepare": "python tests/make_toy_repo.py work/toyrepo",   # optional, run first
      "base_commit": null,
      "issue": "add() returns the wrong result",
      "test_command": "python -m unittest discover -s tests -t . -v",
      "fail_to_pass": ["python -m unittest tests.test_ops"],     # must FAIL before, PASS after
      "pass_to_pass": [],                                        # must PASS both times
      "gold_patch": "fixtures/toy-001/gold.patch",               # optional: the reference fix
      "leak_terms": ["1c20dc6"],                                 # optional: strings that must NOT
                                                                 # appear in the issue text
      "protected_globs": ["**/tests/**"],                        # optional override
      "env": {"PYTHONPATH": "src"},                              # optional, for src-layout repos
      "model": "gpt-4o-mini",                                    # optional override
      "max_steps": 20                                            # optional override
    }

Per task the harness: rebuilds a clean checkout, proves the task is actually broken
(fail_to_pass fails before the fix), optionally proves it is solvable at all by applying
the reference fix, runs the agent, checks the patch contract, then applies the agent's
patch to an untouched checkout and re-runs both test sets.

Two gates are worth more than the rest of this file, because a task that fails either one
silently corrupts every number the harness prints: an unsolvable task (nothing can turn
``fail_to_pass`` green) and an unbroken task (it was already green). ``--check-only``
rehearses both without spending a token, which is why it is safe to run before every batch.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from repo_agent.config import Budget, RunConfig
from repo_agent.proc import run_bounded
from repo_agent.runner import run_agent
from repo_agent.task import head_commit, prepare_workspace


@dataclass(slots=True)
class Task:
    id: str
    repo: str
    # Give the issue text directly, or point at a file next to the task list.
    issue: str = ""
    test_command: str = "python -m unittest discover -s tests -t . -v"
    fail_to_pass: list[str] = field(default_factory=list)
    pass_to_pass: list[str] = field(default_factory=list)
    base_commit: str | None = None
    prepare: str | None = None
    protected_globs: list[str] | None = None
    editable_globs: list[str] | None = None
    env: dict[str, str] = field(default_factory=dict)
    issue_file: str | None = None
    # Path to the reference fix, relative to the task file. Used by --check-only to prove
    # the task is solvable; never shown to the agent.
    gold_patch: str | None = None
    # Provenance belongs in the task file, never in the text the agent reads. A 7-char
    # fix sha, a PR number or the upstream commit subject is enough for the model to skip
    # the diagnosis, and the result does not look like cheating - it looks like a
    # suspiciously cheap pass. Declared per task and enforced before anything is cloned.
    leak_terms: list[str] = field(default_factory=list)
    model: str | None = None
    max_steps: int | None = None
    # Both ceilings have to be non-binding for the score to be about the model rather than
    # about the budget. On the 2026-09-21 default-budget batch (m3-golden-20-j4b) five runs
    # ended on a ceiling and three of those had already produced a correct patch - their
    # verdict was decided by where the ceiling happened to land, not by the agent.
    # tasks/README.md derives both numbers from the observed successful runs.
    max_tokens: int | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        known = {name for name in cls.__dataclass_fields__}
        payload = {key: value for key, value in data.items() if key in known}
        for required in ("id", "repo"):
            if not payload.get(required):
                raise ValueError(f"task is missing '{required}': {data}")
        if not payload.get("issue") and not payload.get("issue_file"):
            raise ValueError(f"task needs either 'issue' or 'issue_file': {data}")
        return cls(**payload)


@dataclass(slots=True)
class TaskOutcome:
    id: str
    fixed: bool
    stage: str
    stop_reason: str = ""
    steps: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    duration_s: float = 0.0
    touched_files: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    detail: str = ""
    run_dir: str = ""
    base_commit: str = ""
    #: The ceilings that were actually in force for this row. A batch is often an
    #: experiment *on* the budget, and a task file that quietly lost its calibrated
    #: numbers produces a run that looks like that experiment and is not - the numbers
    #: have to travel with the result, not only with the input.
    budget: dict[str, float] = field(default_factory=dict)


def run_shell(
    command: str, cwd: Path, timeout: float = 600.0, env: dict[str, str] | None = None
) -> tuple[int, str]:
    merged = os.environ.copy()
    # PYTHONDONTWRITEBYTECODE is not cosmetic. Python reuses a .pyc whenever the source
    # keeps the same mtime second *and* the same file size, so a one-token fix such as
    # "a - b" -> "a + b" is invisible to the very next run: the pre-fix bytecode gets
    # executed instead and a correct patch is scored as a failure. The same aliasing can
    # hide a regression behind a stale .pyc and score a broken patch as a pass. Never let
    # a verification run write bytecode.
    merged.update(
        {
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "NO_COLOR": "1",
        }
    )
    merged.update(env or {})
    result = run_bounded(command, cwd=cwd, env=merged, timeout=timeout)
    text = result.output
    if result.timed_out:
        text = f"timeout after {timeout}s\n{text}"
    return result.exit_code, text[-4_000:]


def load_tasks(path: Path) -> list[Task]:
    tasks: list[Task] = []
    path = Path(path)
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("//"):
            task = Task.from_dict(json.loads(line))
            if task.issue_file and not task.issue.strip():
                task.issue = (path.parent / task.issue_file).read_text(encoding="utf-8")
            if task.gold_patch:
                task.gold_patch = str((path.parent / task.gold_patch).resolve())
            tasks.append(task)
    return tasks


def _diff_stat(repo: Path) -> str:
    """What the working tree actually looks like after a patch was applied.

    'git apply returned 0 but nothing changed' is a real failure mode (wrong checkout,
    patch already applied, a stray .gitignore), and without this the symptom is just
    'the reference fix did not help', which points at the wrong thing.
    """
    proc = subprocess.run(
        ["git", "-C", str(repo), "diff", "--stat", "--no-color"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60.0,
    )
    return (proc.stdout or "").strip() or "(no difference in the working tree)"


#: Provenance markers that must never reach the prompt of any task.
PROVENANCE_MARKERS = ("来源：", "提交者：", "已合并修复", "upstream fix", "fixed by")


def issue_leak(task: Task) -> str | None:
    """Gate 0: refuse a task whose prompt already contains the answer.

    A fix sha, a PR number or the upstream commit subject turns "diagnose this bug" into
    "recall this diff", and the only visible symptom is a pass that costs almost nothing.
    This runs before any clone, so it is free.
    """
    haystack = task.issue.lower()
    terms = (*PROVENANCE_MARKERS, *task.leak_terms)
    found = [term for term in terms if term.lower() in haystack]
    if not found:
        return None
    return "issue text leaks provenance: " + ", ".join(repr(term) for term in found)


def preflight_model(model: str) -> str | None:
    """One cheap call before the batch: prove the key and the model name actually work.

    The loop turns any provider error into a stopped run with no patch, so an unusable
    model reaches the results file as a row of ``empty_patch`` - twenty model failures that
    never happened. A mistyped model name and a missing key are the two most common ways to
    lose a batch this way, and both are free to detect up front.
    """
    from langchain_core.messages import HumanMessage

    from repo_agent.llm import LiteLLMClient

    try:
        LiteLLMClient(model, max_tokens=16, timeout=60.0).complete(
            [HumanMessage(content="Reply with the single word: ok")]
        )
    except Exception as exc:  # noqa: BLE001 - any transport or auth error is the answer
        return f"{type(exc).__name__}: {exc}"
    return None


def check_gold(task: Task, verify: Path) -> tuple[bool, str]:
    """Apply the reference fix and confirm it really does turn the task green.

    Without this the harness will happily score a task that no patch can solve: a fixture
    that never received the new test, a node id that does not exist, an environment
    variable that never reaches the test process. All three look exactly like a model
    failure in the results, which is the expensive way to find out.
    """
    patch = Path(task.gold_patch).read_text(encoding="utf-8")
    code, out = _apply(patch, verify)
    if code != 0:
        return False, f"the reference fix does not apply to the fixture:\n{out.strip()}"
    stat = _diff_stat(verify)
    for command in task.fail_to_pass:
        code, out = run_shell(command, verify, env=task.env)
        if code != 0:
            return False, (
                f"the reference fix leaves '{command}' failing.\n"
                f"Working tree after applying it:\n{stat}\n{out.strip()}"
            )
    for command in task.pass_to_pass:
        code, out = run_shell(command, verify, env=task.env)
        if code != 0:
            return False, (
                f"the reference fix regresses '{command}'.\n"
                f"Working tree after applying it:\n{stat}\n{out.strip()}"
            )
    return True, (
        f"gold patch turns {len(task.fail_to_pass)} command(s) green and "
        f"{len(task.pass_to_pass)} regression command(s) hold"
    )


def run_one(
    task: Task,
    work_root: Path,
    model: str | None,
    sandbox: str | None,
    pre_check_only: bool = False,
) -> TaskOutcome:
    started = time.time()
    leak = issue_leak(task)
    if leak:
        return TaskOutcome(task.id, False, "issue_leak", detail=leak)
    repo_path = Path(task.repo)
    if task.prepare and not repo_path.exists():
        code, out = run_shell(task.prepare.replace("{repo}", str(repo_path)), Path.cwd())
        if code != 0:
            return TaskOutcome(task.id, False, "prepare", detail=out)
    task_root = work_root / task.id
    workspace = prepare_workspace(task.repo, task_root / "workspace", task.base_commit)
    verify = prepare_workspace(task.repo, task_root / "verify", task.base_commit)
    base_commit = head_commit(verify)

    # Gate 1: the task must actually be broken before we start.
    for command in task.fail_to_pass:
        code, out = run_shell(command, verify, env=task.env)
        if code == 0:
            return TaskOutcome(
                task.id, False, "pre_check", detail=f"'{command}' already passes before the fix"
            )
    if pre_check_only:
        detail = f"{len(task.fail_to_pass)} failing test command(s) confirmed"
        if task.gold_patch:
            # Gate 1b: somebody must be able to solve it, so the task is worth scoring.
            solved, gold_detail = check_gold(task, verify)
            if not solved:
                return TaskOutcome(
                    task.id, False, "gold_check", base_commit=base_commit, detail=gold_detail
                )
            detail = f"{detail}; {gold_detail}"
        return TaskOutcome(task.id, False, "valid", base_commit=base_commit, detail=detail)

    cfg = RunConfig(
        task=task.issue,
        workspace=workspace,
        test_command=task.test_command,
        model=model or task.model or "gpt-4o-mini",
        sandbox=sandbox or "local",
        run_dir=task_root / "run",
        env=dict(task.env),
    )
    if task.max_steps or task.max_tokens:
        cfg.budget = Budget(
            max_steps=task.max_steps or cfg.budget.max_steps,
            max_tokens=task.max_tokens or cfg.budget.max_tokens,
        )
    if task.protected_globs:
        cfg.protected_globs = tuple(task.protected_globs)
    if task.editable_globs:
        cfg.editable_globs = tuple(task.editable_globs)

    result = run_agent(cfg, reference_repo=verify)
    outcome = TaskOutcome(
        id=task.id,
        fixed=False,
        stage="agent",
        stop_reason=result.stop_reason,
        steps=result.steps,
        tokens=result.tokens,
        cost_usd=result.cost_usd,
        duration_s=round(time.time() - started, 2),
        touched_files=result.touched_files,
        violations=result.contract_violations,
        detail=result.error,
        run_dir=result.run_dir,
        base_commit=base_commit,
        budget={
            "max_steps": cfg.budget.max_steps,
            "max_tokens": cfg.budget.max_tokens,
        },
    )
    if result.stop_reason == "llm_error" and result.tokens == 0:
        # The model was never reached, so there is nothing to score. Reporting this as
        # empty_patch ("the agent changed nothing") would blame the wrong thing; a wrong
        # key or a rate limit belongs in the same bucket as a failed clone.
        outcome.stage = "llm_error"
        outcome.detail = result.error or "the model call failed before any tokens were billed"
        return outcome
    if not result.patch.strip():
        outcome.stage = "empty_patch"
        return outcome
    if result.contract_violations or not result.applies_cleanly:
        outcome.stage = "contract"
        outcome.detail = result.patch_path
        return outcome

    # Gate 2: apply the patch to an untouched checkout and run the real tests.
    apply_code, apply_out = _apply(result.patch, verify)
    if apply_code != 0:
        outcome.stage = "apply"
        outcome.detail = apply_out
        return outcome
    for command in task.fail_to_pass:
        code, out = run_shell(command, verify, env=task.env)
        if code != 0:
            outcome.stage = "fail_to_pass"
            outcome.detail = f"{command}\n{out}"
            return outcome
    for command in task.pass_to_pass:
        code, out = run_shell(command, verify, env=task.env)
        if code != 0:
            outcome.stage = "pass_to_pass"
            outcome.detail = f"regression: {command}\n{out}"
            return outcome
    outcome.fixed = True
    outcome.stage = "ok"
    outcome.duration_s = round(time.time() - started, 2)
    return outcome


def _apply(patch: str, repo: Path) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", "-"],
        cwd=str(repo),
        input=patch.encode("utf-8"),
        capture_output=True,
        timeout=120.0,
    )
    return proc.returncode, (proc.stdout + proc.stderr).decode("utf-8", errors="replace")


def keep_artifacts(outcome: TaskOutcome, out_dir: Path) -> None:
    """The work root is temporary, but the run's evidence must outlive it.

    Without this the harness deletes trace.jsonl / NOTES.md / patch.diff at the end of
    every task, which makes failures impossible to diagnose after the fact.
    """
    if not outcome.run_dir:
        return
    source = Path(outcome.run_dir)
    if not source.is_dir():
        return
    target = out_dir / "artifacts" / outcome.id
    shutil.copytree(source, target, dirs_exist_ok=True)
    outcome.run_dir = str(target)


def report(outcomes: list[TaskOutcome], out_dir: Path) -> dict:
    fixed = [o for o in outcomes if o.fixed]
    total = len(outcomes)
    summary = {
        "tasks": total,
        "fixed": len(fixed),
        "pass@1": round(len(fixed) / total, 4) if total else 0.0,
        "avg_steps": round(sum(o.steps for o in outcomes) / total, 2) if total else 0.0,
        "avg_tokens": round(sum(o.tokens for o in outcomes) / total, 1) if total else 0.0,
        "avg_cost_usd": round(sum(o.cost_usd for o in outcomes) / total, 6) if total else 0.0,
        "avg_duration_s": round(sum(o.duration_s for o in outcomes) / total, 1) if total else 0.0,
        "stages": {},
    }
    for outcome in outcomes:
        summary["stages"][outcome.stage] = summary["stages"].get(outcome.stage, 0) + 1
    rows = [
        f"{o.id:<16} {'PASS' if o.fixed else 'fail':<5} {o.stage:<14} "
        f"steps={o.steps:<3} tokens={o.tokens:<7} ${o.cost_usd:<9.4f} {o.duration_s}s"
        for o in outcomes
    ]
    print("\n".join(rows) if rows else "(no tasks)")
    print("-" * 72)
    print(
        f"pass@1 {summary['pass@1']:.2%}  ({summary['fixed']}/{total})   "
        f"avg steps {summary['avg_steps']}   avg tokens {summary['avg_tokens']}   "
        f"avg ${summary['avg_cost_usd']:.4f}   avg {summary['avg_duration_s']}s"
    )
    print(f"stages: {summary['stages']}")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.jsonl").write_text(
        "\n".join(json.dumps(asdict(o), ensure_ascii=False) for o in outcomes),
        encoding="utf-8",
    )
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"results: {out_dir / 'results.jsonl'}")
    return summary


def guarded_run_one(
    task: Task,
    work_root: Path,
    model: str | None,
    sandbox: str | None,
    check_only: bool,
) -> TaskOutcome:
    """Run one task, turning an infrastructure failure into a scoreable outcome.

    A clone that dies must not discard the other nineteen results, and it must not look like
    the model failed: it gets its own stage, ``harness_error``, so pass@1 stays honest and the
    error stays visible (the exit code is already non-zero whenever anything did not pass).
    """
    try:
        return run_one(task, work_root, model, sandbox, pre_check_only=check_only)
    except Exception as exc:  # noqa: BLE001 - the point is to survive anything
        return TaskOutcome(
            task.id,
            False,
            "harness_error",
            detail=f"{type(exc).__name__}: {exc}",
        )


def run_parallel(
    tasks: list[Task],
    work_root: Path,
    model: str | None,
    sandbox: str | None,
    check_only: bool,
    out_dir: Path,
    jobs: int,
) -> list[TaskOutcome]:
    """Run the batch on ``jobs`` threads and return outcomes in task-file order.

    Each task owns its own checkout, run directory and artifacts, so the only shared state is
    the console and the artifacts copy; both are serialised. Results are re-ordered at the end
    because the log and the baseline table are read as an ordered list, and a batch that
    finishes out of order must not shuffle them.
    """
    lock = threading.Lock()
    finished: dict[str, TaskOutcome] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        pending = {
            pool.submit(guarded_run_one, task, work_root, model, sandbox, check_only): task
            for task in tasks
        }
        with lock:
            print("-> " + ", ".join(task.id for task in tasks))
        for future in concurrent.futures.as_completed(pending):
            outcome = future.result()
            finished[outcome.id] = outcome
            if not check_only:
                keep_artifacts(outcome, out_dir)
            with lock:
                flag = "PASS" if outcome.fixed else "fail"
                print(
                    f"   done {outcome.id:<24} {flag}  {outcome.stage:<14} "
                    f"steps={outcome.steps:<3} {outcome.duration_s}s"
                )
    return [finished[task.id] for task in tasks]


def run_eval(
    tasks_path: Path,
    out_dir: Path | None = None,
    model: str | None = None,
    sandbox: str | None = None,
    limit: int | None = None,
    check_only: bool = False,
    only: list[str] | None = None,
    jobs: int = 1,
) -> int:
    tasks = load_tasks(tasks_path)
    known = {task.id for task in tasks}
    if only:
        wanted = {name.strip() for name in only if name.strip()}
        missing = sorted(wanted - known)
        if missing:
            print(f"unknown task id(s): {', '.join(missing)}", file=sys.stderr)
            print(f"known: {', '.join(sorted(known))}", file=sys.stderr)
            return 2
        tasks = [task for task in tasks if task.id in wanted]
    if limit:
        tasks = tasks[:limit]
    if model and not check_only:
        failure = preflight_model(model)
        if failure:
            print(f"model '{model}' is not usable: {failure}", file=sys.stderr)
            print(
                "refusing to start: every task would be recorded as an empty patch. "
                "Check DEEPSEEK_API_KEY and the model name (deepseek/deepseek-chat).",
                file=sys.stderr,
            )
            return 2
    out_dir = out_dir or Path("eval-runs") / time.strftime("%Y%m%d-%H%M%S")
    work_root = Path(tempfile.mkdtemp(prefix="repo-agent-eval-"))
    print(f"tasks: {len(tasks)}/{len(known)}   jobs: {jobs}   work root: {work_root}")
    if jobs > 1:
        print(
            "note: latency and wall-clock numbers are only comparable between runs with the "
            "same --jobs; pass@1 and cost are not affected."
        )
    outcomes: list[TaskOutcome] = []
    try:
        if jobs <= 1:
            for task in tasks:
                print(f"-> {task.id}")
                outcome = guarded_run_one(task, work_root, model, sandbox, check_only)
                outcomes.append(outcome)
                if not check_only:
                    keep_artifacts(outcome, out_dir)
        else:
            outcomes = run_parallel(tasks, work_root, model, sandbox, check_only, out_dir, jobs)
    finally:
        shutil.rmtree(work_root, ignore_errors=True)
    if check_only:
        for outcome in outcomes:
            flag = "VALID  " if outcome.stage == "valid" else "INVALID"
            print(f"{flag} {outcome.id:<20} {outcome.detail}")
        valid = sum(1 for outcome in outcomes if outcome.stage == "valid")
        print(f"valid tasks: {valid}/{len(outcomes)} (no model was called)")
        return 0 if valid == len(outcomes) else 1
    summary = report(outcomes, out_dir)
    return 0 if summary["fixed"] == summary["tasks"] else 1


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="harness.run_eval", description=__doc__)
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--out", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--sandbox", default=None, choices=["local", "docker"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="run this many tasks at once (default 1 = serial). Wall-clock and latency "
        "numbers are only comparable between runs that used the same --jobs; pass@1 and cost "
        "are not affected. Serial stays the default because a baseline should be reproducible",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=None,
        metavar="TASK_ID",
        help="run just these task ids (repeatable). Cheaper than guessing: after changing the "
        "loop detector or a budget, prove the change is actually exercised before paying for "
        "the whole set",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="only verify that each task is broken before the fix; never calls a model",
    )
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    return run_eval(
        Path(args.tasks),
        Path(args.out) if args.out else None,
        args.model,
        args.sandbox,
        args.limit,
        args.check_only,
        args.only,
        args.jobs,
    )


if __name__ == "__main__":
    raise SystemExit(main())
