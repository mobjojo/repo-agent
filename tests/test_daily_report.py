"""The log writer edits a real file, so the editing rules get their own tests.

Background: the 2026-09-20 log was destroyed by a hand-written slice replacement (a 14 KB
file became 4.3 MB). A tool that rewrites the log must therefore fail loudly on an unexpected
shape and be idempotent on the expected one.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.daily_report import (
    END,
    START,
    ReportError,
    format_row,
    summarize,
    upsert_row,
)


def make_batch(root: Path, rows: list[dict], model: str = "deepseek/deepseek-chat") -> Path:
    batch = root / "batch-x"
    (batch / "artifacts" / "toy-001").mkdir(parents=True)
    (batch / "artifacts" / "toy-001" / "trace.jsonl").write_text(
        json.dumps({"kind": "run_start", "model": model}) + "\n", encoding="utf-8"
    )
    (batch / "results.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows), encoding="utf-8"
    )
    return batch


def row(task: str, fixed: bool, stage: str) -> dict:
    return {
        "id": task,
        "fixed": fixed,
        "stage": stage,
        "stop_reason": "submitted" if fixed else "budget:steps",
        "steps": 8,
        "tokens": 40000,
        "cost_usd": 0.004,
        "duration_s": 20.0,
    }


class SummarizeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_counts_and_averages(self) -> None:
        batch = make_batch(self.root, [row("a", True, "ok"), row("b", False, "empty_patch")])
        summary = summarize(batch)
        self.assertEqual(summary["tasks"], 2)
        self.assertEqual(summary["fixed"], 1)
        self.assertEqual(summary["pass_at_1"], 0.5)
        self.assertEqual(summary["avg_steps"], 8)
        self.assertEqual(summary["wall_s"], 40.0)
        self.assertEqual(summary["stages"], {"ok": 1, "empty_patch": 1})
        self.assertEqual(summary["stop_reasons"], {"submitted": 1, "budget:steps": 1})

    def test_missing_results_is_an_error_not_a_zero(self) -> None:
        # A silent 0/0 would look like a catastrophic regression in the log.
        with self.assertRaises(ReportError):
            summarize(self.root / "does-not-exist")

    def test_the_model_column_comes_from_the_trace(self) -> None:
        # Two models in one log is how a baseline becomes unreadable: the row must say which.
        batch = make_batch(self.root, [row("a", True, "ok")], model="deepseek/deepseek-flash")
        self.assertEqual(summarize(batch)["model"], "deepseek/deepseek-flash")

    def test_a_batch_without_traces_says_so_instead_of_guessing(self) -> None:
        batch = make_batch(self.root, [row("a", True, "ok")])
        (batch / "artifacts" / "toy-001" / "trace.jsonl").unlink()
        self.assertEqual(summarize(batch)["model"], "?")

    def test_row_matches_the_table_columns(self) -> None:
        batch = make_batch(self.root, [row("a", True, "ok")])
        text = format_row("batch-x", summarize(batch), "note")
        self.assertEqual(text.count("|"), 12)
        self.assertIn("| `batch-x` | `deepseek/deepseek-chat` | 1 |", text)
        self.assertIn("**1/1 (100%)**", text)
        self.assertTrue(text.endswith("| note |"))


class UpsertTests(unittest.TestCase):
    def log(self, *rows: str) -> list[str]:
        return ["# log", "", START, "| 批次 | 任务数 |", "| --- | --- |", *rows, END, "", "tail"]

    def test_appends_a_new_batch(self) -> None:
        out = upsert_row(self.log("| `a` | 1 |"), "b", "| `b` | 2 |")
        self.assertEqual(out.count("| `b` | 2 |"), 1)
        self.assertEqual(out[-2:], ["", "tail"])

    def test_replaces_in_place_and_stays_idempotent(self) -> None:
        lines = self.log("| `a` | 1 |", "| `b` | 2 |", "| `c` | 3 |")
        once = upsert_row(lines, "b", "| `b` | 22 |")
        twice = upsert_row(once, "b", "| `b` | 22 |")
        self.assertEqual(once, twice)
        self.assertEqual(once.index("| `b` | 22 |"), lines.index("| `b` | 2 |"))
        self.assertEqual(len(once), len(lines))

    def test_duplicate_rows_collapse_to_one(self) -> None:
        lines = self.log("| `a` | 1 |", "| `a` | 1 |")
        out = upsert_row(lines, "a", "| `a` | 9 |")
        self.assertEqual([line for line in out if line.startswith("| `a` |")], ["| `a` | 9 |"])

    def test_a_header_is_added_to_an_empty_table(self) -> None:
        out = upsert_row(["# log", START, END], "a", "| `a` | 1 |")
        self.assertTrue(any(line.startswith("| 批次 |") for line in out))
        self.assertIn(START, out)
        self.assertIn(END, out)

    def test_a_stale_header_is_repaired(self) -> None:
        # Columns get added over time; a header that disagrees with its rows breaks the
        # rendered table, and repairing it by hand is how the log got destroyed once already.
        stale = ["# log", START, "| 批次 | 任务数 |", "| --- | --- |", "| `a` | 1 |", END]
        out = upsert_row(stale, "b", "| `b` | 2 |")
        self.assertEqual(out[2], "| 批次 | 模型 | 任务数 | pass@1 | 平均步数 | 平均 token | 平均费用 | 平均延迟 | 整批墙钟 | 合计费用 | 说明 |")
        self.assertEqual(out[3], "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")

    def test_a_current_header_is_left_alone(self) -> None:
        lines = ["# log", START, *[], END]
        seeded = upsert_row(lines, "a", "| `a` | 1 |")
        again = upsert_row(seeded, "b", "| `b` | 2 |")
        self.assertEqual(seeded[2], again[2])
        self.assertEqual(seeded[3], again[3])

    def test_missing_markers_fail_loudly(self) -> None:
        with self.assertRaises(ReportError):
            upsert_row(["# log", "| `a` | 1 |"], "a", "| `a` | 2 |")

    def test_reversed_markers_fail_loudly(self) -> None:
        with self.assertRaises(ReportError):
            upsert_row([END, "| `a` | 1 |", START], "a", "| `a` | 2 |")

    def test_text_outside_the_markers_is_untouched(self) -> None:
        lines = ["# 工作日志", "", START, END, "", "## 2026-09-20", "叙述内容"]
        out = upsert_row(lines, "a", "| `a` | 1 |")
        self.assertEqual(out[:2], lines[:2])
        self.assertEqual(out[-2:], ["## 2026-09-20", "叙述内容"])


if __name__ == "__main__":
    unittest.main()
