"""Split a pull-request diff into the test patch and the source (gold) patch.

This is the mechanical part of turning a merged bugfix PR into a scored task: the test
patch is applied to the base commit to build the task fixture, the source patch is the
reference fix used to prove the task is solvable.

    curl -sL -H "Accept: application/vnd.github.v3.diff" \\
      https://api.github.com/repos/<owner>/<repo>/pulls/<n> -o pr.diff
    python tools/split_pr_diff.py pr.diff --out-dir work

Writes ``test.patch`` and ``gold.patch`` next to each other and prints what it ignored.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def split_blocks(diff_text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    for line in diff_text.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current:
                blocks.append("".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append("".join(current))
    return blocks


def classify(block: str) -> str:
    header = block.splitlines()[0]
    parts = header.split()
    path = parts[-1] if len(parts) >= 4 else header
    if path.startswith("b/"):
        path = path[2:]
    segments = path.split("/")
    name = segments[-1]
    if segments[:1] == ["tests"] or "tests" in segments or "test" in segments:
        return "test"
    if name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py":
        return "test"
    if path.startswith("src/") or path.endswith(".py"):
        return "gold"
    return "ignored"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("diff", help="path to a PR diff file")
    parser.add_argument("--out-dir", default="work", help="where to write the patches")
    args = parser.parse_args(argv)

    blocks = split_blocks(Path(args.diff).read_text(encoding="utf-8"))
    buckets: dict[str, list[str]] = {"test": [], "gold": [], "ignored": []}
    for block in blocks:
        buckets[classify(block)].append(block)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for kind, filename in (("test", "test.patch"), ("gold", "gold.patch")):
        # newline="" keeps the diff byte-exact; git apply is strict about that.
        (out_dir / filename).write_text("".join(buckets[kind]), encoding="utf-8", newline="")
        files = [b.splitlines()[0][11:] for b in buckets[kind]]
        print(f"{filename}: {len(files)} block(s)")
        for name in files:
            print(f"    {name}")
    for name in [b.splitlines()[0][11:] for b in buckets["ignored"]]:
        print(f"ignored (not needed for scoring): {name}")
    if not buckets["test"]:
        print("WARNING: no test changes found - this PR cannot be turned into a task as-is")
    if not buckets["gold"]:
        print("WARNING: no source changes found - nothing to fix")
    return 0


if __name__ == "__main__":
    sys.exit(main())
