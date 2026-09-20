"""The evaluation harness decides pass@1, so its own plumbing must be verified end to end.

The model is replaced by a scripted trajectory, which keeps this test offline and exact.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from repo_agent.llm import ScriptedLLM
from repo_agent.runner import run_agent as real_run_agent
from tests.make_toy_repo import build_toy_repo
from tests.test_loop_e2e import fixing_script

import harness.run_eval as harness

FAIL_TO_PASS = ["python -m unittest tests.test_ops"]
PASS_TO_PASS = ['python -c "from calc.ops import mul; assert mul(2, 3) == 6"']
ENV_CHECK = [
    "python -c \"import os, sys; sys.exit(0 if os.environ.get('TASK_FLAG') == '1' else 3)\""
]


def scripted_run_agent(cfg, reference_repo=None, **kwargs):
    return real_run_agent(cfg, llm=ScriptedLLM(fixing_script()), reference_repo=reference_repo)


class HarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.repo = build_toy_repo(self.tmp / "toyrepo")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_tasks(
        self,
        name: str,
        fail_to_pass: list[str],
        pass_to_pass: list[str],
        env: dict[str, str] | None = None,
        gold: Path | None = None,
    ) -> Path:
        task = {
            "id": "toy-001",
            "repo": str(self.repo),
            "issue": "add(2, 3) returns -1; it should return 5.",
            "test_command": "python -m unittest discover -s tests -t . -v",
            "fail_to_pass": fail_to_pass,
            "pass_to_pass": pass_to_pass,
            "max_steps": 12,
        }
        if env:
            task["env"] = env
        if gold:
            task["gold_patch"] = str(gold)
        path = self.tmp / name
        path.write_text(json.dumps(task) + "\n", encoding="utf-8")
        return path

    def test_fixed_task_is_scored_as_a_pass(self) -> None:
        tasks = self._write_tasks("tasks.jsonl", FAIL_TO_PASS, PASS_TO_PASS)
        out_dir = self.tmp / "out"
        with mock.patch.object(harness, "run_agent", scripted_run_agent):
            code = harness.run_eval(tasks, out_dir=out_dir)
        summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(summary["pass@1"], 1.0)
        self.assertEqual(summary["stages"], {"ok": 1})
        record = json.loads((out_dir / "results.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertTrue(record["fixed"])
        self.assertEqual(record["touched_files"], ["calc/ops.py"])

    def test_a_task_that_is_not_broken_is_rejected_before_the_agent_runs(self) -> None:
        # PASS_TO_PASS already succeeds, so this task cannot prove anything.
        tasks = self._write_tasks("bad.jsonl", PASS_TO_PASS, [])
        out_dir = self.tmp / "out-bad"
        with mock.patch.object(
            harness, "run_agent", mock.MagicMock(side_effect=scripted_run_agent)
        ) as patched:
            code = harness.run_eval(tasks, out_dir=out_dir)
        summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(code, 1)
        self.assertEqual(summary["stages"], {"pre_check": 1})
        self.assertFalse(patched.called)

    def test_check_only_proves_the_gold_patch_solves_the_task(self) -> None:
        # The reference fix is applied to a scratch checkout: add() becomes correct.
        gold = self.tmp / "gold.patch"
        # newline="\n" matters: write_text would translate every LF to CRLF on Windows
        # and git apply would then refuse the patch. The same trap tools.py guards against.
        gold.write_text(
            "diff --git a/calc/ops.py b/calc/ops.py\n"
            "--- a/calc/ops.py\n"
            "+++ b/calc/ops.py\n"
            "@@ -3,4 +3,4 @@\n"
            " \n"
            " def add(a, b):\n"
            "-    return a - b\n"
            "+    return a + b\n"
            " \n",
            encoding="utf-8",
            newline="\n",
        )
        tasks = self._write_tasks("gold.jsonl", FAIL_TO_PASS, PASS_TO_PASS, gold=gold)
        self.assertEqual(harness.run_eval(tasks, check_only=True), 0)

    def test_check_only_rejects_a_gold_patch_that_does_not_solve_the_task(self) -> None:
        # A patch that applies but leaves the failing test failing means the fixture, the
        # node ids or the env are wrong: the task would be scored as a miss forever.
        gold = self.tmp / "gold-bad.patch"
        gold.write_text(
            "diff --git a/README.md b/README.md\n"
            "--- a/README.md\n"
            "+++ b/README.md\n"
            "@@ -1,3 +1,3 @@\n"
            " # toyrepo\n"
            "\n"
            "-A deliberately broken two-function package.\n"
            "+Still broken.\n",
            encoding="utf-8",
            newline="\n",
        )
        tasks = self._write_tasks("gold-bad.jsonl", FAIL_TO_PASS, PASS_TO_PASS, gold=gold)
        self.assertEqual(harness.run_eval(tasks, check_only=True), 1)

    def test_verification_commands_leave_no_bytecode_behind(self) -> None:
        # Stale bytecode is invisible and cuts both ways: Python reuses a .pyc when the
        # source keeps the same mtime second and the same byte length, so the pre-fix
        # bytecode can answer for the post-fix run. A correct one-line fix gets scored as
        # a failure, and a same-size regression hides behind a green run. The harness must
        # therefore never let a verification command write bytecode.
        self.assertEqual(harness.run_shell(PASS_TO_PASS[0], self.repo)[0], 0)
        self.assertEqual(harness.run_shell(FAIL_TO_PASS[0], self.repo)[0], 1)
        self.assertEqual(list(self.repo.rglob("__pycache__")), [])

    def test_task_env_reaches_the_agent_and_the_verification_commands(self) -> None:
        tasks = self._write_tasks(
            "env.jsonl", FAIL_TO_PASS, PASS_TO_PASS + ENV_CHECK, env={"TASK_FLAG": "1"}
        )
        out_dir = self.tmp / "out-env"
        captured: dict[str, object] = {}

        def capture(cfg, reference_repo=None, **kwargs):
            captured["env"] = dict(cfg.env)
            return real_run_agent(
                cfg, llm=ScriptedLLM(fixing_script()), reference_repo=reference_repo
            )

        with mock.patch.object(harness, "run_agent", mock.MagicMock(side_effect=capture)):
            code = harness.run_eval(tasks, out_dir=out_dir)
        summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(captured["env"], {"TASK_FLAG": "1"})
        self.assertEqual(code, 0)
        self.assertEqual(summary["stages"], {"ok": 1})

    def test_run_evidence_survives_the_temporary_work_root(self) -> None:
        run_dir = self.tmp / "run-evidence"
        run_dir.mkdir()
        (run_dir / "trace.jsonl").write_text("{}\n", encoding="utf-8")
        (run_dir / "patch.diff").write_text("diff --git a/x b/x\n", encoding="utf-8")
        outcome = harness.TaskOutcome(
            id="toy-001", fixed=False, stage="ok", run_dir=str(run_dir)
        )
        out_dir = self.tmp / "kept"
        harness.keep_artifacts(outcome, out_dir)
        self.assertEqual(outcome.run_dir, str(out_dir / "artifacts" / "toy-001"))
        self.assertTrue((out_dir / "artifacts" / "toy-001" / "trace.jsonl").is_file())
        self.assertTrue((out_dir / "artifacts" / "toy-001" / "patch.diff").is_file())


class IssueLeakTests(unittest.TestCase):
    """Gate 0: the prompt must not contain the answer it is asking for.

    An issue text carrying the upstream fix sha or its subject line turns diagnosis into
    recall. Nothing about the resulting run looks wrong - which is exactly why the check
    has to be mechanical.
    """

    def _task(self, issue: str, leak_terms: list[str] | None = None) -> harness.Task:
        return harness.Task(id="t", repo=".", issue=issue, leak_terms=leak_terms or [])

    def test_clean_issue_passes(self) -> None:
        self.assertIsNone(harness.issue_leak(self._task('echo(b"", f) raises TypeError')))

    def test_declared_leak_term_is_refused(self) -> None:
        task = self._task("已合并修复 1c20dc6 之后就好了", ["1c20dc6"])
        self.assertIsNotNone(harness.issue_leak(task))

    def test_provenance_header_is_refused_even_without_a_declared_term(self) -> None:
        self.assertIsNotNone(harness.issue_leak(self._task("来源：上游 PR #296")))

    def test_leaked_task_is_refused_before_anything_is_cloned(self) -> None:
        outcome = harness.run_one(
            self._task("来源：上游 PR #296"), Path("."), None, None, pre_check_only=True
        )
        self.assertEqual(outcome.stage, "issue_leak")


if __name__ == "__main__":
    unittest.main()
