"""End-to-end loop tests with a scripted model: no API key, no network, no Docker."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage

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


def nudges(cfg: RunConfig) -> list[dict]:
    """The budget warnings the loop sent, in order. The trace is the only witness."""
    events = [
        json.loads(line)
        for line in (cfg.run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return [event for event in events if event["kind"] == "budget_nudge"]


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

    def test_a_run_that_never_edited_is_told_to_start_editing(self) -> None:
        # Of the 15 failed runs on the 2026-09-21 batches, 11 never edited a source file at
        # all - they spent the whole budget reading. What runs out first there is attention,
        # so the message has to be "start editing"; "submit what you have" would be advice
        # to submit nothing.
        cfg = self._config("nudge-no-edit", max_steps=10)
        prompts: list[str] = []

        def looking_around(messages):
            prompts.append("\n".join(str(m.content) for m in messages))
            index = len(prompts)
            return call("bash", {"command": f"echo {index}"}, f"n{index}")

        script = [looking_around] * 9 + [call("submit", {"summary": "gave up"}, "last")]
        run_agent(cfg, llm=ScriptedLLM(script))

        warned = nudges(cfg)
        self.assertEqual([event["level"] for event in warned], [1, 2])
        self.assertEqual(warned[0]["step"], 7)
        self.assertFalse(warned[0]["edited"])
        self.assertIn("have not edited a single source file", warned[0]["message"])
        self.assertIn("call submit now", warned[1]["message"])
        # A message the model never receives is not a warning: the next call must carry it.
        self.assertIn("have not edited a single source file", prompts[7])

    def test_a_run_that_has_edited_is_told_to_wrap_up_instead(self) -> None:
        cfg = self._config("nudge-edited", max_steps=10)
        script = [
            call("view", {"path": "calc/ops.py"}, "e0"),
            call(
                "replace_in_file",
                {"path": "calc/ops.py", "old": "    return a - b", "new": "    return a + b"},
                "e1",
            ),
        ]
        script += [call("bash", {"command": f"echo {index}"}, f"e{index + 2}") for index in range(7)]
        script += [call("submit", {"summary": "fix"}, "e9")]
        result = run_agent(cfg, llm=ScriptedLLM(script))

        warned = nudges(cfg)
        self.assertTrue(result.valid, result.contract_violations)
        self.assertTrue(warned[0]["edited"])
        self.assertIn("call submit", warned[0]["message"])
        self.assertNotIn("have not edited", warned[0]["message"])

    def test_a_scratch_script_does_not_count_as_an_edit(self) -> None:
        # Writing .repo-agent/repro.py is not progress. The runs that died with an empty
        # patch had exactly this shape: several scratch scripts, zero source edits.
        cfg = self._config("nudge-scratch", max_steps=10)
        script = [
            call(
                "create_file",
                {"path": ".repo-agent/repro.py", "content": "print('probe')"},
                "s1",
            )
        ]
        script += [call("bash", {"command": f"echo {index}"}, f"s{index + 2}") for index in range(7)]
        script += [call("submit", {"summary": "gave up"}, "s9")]
        run_agent(cfg, llm=ScriptedLLM(script))

        warned = nudges(cfg)
        self.assertFalse(warned[0]["edited"])
        self.assertIn("have not edited a single source file", warned[0]["message"])

    def test_the_nudge_does_not_repeat_every_step(self) -> None:
        # A warning on every step is noise that costs tokens - the failure mode this whole
        # change is about. Two levels, then silence.
        cfg = self._config("nudge-once", max_steps=10)
        script = [call("bash", {"command": f"echo {index}"}, f"o{index}") for index in range(9)]
        script += [call("submit", {"summary": "gave up"}, "olast")]
        run_agent(cfg, llm=ScriptedLLM(script))

        warned = nudges(cfg)
        self.assertEqual(len(warned), 2, [event["step"] for event in warned])
        self.assertEqual([event["step"] for event in warned], [7, 9])

    def test_a_run_that_stops_on_the_budget_gets_no_warning(self) -> None:
        # The step budget runs out at 100%: there is no next model call to warn, and a
        # message nobody reads is just a line in the trace.
        cfg = self._config("nudge-too-late", max_steps=3)
        script = [call("bash", {"command": f"echo {index}"}, f"t{index}") for index in range(9)]
        result = run_agent(cfg, llm=ScriptedLLM(script))
        self.assertEqual(result.stop_reason, "budget:steps")
        self.assertEqual(nudges(cfg), [])


if __name__ == "__main__":
    unittest.main()
