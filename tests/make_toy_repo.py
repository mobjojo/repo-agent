"""Materialise a tiny buggy repository: the fixture for smoke tests and the demo task.

    python tests/make_toy_repo.py work/toyrepo
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

OPS = '''"""Tiny arithmetic helpers used by the toy repository."""


def add(a, b):
    return a - b


def mul(a, b):
    return a * b


def add_all(values):
    total = 0
    for value in values:
        total = add(total, value)
    return total
'''

TESTS = '''import unittest

from calc.ops import add, add_all, mul


class TestOps(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(2, 3), 5)

    def test_mul(self):
        self.assertEqual(mul(2, 3), 6)

    def test_add_all(self):
        self.assertEqual(add_all([1, 2, 3]), 6)


if __name__ == "__main__":
    unittest.main()
'''

README = """# toyrepo

A deliberately broken two-function package. `add` returns the difference instead of the
sum, so `tests/test_ops.py` fails. Used to smoke-test the agent loop end to end.
"""

FILES = {
    "README.md": README,
    "calc/__init__.py": "",
    "calc/ops.py": OPS,
    "tests/__init__.py": "",
    "tests/test_ops.py": TESTS,
}


def build_toy_repo(dest: str | Path, force: bool = False) -> Path:
    dest = Path(dest).resolve()
    if dest.exists():
        if not force:
            return dest
        raise FileExistsError(f"{dest} already exists")
    for name, text in FILES.items():
        path = dest / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    env_args = ["-c", "user.email=agent@localhost", "-c", "user.name=repo-agent"]
    subprocess.run(["git", "init", "--quiet", "-b", "main", str(dest)], check=True)
    # Set the line-ending policy before staging, or the very first add rewrites the blobs.
    subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=str(dest), check=True)
    subprocess.run(["git", "config", "core.eol", "lf"], cwd=str(dest), check=True)
    subprocess.run(["git", *env_args, "add", "-A"], cwd=str(dest), check=True)
    subprocess.run(
        ["git", *env_args, "commit", "--quiet", "-m", "toyrepo: initial state"],
        cwd=str(dest),
        check=True,
    )
    return dest


def main(argv: list[str]) -> int:
    dest = argv[1] if len(argv) > 1 else "toyrepo"
    path = build_toy_repo(dest)
    print(f"toy repository ready: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
