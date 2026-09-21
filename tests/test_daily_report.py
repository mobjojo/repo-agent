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
    existing_note,
    format_row,
    main,
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


def add_trace(batch: Path, task: str, start: float, end: float | None) -> None:
    events = [{"ts": start, "kind": "run_start", "model": "deepseek/deepseek-chat"}]
    if end is not None:
        events.append({"ts": end, "kind": "run_end"})
    target = batch / "artifacts" / task
    target.mkdir(parents=True, exist_ok=True)
    (target / "trace.jsonl").write_text(
        "\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8"
    )


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

    def test_wall_clock_is_measured_not_summed(self) -> None:
        # The sum of per-task durations is 4x the wall clock on a --jobs 4 batch, and wall
        # clock is the number the concurrency work is judged by. Two tasks overlapping in
        # time must not add up.
        batch = make_batch(self.root, [row("a", True, "ok"), row("b", True, "ok")])
        add_trace(batch, "toy-001", start=100.0, end=120.0)
        add_trace(batch, "waiting", start=110.0, end=130.0)
        summary = summarize(batch)
        self.assertEqual(summary["wall_s"], 30.0)
        self.assertTrue(summary["wall_is_measured"])
        self.assertIn("| 30.0s |", format_row("batch-x", summary, "note"))

    def test_an_interrupted_batch_falls_back_to_the_sum_and_says_so(self) -> None:
        # No run_end means the batch never finished, so there is no wall clock to report.
        batch = make_batch(self.root, [row("a", True, "ok"), row("b", True, "ok")])
        add_trace(batch, "toy-001", start=100.0, end=120.0)
        add_trace(batch, "waiting", start=110.0, end=None)
        summary = summarize(batch)
        self.assertEqual(summary["wall_s"], 40.0)
        self.assertFalse(summary["wall_is_measured"])
        self.assertIn("| ~40.0s |", format_row("batch-x", summary, "note"))

    def test_a_note_is_read_back_so_a_refresh_can_keep_it(self) -> None:
        # Refreshing a row (new numbers, same experiment) must not need the note retyped:
        # that is exactly how a table ends up with half-empty descriptions.
        lines = [START, "| `batch-x` | 1 | 说明文字 |", END]
        self.assertEqual(existing_note(lines, "batch-x"), "说明文字")
        self.assertEqual(existing_note(lines, "other"), "")
        log = self.root / "log.md"
        log.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        batch = make_batch(self.root, [row("a", True, "ok")])
        self.assertEqual(main(["batch-x", "--runs", str(self.root), "--log", str(log)]), 0)
        written = log.read_text(encoding="utf-8")
        self.assertNotIn("| `batch-x` | 1 | 说明文字 |", written)
        self.assertIn("说明文字 |", written)
        self.assertIn("**1/1 (100%)**", written)


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
