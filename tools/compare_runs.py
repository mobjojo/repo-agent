"""并排比较两个批次的逐任务结果，并统计翻转条数（重复跑波动）。"""

from __future__ import annotations

import json
import pathlib
import sys


def load(batch: str) -> dict[str, dict]:
    path = pathlib.Path(f"eval-runs/{batch}/results.jsonl")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {row["id"]: row for row in rows}


def main(a: str, b: str) -> int:
    left, right = load(a), load(b)
    flips = 0
    for tid in left:
        l, r = left[tid], right.get(tid)
        if r is None:
            print(f"{tid:<26} (missing in {b})")
            continue
        mark = "" if l["fixed"] == r["fixed"] else "  <-- FLIP"
        if mark:
            flips += 1
        print(
            f'{tid:<26} {a}: {"PASS" if l["fixed"] else "fail":<5} ({l["stage"]:<13} {l["steps"]:>2} steps)   '
            f'{b}: {"PASS" if r["fixed"] else "fail":<5} ({r["stage"]:<13} {r["steps"]:>2} steps){mark}'
        )
    for name, rows in ((a, left), (b, right)):
        fixed = sum(1 for row in rows.values() if row["fixed"])
        total = len(rows)
        print(
            f'{name}: pass@1 {fixed}/{total} = {fixed / total:.2%}   '
            f'avg steps {sum(r["steps"] for r in rows.values()) / total:.2f}   '
            f'avg tokens {sum(r["tokens"] for r in rows.values()) / total:.0f}   '
            f'avg ${sum(r["cost_usd"] for r in rows.values()) / total:.4f}   '
            f'avg {sum(r["duration_s"] for r in rows.values()) / total:.1f}s   '
            f'total ${sum(r["cost_usd"] for r in rows.values()):.4f}'
        )
    print(f"翻转条数: {flips}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
