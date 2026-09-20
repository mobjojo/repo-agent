"""Sandbox wiring: task-level env must reach both backends, output must stay bounded."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from repo_agent.config import RunConfig
from repo_agent.sandbox import DockerSandbox, LocalSandbox, make_sandbox

PRINT_FLAG = "python -c \"import os; print(os.environ.get('TASK_FLAG'))\""
NOISY = "python -c \"print('A' * 5000)\""
# A *grandchild* that outlives the shell: with shell=True the direct child is cmd.exe,
# so this is the shape that used to leave run() blocked on an open pipe forever.
SLEEPING_GRANDCHILD = (
    "python -c \"import subprocess, sys; "
    "subprocess.run([sys.executable, '-c', 'import time; time.sleep(120)'])\""
)


class LocalSandboxTests(unittest.TestCase):
    def test_task_env_reaches_the_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = RunConfig(task="t", workspace=Path(tmp), env={"TASK_FLAG": "1"})
            sandbox = make_sandbox(cfg)
            self.assertIsInstance(sandbox, LocalSandbox)
            result = sandbox.run(PRINT_FLAG)
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("1", result.output)

    def test_large_output_is_truncated_with_head_and_tail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = LocalSandbox(Path(tmp), max_output_bytes=200)
            result = sandbox.run(NOISY)
            self.assertTrue(result.truncated)
            self.assertIn("chars omitted", result.output)

    def test_command_runs_inside_the_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "marker.txt").write_text("hello", encoding="utf-8")
            sandbox = LocalSandbox(root)
            result = sandbox.run("git --version")
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertEqual(sandbox.root, root.resolve())

    def test_timeout_kills_the_whole_process_tree(self) -> None:
        """A timeout must bound wall time even when the work is in a grandchild."""
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = LocalSandbox(Path(tmp))
            started = time.time()
            result = sandbox.run(SLEEPING_GRANDCHILD, timeout=1.0)
            elapsed = time.time() - started
            self.assertTrue(result.timed_out, result.output)
            self.assertEqual(result.exit_code, 124)
            self.assertLess(
                elapsed,
                30.0,
                f"run() did not return promptly after its timeout ({elapsed:.1f}s)",
            )


class DockerSandboxTests(unittest.TestCase):
    """The Docker backend cannot run in CI without a daemon, so pin down its contract."""

    def setUp(self) -> None:
        self.cfg = RunConfig(
            task="t",
            workspace=Path("."),
            sandbox="docker",
            image="python:3.11-slim",
            env={"PYTHONPATH": "src"},
        )

    def test_argv_enforces_isolation_policy(self) -> None:
        argv = DockerSandbox(self.cfg)._argv("agent-test")
        self.assertEqual(argv[argv.index("--network") + 1], "none")
        self.assertEqual(argv[argv.index("--name") + 1], "agent-test")
        self.assertIn("PYTHONPATH=src", argv)
        self.assertIn("python:3.11-slim", argv)
        self.assertEqual(argv[-2:], ["bash", "-s"])
        self.assertTrue(any(part.endswith(":/workspace") for part in argv))


if __name__ == "__main__":
    unittest.main()
