"""Editing tools must not rewrite line endings.

On Windows, ``Path.write_text`` translates every ``\\n`` to ``\\r\\n``. That turns a one-line
fix into a whole-file diff, which is both unreviewable and a giveaway that the tooling is
broken. These tests pin the byte-level behaviour.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from repo_agent.config import RunConfig
from repo_agent.guard import Guard
from repo_agent.sandbox import LocalSandbox
from repo_agent.tools import WorkspaceTools


class EditorLineEndingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.tools = WorkspaceTools(
            RunConfig(task="t", workspace=self.root),
            LocalSandbox(self.root),
            Guard(
                root=self.root,
                protected_globs=("**/tests/**",),
                forbidden_prefixes=(".git/",),
            ),
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, rel: str, data: bytes) -> Path:
        path = self.root / rel
        path.write_bytes(data)
        return path

    def test_lf_file_stays_lf(self) -> None:
        path = self._write("a.py", b"one\ntwo\nthree\n")
        outcome = self.tools.dispatch(
            "replace_in_file", {"path": "a.py", "old": "two", "new": "TWO"}
        )
        self.assertTrue(outcome.ok, outcome.content)
        self.assertEqual(path.read_bytes(), b"one\nTWO\nthree\n")

    def test_crlf_file_stays_crlf(self) -> None:
        path = self._write("b.py", b"one\r\ntwo\r\nthree\r\n")
        outcome = self.tools.dispatch(
            "replace_in_file", {"path": "b.py", "old": "two", "new": "TWO"}
        )
        self.assertTrue(outcome.ok, outcome.content)
        self.assertEqual(path.read_bytes(), b"one\r\nTWO\r\nthree\r\n")

    def test_insert_lines_preserves_the_separator(self) -> None:
        path = self._write("c.py", b"one\nthree\n")
        self.tools.dispatch("insert_lines", {"path": "c.py", "line": 2, "text": "two"})
        self.assertEqual(path.read_bytes(), b"one\ntwo\nthree\n")

    def test_new_files_are_written_with_lf(self) -> None:
        self.tools.dispatch("create_file", {"path": "d.py", "content": "x = 1\ny = 2\n"})
        self.assertEqual((self.root / "d.py").read_bytes(), b"x = 1\ny = 2\n")

    def test_git_reports_a_one_line_change(self) -> None:
        subprocess.run(["git", "init", "--quiet", "-b", "main", str(self.root)], check=True)
        subprocess.run(
            ["git", "config", "core.autocrlf", "false"], cwd=str(self.root), check=True
        )
        self._write("mod.py", b"def f():\n    return 1\n")
        subprocess.run(["git", "add", "-A"], cwd=str(self.root), check=True)
        subprocess.run(
            ["git", "-c", "user.email=a@b", "-c", "user.name=a", "commit", "--quiet", "-m", "init"],
            cwd=str(self.root),
            check=True,
        )
        self.tools.dispatch(
            "replace_in_file", {"path": "mod.py", "old": "return 1", "new": "return 2"}
        )
        diff = subprocess.run(
            ["git", "diff"], cwd=str(self.root), capture_output=True
        ).stdout.decode("utf-8")
        added = [line for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++")]
        removed = [line for line in diff.splitlines() if line.startswith("-") and not line.startswith("---")]
        self.assertEqual(added, ["+    return 2"])
        self.assertEqual(removed, ["-    return 1"])


if __name__ == "__main__":
    unittest.main()
