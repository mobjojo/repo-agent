"""Command line entry points: one task, or a whole evaluation set."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from .config import Budget, RunConfig
from .runner import RunResult, run_agent
from .task import prepare_workspace


def _force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _print_result(result: RunResult) -> None:
    print("")
    print("=" * 72)
    print(f"stop_reason : {result.stop_reason}")
    print(f"valid patch : {result.valid}")
    print(f"steps       : {result.steps}   tokens: {result.tokens}   cost: ${result.cost_usd:.4f}")
    print(f"duration    : {result.duration_s}s")
    if result.touched_files:
        print(f"files       : {', '.join(result.touched_files)}")
    if result.contract_violations:
        print("violations  :")
        for item in result.contract_violations:
            print(f"  - {item}")
    if result.error:
        print(f"error       : {result.error}")
    print(f"patch       : {result.patch_path}")
    print(f"trace       : {result.trace_path}")
    print(f"notes       : {result.notes_path}")
    print("=" * 72)


def cmd_run(args: argparse.Namespace) -> int:
    work_root = (
        Path(args.workdir).resolve()
        if args.workdir
        else Path(tempfile.mkdtemp(prefix="repo-agent-"))
    )
    work_root.mkdir(parents=True, exist_ok=True)
    workspace = prepare_workspace(args.repo, work_root / "workspace", args.commit)
    reference = None
    if not args.no_reference_check:
        reference = prepare_workspace(args.repo, work_root / "reference", args.commit)
    if args.issue:
        task = args.issue
    elif args.issue_file:
        task = Path(args.issue_file).read_text(encoding="utf-8")
    else:
        task = ""
    if not task.strip():
        print("error: pass --issue or --issue-file", file=sys.stderr)
        return 2
    cfg = RunConfig(
        task=task,
        workspace=workspace,
        test_command=args.test_command,
        model=args.model,
        sandbox=args.sandbox,
        image=args.image,
        budget=Budget(
            max_steps=args.max_steps,
            max_tokens=args.max_tokens,
            max_cost_usd=args.max_cost,
            max_wall_seconds=args.max_wall,
        ),
        run_dir=Path(args.run_dir) if args.run_dir else None,
    )
    if args.protected:
        cfg.protected_globs = tuple(args.protected)
    if args.editable:
        cfg.editable_globs = tuple(args.editable)
    print(f"workspace: {workspace}")
    print(f"model    : {cfg.model}   sandbox: {cfg.sandbox}")
    result = run_agent(cfg, reference_repo=reference)
    _print_result(result)
    return 0 if result.valid else 1


def cmd_eval(args: argparse.Namespace) -> int:
    from harness.run_eval import run_eval

    return run_eval(
        tasks_path=Path(args.tasks),
        out_dir=Path(args.out) if args.out else None,
        model=args.model,
        sandbox=args.sandbox,
        limit=args.limit,
        check_only=args.check_only,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="repo_agent", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="fix one issue in one repository")
    run.add_argument("--repo", required=True, help="local path or clone URL of the repository")
    run.add_argument("--commit", default=None, help="base commit to check out (default: HEAD)")
    run.add_argument("--issue", default=None, help="bug report text")
    run.add_argument("--issue-file", default=None, help="file containing the bug report")
    run.add_argument("--test-command", default="python -m unittest discover -s tests -t . -v")
    run.add_argument("--model", default="gpt-4o-mini")
    run.add_argument("--sandbox", default="local", choices=["local", "docker"])
    run.add_argument("--image", default="python:3.11-slim")
    run.add_argument("--max-steps", type=int, default=20)
    run.add_argument("--max-tokens", type=int, default=200_000)
    run.add_argument("--max-cost", type=float, default=2.0)
    run.add_argument("--max-wall", type=float, default=900.0)
    run.add_argument("--protected", nargs="*", default=None)
    run.add_argument("--editable", nargs="*", default=None)
    run.add_argument("--workdir", default=None, help="keep clones here instead of a temp dir")
    run.add_argument("--run-dir", default=None, help="where trace/patch/notes are written")
    run.add_argument("--no-reference-check", action="store_true")
    run.set_defaults(func=cmd_run)

    evaluate = sub.add_parser("eval", help="run a task set and report pass@1 / cost / latency")
    evaluate.add_argument("--tasks", required=True, help="JSONL task file")
    evaluate.add_argument("--out", default=None, help="output directory for results")
    evaluate.add_argument("--model", default=None, help="override the model for every task")
    evaluate.add_argument("--sandbox", default=None, choices=["local", "docker"])
    evaluate.add_argument("--limit", type=int, default=None, help="only the first N tasks")
    evaluate.add_argument(
        "--check-only",
        action="store_true",
        help="verify task validity (a broken test before the fix) without calling a model",
    )
    evaluate.set_defaults(func=cmd_eval)
    return parser


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    args = build_parser().parse_args(argv)
    return int(args.func(args))
