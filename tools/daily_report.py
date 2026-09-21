"""Turn a finished eval batch into a log entry, without touching the log by hand.

Why this exists: appending numbers to ``工作日志.md`` by hand is where the mistakes come
from - on 2026-09-20 a hand-written slice replacement turned a 14 KB log into 4.3 MB. The
numbers here are computed from ``results.jsonl``, and the edit is an upsert between two
literal markers, so running it twice is harmless and running it on the wrong file fails
loudly instead of quietly corrupting it.

    python tools/daily_report.py m3-golden-20-w5 --note "熔断 3 警告 / 5 终止；空结果"

The batch id is the key: re-running for the same batch replaces its row in place.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

START = "<!-- batch-table:start -->"
END = "<!-- batch-table:end -->"
HEADER = (
    "| 批次 | 模型 | 任务数 | pass@1 | 平均步数 | 平均 token | 平均费用 | 平均延迟 | 整批墙钟 | 合计费用 | 说明 |",
    "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
)


class ReportError(Exception):
    """Raised when the log is not in a shape we are willing to edit."""


def _counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def summarize(batch_dir: Path) -> dict[str, object]:
    results = batch_dir / "results.jsonl"
    if not results.is_file():
        raise ReportError(f"{results} not found - was the batch finished?")
    rows = [
        json.loads(line)
        for line in results.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not rows:
        raise ReportError(f"{results} is empty")
    total = len(rows)
    fixed = sum(1 for row in rows if row["fixed"])
    wall = wall_seconds(batch_dir)
    durations = sum(row["duration_s"] for row in rows)
    stages: dict[str, int] = {}
    for row in rows:
        stages[row["stage"]] = stages.get(row["stage"], 0) + 1
    return {
        "model": batch_model(batch_dir),
        "tasks": total,
        "fixed": fixed,
        "pass_at_1": fixed / total,
        "stages": stages,
        "avg_steps": sum(row["steps"] for row in rows) / total,
        "avg_tokens": sum(row["tokens"] for row in rows) / total,
        "avg_cost": sum(row["cost_usd"] for row in rows) / total,
        "avg_duration": sum(row["duration_s"] for row in rows) / total,
        # Wall clock is the number the concurrency work is judged by, and it is *not* the
        # sum of per-task durations: at --jobs 4 that sum is four times too large.
        "wall_s": wall if wall is not None else durations,
        "wall_is_measured": wall is not None,
        "cost_usd": sum(row["cost_usd"] for row in rows),
        "stop_reasons": _counts(row.get("stop_reason", "") for row in rows),
    }


def wall_seconds(batch_dir: Path) -> float | None:
    """First task start to last task end, straight off the traces.

    Returns None when any task's trace is missing its ``run_end`` (an interrupted batch),
    because a half-finished batch has no wall clock - the caller falls back to the sum and
    marks the number as approximate.
    """
    traces = sorted((batch_dir / "artifacts").glob("*/trace.jsonl"))
    if not traces:
        return None
    starts: list[float] = []
    ends: list[float] = []
    for trace in traces:
        trace_start = trace_end = None
        for line in trace.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            stamp = event.get("ts")
            if not isinstance(stamp, (int, float)):
                continue
            if event.get("kind") == "run_start" and trace_start is None:
                trace_start = float(stamp)
            elif event.get("kind") == "run_end":
                trace_end = float(stamp)
        if trace_start is None or trace_end is None:
            return None
        starts.append(trace_start)
        ends.append(trace_end)
    return max(ends) - min(starts)


def existing_note(lines: list[str], batch: str) -> str:
    """The note already written for this batch, so a refresh does not need it retyped."""
    key = f"| `{batch}` |"
    for line in lines:
        if line.startswith(key) and line.endswith("|"):
            cells = line.split(" | ")
            if len(cells) >= 2:
                return cells[-1].rstrip(" |").strip()
    return ""


def batch_model(batch_dir: Path) -> str:
    """The model actually used, read from the traces.

    A batch's score is only meaningful next to the model that produced it, and the harness
    writes that string once per run into trace.jsonl, so the table reads it instead of
    trusting whoever typed the batch name.
    """
    for trace in sorted((batch_dir / "artifacts").glob("*/trace.jsonl")):
        for line in trace.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("kind") == "run_start" and event.get("model"):
                return str(event["model"])
    return "?"


def format_row(batch: str, summary: dict[str, object], note: str) -> str:
    fixed, tasks = summary["fixed"], summary["tasks"]
    wall = f"{summary['wall_s']:.1f}s" if summary["wall_is_measured"] else f"~{summary['wall_s']:.1f}s"
    return (
        f"| `{batch}` | `{summary['model']}` | {tasks} | **{fixed}/{tasks} ({summary['pass_at_1']:.0%})** "
        f"| {summary['avg_steps']:.2f} | {summary['avg_tokens']:,.0f} "
        f"| ${summary['avg_cost']:.4f} | {summary['avg_duration']:.1f}s "
        f"| {wall} | ${summary['cost_usd']:.4f} | {note} |"
    )


def upsert_row(lines: list[str], batch: str, row: str) -> list[str]:
    """Insert or replace this batch's row inside the marked table. Idempotent."""
    try:
        start = lines.index(START)
        end = lines.index(END)
    except ValueError as exc:
        raise ReportError(f"log is missing the {START} / {END} markers") from exc
    if end < start:
        raise ReportError(f"{END} appears before {START}")
    body = lines[start + 1 : end]
    header_at = next(
        (index for index, line in enumerate(body) if line.startswith("| 批次 |")), None
    )
    if header_at is None:
        body = list(HEADER) + body
    else:
        # A table whose header predates a new column renders as garbage in every markdown
        # viewer, and hand-editing it is exactly the kind of edit that goes wrong. The columns
        # are ours, so the header is ours to repair.
        if body[header_at] != HEADER[0]:
            body[header_at] = HEADER[0]
        if header_at + 1 < len(body) and body[header_at + 1].startswith("| ---"):
            body[header_at + 1] = HEADER[1]
    key = f"| `{batch}` |"
    replaced: list[str] = []
    seen = False
    for line in body:
        if line.startswith(key):
            if not seen:
                replaced.append(row)
                seen = True
            continue
        replaced.append(line)
    if not seen:
        replaced.append(row)
    return lines[: start + 1] + replaced + lines[end:]


