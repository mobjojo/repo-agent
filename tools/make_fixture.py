"""Build a task fixture: the one repository state the agent is allowed to see.

A fixture is a repository checked out at the buggy base commit with **only the tests**
of the merged fix applied and committed on top. Two properties matter more than anything
else, and both are enforced here rather than left to discipline:

1. the failing test exists at all, otherwise ``fail_to_pass`` can never turn green;
2. the repository holds no trace of the future - no remote, no branch, no tag and no
   unreachable object that still contains the reference fix. A fixture that ships the
   answer makes every score the harness produces meaningless.

    python tools/make_fixture.py ^
      --source work/itsdangerous-full ^
      --commit b11475a ^
      --dest .repos/itsdangerous-124 ^
      --test-patch work/m2-002-test.patch ^
      --forbid 526b1ea ^
      --message "task fixture: date_signed must be a datetime (#124)"

Or let the tool carve the patch itself out of the merged fix, which is the usual case:

    python tools/make_fixture.py ^
      --source work/click-full --commit <base> --fix 4d3db84 ^
      --dest .repos/click-echo --fixtures-dir tasks/fixtures/click-echo
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from split_pr_diff import classify, split_blocks  # noqa: E402  (sibling tool)


def extract_patches(source: Path, base: str, fix: str, out_dir: Path) -> tuple[Path, Path]:
    """Carve the merged fix into test.patch (for the fixture) and gold.patch (the reference).

    Doing this here rather than by hand keeps one rule in one place: whatever lives under
    tests/ ends up in the fixture, everything that is source ends up in the reference fix.
    """
    diff = git(source, "diff", base, fix)[1]
    buckets: dict[str, list[str]] = {"test": [], "gold": [], "ignored": []}
    for block in split_blocks(diff):
        buckets[classify(block)].append(block)
    if not buckets["test"]:
        raise SystemExit(f"{base}..{fix} changes no test file: it cannot become a task")
    if not buckets["gold"]:
        raise SystemExit(f"{base}..{fix} changes no source file: nothing to fix")
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for kind, name in (("test", "test.patch"), ("gold", "gold.patch")):
        target = out_dir / name
        # newline="" keeps the diff byte-exact; git apply is strict about that.
        target.write_text("".join(buckets[kind]), encoding="utf-8", newline="")
        written.append(target)
    for block in buckets["ignored"]:
        print(f"ignored: {block.splitlines()[0][11:]}")
    return written[0], written[1]


def _clear_readonly(func, path, _error) -> None:
    """Git marks packed files read-only, which makes plain rmtree fail on Windows."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def rmtree(path: Path) -> None:
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_clear_readonly)
    else:  # pragma: no cover - kept so the tool also runs on older interpreters
        shutil.rmtree(path, onerror=_clear_readonly)


def git(root: Path, *args: str, check: bool = True) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    if check and proc.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed in {root}:\n{output.strip()}")
    return proc.returncode, output


def clone_fixture(source: Path, dest: Path, force: bool = False) -> None:
    if dest.exists():
        if not force:
            raise SystemExit(f"{dest} already exists; pass --force to rebuild it")
        # Guard rail: only ever delete an empty directory or a real git checkout.
        if not (dest / ".git").is_dir() and any(dest.iterdir()):
            raise SystemExit(
                f"refusing to delete {dest}: it holds data but is not a git checkout"
            )
        rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "git",
            "clone",
            "--quiet",
            "--no-hardlinks",
            "--config",
            "core.autocrlf=false",
            str(source),
            str(dest),
        ],
        check=True,
    )


def strip_future(dest: Path) -> None:
    """Remove every reference that could carry commits newer than the base commit."""
    git(dest, "remote", "remove", "origin", check=False)
    for tag in git(dest, "tag", "-l")[1].split():
        git(dest, "tag", "-d", tag, check=False)
    for branch in git(dest, "branch", "--format=%(refname:short)")[1].split():
        git(dest, "branch", "-D", branch, check=False)
    git(dest, "reflog", "expire", "--expire=now", "--all")
    git(dest, "gc", "--prune=now", "--quiet")


