"""The guard is the security boundary, so it gets its own tests."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from repo_agent.guard import Guard, GuardError, matches, protected_files_in


class MatchTests(unittest.TestCase):
    def test_directory_pattern_matches_at_any_depth(self) -> None:
        self.assertTrue(matches("tests/test_ops.py", ["**/tests/**"]))
        self.assertTrue(matches("pkg/tests/helper.py", ["**/tests/**"]))
        self.assertFalse(matches("calc/ops.py", ["**/tests/**"]))

    def test_test_prefix_pattern(self) -> None:
        self.assertTrue(matches("test_ops.py", ["**/test_*.py"]))
        self.assertTrue(matches("pkg/test_ops.py", ["**/test_*.py"]))
        self.assertFalse(matches("pkg/ops.py", ["**/test_*.py"]))

    def test_plain_pattern_is_anchored(self) -> None:
        self.assertTrue(matches("pkg/mod.py", ["pkg/*.py"]))
        self.assertFalse(matches("other/pkg/mod.py", ["pkg/*.py"]))

    def test_protected_files_in_lists_only_offenders(self) -> None:
        touched = ["calc/ops.py", "tests/test_ops.py", "pkg/test_util.py"]
        self.assertEqual(
            protected_files_in(touched, ["**/tests/**", "**/test_*.py"]),
            ["pkg/test_util.py", "tests/test_ops.py"],
        )


class GuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "calc").mkdir()
        (self.root / "calc" / "ops.py").write_text("x = 1\n", encoding="utf-8")
        (self.root / "tests").mkdir()
        (self.root / "tests" / "test_ops.py").write_text("y = 2\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _guard(self, **kwargs: object) -> Guard:
        defaults: dict[str, object] = {
            "root": self.root,
            "protected_globs": ("**/tests/**",),
            "forbidden_prefixes": (".git/",),
        }
        defaults.update(kwargs)
        return Guard(**defaults)  # type: ignore[arg-type]

    def test_relative_paths_resolve_inside_the_workspace(self) -> None:
        self.assertEqual(self._guard().check_write("calc/ops.py"), "calc/ops.py")

    def test_traversal_is_rejected(self) -> None:
        with self.assertRaises(GuardError):
            self._guard().check_write("../outside.py")

    def test_absolute_path_outside_the_workspace_is_rejected(self) -> None:
        with self.assertRaises(GuardError):
            self._guard().check_write(str(self.root.parent / "elsewhere.py"))

    def test_writing_to_test_files_is_rejected(self) -> None:
        with self.assertRaises(GuardError):
            self._guard().check_write("tests/test_ops.py")

    def test_reading_test_files_is_allowed(self) -> None:
        self.assertEqual(self._guard().check_read("tests/test_ops.py"), "tests/test_ops.py")

    def test_version_control_internals_are_write_forbidden(self) -> None:
        guard = Guard(root=self.root, protected_globs=(), forbidden_prefixes=(".git/",))
        with self.assertRaises(GuardError):
            guard.check_write(".git/config")

    def test_editable_globs_restrict_writes(self) -> None:
        guard = Guard(
            root=self.root, protected_globs=(), forbidden_prefixes=(), editable_globs=("calc/**",)
        )
        self.assertEqual(guard.check_write("calc/ops.py"), "calc/ops.py")
        with self.assertRaises(GuardError):
            guard.check_write("docs/index.md")


if __name__ == "__main__":
    unittest.main()