def stage_line(summary: dict[str, object]) -> str:
    stages = ", ".join(f"{name} {count}" for name, count in sorted(summary["stages"].items()))
    stops = ", ".join(f"{name} {count}" for name, count in sorted(summary["stop_reasons"].items()))
    return f"阶段：{stages}；终止原因：{stops}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools.daily_report", description=__doc__)
    parser.add_argument("batch", help="batch name under eval-runs/")
    parser.add_argument("--runs", default="eval-runs", help="directory holding batches")
    parser.add_argument("--log", default="工作日志.md")
    parser.add_argument(
        "--note",
        default="",
        help="free-text note for the last column; empty keeps the note already in the log",
    )
    parser.add_argument("--docx", action="store_true", help="re-render the .docx next to the log")
    parser.add_argument("--outputs", default=None, help="copy log + docx here, dated")
    parser.add_argument("--date", default=None, help="date prefix for --outputs (default: today)")
    parser.add_argument(
        "--print-only", action="store_true", help="show the row without touching the log"
    )
    args = parser.parse_args(argv)

    summary = summarize(Path(args.runs) / args.batch)
    log = Path(args.log)
    lines = log.read_text(encoding="utf-8").splitlines() if log.is_file() else []
    note = args.note or existing_note(lines, args.batch)
    row = format_row(args.batch, summary, note)
    print(row)
    print(stage_line(summary))
    if args.print_only:
        return 0

    body = "\n".join(upsert_row(lines, args.batch, row)) + "\n"
    log.write_text(body, encoding="utf-8", newline="\n")
    print(f"updated {log}")

    if args.docx or args.outputs:
        subprocess.run(
            ["python", "tools/md_to_docx.py", str(log), str(log.with_suffix(".docx"))],
            check=True,
        )
    if args.outputs:
        date = args.date or time.strftime("%Y-%m-%d")
        target = Path(args.outputs)
        target.mkdir(parents=True, exist_ok=True)
        for suffix in (".md", ".docx"):
            source = log.with_suffix(suffix)
            if source.is_file():
                shutil.copyfile(source, target / f"{date}-{source.name}")
                print(f"copied {source.name} -> {target}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReportError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
