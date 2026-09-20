"""End-to-end loop tests with a scripted model: no API key, no network, no Docker."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from langchain_core.messages import AIMessage

from repo_agent.config import Budget, RunConfig
from repo_agent.llm import ScriptedLLM
from repo_agent.runner import run_agent
from repo_agent.task import prepare_workspace
from tests.make_toy_repo import build_toy_repo

REPRO = "python -m unittest discover -s tests -t . -v"
PROTECTED = ("**/tests/**", "**/test_*.py")


def call(name: str, args: dict[str, object], call_id: str) -> AIMessage:
    return AIMessage(content=f"calling {name}", tool_calls=[{"name": name, "args": args, "id": call_id}])


def fixing_script() -> list[AIMessage]:
    return [
        call("bash", {"command": REPRO}, "c1"),
        call("view", {"path": "calc/ops.py"}, "c2"),
        call(
            "replace_in_file",
            {"path": "calc/ops.py", "old": "    return a - b", "new": "    return a + b"},
            "c3",
        ),
        call("bash", {"command": REPRO}, "c4"),
        call("submit", {"summary": "add() subtracted instead of adding"}, "c5"),
    ]


class ScriptedLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.origin = build_toy_repo(self.tmp / "origin")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _config(self, name: str, max_steps: int = 10) -> RunConfig:
        workspace = prepare_workspace(self.origin, self.tmp / name / "workspace")
        return RunConfig(
            task="tests/test_ops.py fails: add(2, 3) should be 5 but is -1.",
            workspace=workspace,
            test_command=REPRO,
            protected_globs=PROTECTED,
            budget=Budget(max_steps=max_steps, max_cost_usd=1.0, max_tokens=10**9),
            run_dir=self.tmp / name / "run",
        )

    def test_a_clean_fix_produces_a_valid_applicable_patch(self) -> None:
        cfg = self._config("fix")
        reference = prepare_workspace(self.origin, self.tmp / "fix" / "reference")
        result = run_agent(cfg, llm=ScriptedLLM(fixing_script()), reference_repo=reference)
        self.assertTrue(result.valid, result.contract_violations)
        self.assertEqual(result.touched_files, ["calc/ops.py"])
        self.assertIn("return a + b", result.patch)
        self.assertTrue(result.submitted)
        self.assertEqual(result.steps, 5)
        self.assertEqual(result.stop_reason, "submitted")

        # Independent verification: apply the patch to an untouched checkout.
        applied = prepare_workspace(self.origin, self.tmp / "fix" / "applied")
        proc = subprocess.run(
            ["git", "apply", "-"],
            cwd=str(applied),
            input=result.patch.encode("utf-8"),
            capture_output=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        test = subprocess.run(REPRO, cwd=str(applied), shell=True, capture_output=True)
        self.assertEqual(test.returncode, 0, test.stdout.decode("utf-8", "replace"))

    def test_writing_to_a_test_file_is_blocked_by_the_tools(self) -> None:
        cfg = self._config("cheat")
        script = [
            call("view", {"path": "tests/test_ops.py"}, "c1"),
            call(
                "replace_in_file",
                {"path": "tests/test_ops.py", "old": "self.assertEqual(add(2, 3), 5)", "new": "pass"},
                "c2",
            ),
            call("submit", {"summary": "weakened the test"}, "c3"),
        ]
        result = run_agent(cfg, llm=ScriptedLLM(script))
        events = [
            json.loads(line)
            for line in (cfg.run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        rejected = [e for e in events if e["kind"] == "tool_call" and not e["ok"]]
        self.assertEqual(len(rejected), 1)
        self.assertIn("protected", rejected[0]["observation"])
        self.assertEqual(result.touched_files, [])
        self.assertFalse(result.valid)

    def test_varying_commands_hit_the_step_budget(self) -> None:
        cfg = self._config("budget", max_steps=3)
        script = [call("bash", {"command": f"echo {index}"}, f"c{index}") for index in range(20)]
        result = run_agent(cfg, llm=ScriptedLLM(script))
        self.assertEqual(result.stop_reason, "budget:steps")
        self.assertEqual(result.steps, 3)
        self.assertFalse(result.valid)

    def test_repeating_the_same_call_stops_the_run_early(self) -> None:
        cfg = self._config("loop", max_steps=10)
        script = [call("bash", {"command": "echo tick"}, f"c{index}") for index in range(20)]
        result = run_agent(cfg, llm=ScriptedLLM(script))
        self.assertEqual(result.stop_reason, "no_progress:repeated_tool_call")
        self.assertEqual(result.steps, 5)

        events = [
            json.loads(line)
            for line in (cfg.run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        warnings = [e for e in events if e["kind"] == "loop_warning"]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["step"], 3)

    def test_a_warned_loop_can_still_recover_and_submit(self) -> None:
        cfg = self._config("loop-recover", max_steps=10)
        script = [call("bash", {"command": "echo tick"}, f"w{index}") for index in range(3)]
        script += fixing_script()
        result = run_agent(cfg, llm=ScriptedLLM(script))
        self.assertTrue(result.valid, result.contract_violations)
        self.assertEqual(result.stop_reason, "submitted")
        self.assertEqual(result.touched_files, ["calc/ops.py"])


if __name__ == "__main__":
    unittest.main()
