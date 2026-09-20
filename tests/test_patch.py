"""The patch contract is what the whole evaluation rests on, so test it directly."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from repo_agent.patch import collect_patch, touched_files, validate_patch
from repo_agent.task import SCRATCH_DIR, prepare_workspace
from tests.make_toy_repo import build_toy_repo

PROTECTED = ("**/tests/**", "**/test_*.py")


class PatchContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.origin = build_toy_repo(self.tmp / "origin")
        self.workspace = prepare_workspace(self.origin, self.tmp / "workspace")
        self.reference = prepare_workspace(self.origin, self.tmp / "reference")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _edit(self, rel: str, old: str, new: str) -> None:
        path = self.workspace / rel
        path.write_text(
            path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8", newline="\n"
        )

    def test_source_fix_is_a_valid_patch(self) -> None:
        self._edit("calc/ops.py", "return a - b", "return a + b")
        patch = collect_patch(self.workspace)
        self.assertEqual(touched_files(patch), ["calc/ops.py"])
        contract = validate_patch(patch, PROTECTED, self.reference)
        self.assertTrue(contract.ok, contract.violations)
        self.assertEqual(contract.added_lines, 1)
        self.assertEqual(contract.removed_lines, 1)

    def test_scratchpad_is_writable_but_never_reaches_the_patch(self) -> None:
        """The model needs somewhere for throwaway scripts, and the diff must not see it.

        The guard refuses any path outside the workspace, so a scratch script has to live
        inside it - and without this exclusion it ships in the submitted patch (two M3 click
        tasks submitted 91 lines of debug prints and nothing else).
        """
        scratch = self.workspace / SCRATCH_DIR / "repro.py"
        scratch.parent.mkdir(parents=True, exist_ok=True)
        scratch.write_text("print('debug')\n", encoding="utf-8", newline="\n")
        self.assertEqual(collect_patch(self.workspace).strip(), "")

    def test_a_stray_script_in_the_repository_still_reaches_the_patch(self) -> None:
        """Control: the exclusion covers the scratchpad, not untracked files in general."""
        (self.workspace / "scratch_repro.py").write_text(
            "print('debug')\n", encoding="utf-8", newline="\n"
        )
        self.assertEqual(touched_files(collect_patch(self.workspace)), ["scratch_repro.py"])

    def test_editing_a_test_file_voids_the_patch(self) -> None:
        self._edit("tests/test_ops.py", "self.assertEqual(add(2, 3), 5)", "pass")
        patch = collect_patch(self.workspace)
        contract = validate_patch(patch, PROTECTED, self.reference)
        self.assertFalse(contract.ok)
        self.assertIn("touched a protected file: tests/test_ops.py", contract.violations)

    def test_empty_patch_is_invalid(self) -> None:
        contract = validate_patch("", PROTECTED, self.reference)
        self.assertFalse(contract.ok)
        self.assertEqual(contract.violations, ["no changes were produced"])

    def test_patch_that_cannot_apply_is_invalid(self) -> None:
        patch = (
            "diff --git a/calc/ops.py b/calc/ops.py\n"
            "--- a/calc/ops.py\n"
            "+++ b/calc/ops.py\n"
            "@@ -1,2 +1,2 @@\n"
            "-def add(a, b):\n"
            "+def add(a, b, c=0):\n"
            "     return a - b\n"
        )
        contract = validate_patch(patch, PROTECTED, self.reference)
        self.assertFalse(contract.applies_cleanly)
        self.assertFalse(contract.ok)


if __name__ == "__main__":
    unittest.main()
