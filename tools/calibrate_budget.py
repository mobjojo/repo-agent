"""Derive each task's step/token ceiling from the runs we have actually observed.

Why this exists: a task whose ceiling sits at the model's typical step count turns every
run into a coin flip, and the resulting "variance" is a property of the harness, not of the
agent. Neither ceiling is interesting on its own - it only has to be high enough that the
score is about the model rather than about the budget.

Rule: 1.5x the hardest *successful* run, rounded up (steps to 5, tokens to 50k), with floors
of 20 steps / 200k tokens. A task that never succeeded has no success sample to calibrate
from; it falls back to the largest run ever seen for it, solved or not, so the ceiling stops
cutting it off exactly where it already dies.

    python tools/calibrate_budget.py                 # rewrite tasks/golden.jsonl
    python tools/calibrate_budget.py --dry-run       # print what would change
    python tools/calibrate_budget.py --markdown      # table for tasks/README.md

Only pass batches of the model you are calibrating for: steps and tokens are model-specific.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

RUNS = [
    "m3-golden-20",
    "m3-golden-20-r2",
    "m3-golden-20-t90",
    "m3-golden-20-s20",
    "m3-golden-20-w5",
    "m3-golden-20-guard",
    "m3-golden-20-j4b",
    "m3-click-c",
]
STEP_FLOOR, TOKEN_FLOOR = 20, 200_000
STEP_UNIT, TOKEN_UNIT = 5, 50_000
TASK_FILE = Path("tasks") / "golden.jsonl"


def round_up(value: float, unit: int) -> int:
    return int(math.ceil(value / unit) * unit)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", default=",".join(RUNS), help="batch names under eval-runs/")
    parser.add_argument("--task-file", type=Path, default=TASK_FILE)
    parser.add_argument("--dry-run", action="store_true", help="print, do not rewrite")
    parser.add_argument("--markdown", action="store_true", help="emit a README table")
    args = parser.parse_args(argv)

    stats: dict[str, dict[str, list[int]]] = defaultdict(
        lambda: {"solved_steps": [], "solved_tokens": [], "seen_steps": [], "seen_tokens": []}
    )
    for run in [name.strip() for name in args.runs.split(",") if name.strip()]:
        path = Path("eval-runs") / run / "results.jsonl"
        if not path.is_file():
            print(f"skip {run}: no results.jsonl")
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            entry = stats[row["id"]]
            entry["seen_steps"].append(row["steps"])
            entry["seen_tokens"].append(row["tokens"])
            if row["fixed"]:
                entry["solved_steps"].append(row["steps"])
                entry["solved_tokens"].append(row["tokens"])

    tasks = [
        json.loads(line)
        for line in args.task_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows: list[tuple[str, int, int, int, int]] = []
    for task in tasks:
        entry = stats[task["id"]]
        hardest_steps = max(entry["solved_steps"], default=max(entry["seen_steps"], default=0))
        hardest_tokens = max(
            entry["solved_tokens"], default=max(entry["seen_tokens"], default=0)
        )
        steps = max(STEP_FLOOR, round_up(hardest_steps * 1.5, STEP_UNIT))
        tokens = max(TOKEN_FLOOR, round_up(hardest_tokens * 1.5, TOKEN_UNIT))
        task["max_steps"] = steps
        task["max_tokens"] = tokens
        rows.append((task["id"], hardest_steps, steps, hardest_tokens, tokens))

    for task_id, hardest_steps, steps, hardest_tokens, tokens in rows:
        print(
            f"{task_id:<26} 成功上限 {hardest_steps:>3} 步 / {hardest_tokens:>8,} token"
            f"  ->  预算 {steps:>3} 步 / {tokens:>9,} token"
        )
    if args.markdown:
        print()
        print("| 任务 | 观测成功上限（步数 / token） | 预算（步数 / token） |")
        print("| --- | --- | --- |")
        for task_id, hardest_steps, steps, hardest_tokens, tokens in rows:
            print(
                f"| `{task_id}` | {hardest_steps} 步 / {hardest_tokens:,} | "
                f"**{steps} 步 / {tokens:,}** |"
            )
    if args.dry_run:
        print("\n--dry-run: 未写入")
        return 0
    args.task_file.write_text(
        "\n".join(json.dumps(task, ensure_ascii=False) for task in tasks) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"\n已写入 {args.task_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