def audit(dest: Path, source: Path, commit: str, forbidden: list[str]) -> list[str]:
    """Prove the fixture is minimal: the base ancestry only, none of the fix commits."""
    problems: list[str] = []
    # Reachable history must be exactly the base ancestry plus our own fixture commit(s).
    base_count = int(git(source, "rev-list", "--count", commit)[1].strip())
    fixture_count = int(git(dest, "rev-list", "--count", f"{commit}..HEAD")[1].strip() or 0)
    actual = int(git(dest, "rev-list", "--all", "--count")[1].strip())
    if actual != base_count + fixture_count:
        problems.append(
            f"history is not minimal: {actual} reachable commits, expected "
            f"{base_count} (base) + {fixture_count} (fixture) - the future leaked in"
        )
    if git(dest, "remote")[1].strip():
        problems.append("the fixture still has a remote configured")
    for sha in forbidden:
        code, _ = git(dest, "cat-file", "-e", f"{sha}^{{commit}}", check=False)
        if code == 0:
            problems.append(f"{sha} (a commit from the future) is still present")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="local clone holding the full history")
    parser.add_argument("--commit", required=True, help="buggy base commit to check out")
    parser.add_argument("--dest", required=True, help="where to build the fixture")
    parser.add_argument("--test-patch", help="diff with the tests from the merged fix")
    parser.add_argument("--fix", help="the merged fix commit; carve both patches out of it")
    parser.add_argument(
        "--fixtures-dir",
        help="where test.patch/gold.patch are written when --fix is used (default: next to --dest)",
    )
    parser.add_argument("--message", default="task fixture: add the failing test")
    parser.add_argument(
        "--forbid",
        action="append",
        default=[],
        help="commit that must NOT survive in the fixture (the reference fix)",
    )
    parser.add_argument("--branch", default="main")
    parser.add_argument("--force", action="store_true", help="rebuild an existing fixture")
    args = parser.parse_args(argv)

    source = Path(args.source).resolve()
    dest = Path(args.dest).resolve()

    if args.fix:
        fixtures_dir = Path(args.fixtures_dir or f"{args.dest}.fixture")
        if not fixtures_dir.is_absolute():
            fixtures_dir = (Path.cwd() / fixtures_dir).resolve()
        test_patch, gold_patch = extract_patches(source, args.commit, args.fix, fixtures_dir)
        print(f"test    : {test_patch}")
        print(f"gold    : {gold_patch}")
        args.test_patch = str(test_patch)
    if not args.test_patch:
        raise SystemExit("pass --test-patch, or --fix to carve the patches out of the fix commit")

    clone_fixture(source, dest, force=args.force)
    git(dest, "checkout", "--quiet", "-B", args.branch, args.commit)
    strip_future(dest)

    if args.test_patch:
        git(dest, "apply", str(Path(args.test_patch).resolve()))
        git(dest, "add", "-A")
        git(
            dest,
            "-c",
            "user.name=task fixture",
            "-c",
            "user.email=fixture@localhost",
            "commit",
            "--quiet",
            "-m",
            args.message,
        )
        git(dest, "reflog", "expire", "--expire=now", "--all")
        git(dest, "gc", "--prune=now", "--quiet")

    head = git(dest, "log", "-1", "--format=%H %s")[1].strip()
    print(f"fixture : {dest}")
    print(f"head    : {head}")
    print(f"files   : {len(git(dest, 'ls-files')[1].splitlines())} tracked")

    problems = audit(dest, source, args.commit, args.forbid)
    for problem in problems:
        print(f"AUDIT FAIL: {problem}")
    if problems:
        return 1
    print(
        f"audit   : {git(dest, 'rev-list', '--all', '--count')[1].strip()} commit(s), "
        "no remote, no future history"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
