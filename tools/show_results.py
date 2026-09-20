"""打印某个批次的逐任务结果与汇总（只读）。"""

from __future__ import annotations

import json
import pathlib
import sys


def main(batch: str) -> int:
    path = pathlib.Path(f"eval-runs/{batch}/results.jsonl")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in rows:
        flag = "PASS" if row["fixed"] else "fail"
        print(
            f'{row["id"]:<26} {flag:<5} {row["stage"]:<14} steps={row["steps"]:<3} '
            f'tokens={row["tokens"]:<7} ${row["cost_usd"]:<8.4f} {row["duration_s"]}s'
        )
    fixed = sum(1 for row in rows if row["fixed"])
    total = len(rows)
    stages: dict[str, int] = {}
    for row in rows:
        stages[row["stage"]] = stages.get(row["stage"], 0) + 1
    print("-" * 78)
    print(f"pass@1 {fixed}/{total} = {fixed / total:.2%}")
    print(
        f"avg steps {sum(r['steps'] for r in rows) / total:.2f}   "
        f"avg tokens {sum(r['tokens'] for r in rows) / total:.0f}   "
        f"avg ${sum(r['cost_usd'] for r in rows) / total:.4f}   "
        f"avg {sum(r['duration_s'] for r in rows) / total:.1f}s   "
        f"total ${sum(r['cost_usd'] for r in rows):.4f}"
    )
    print("stages:", stages)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "m3-golden-20"))
