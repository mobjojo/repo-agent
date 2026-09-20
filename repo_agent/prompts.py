"""Prompt construction. Kept in one place so prompt changes are reviewable."""

from __future__ import annotations

import os

from .config import RunConfig
from .task import SCRATCH_DIR

SYSTEM_PROMPT = """\
You are a repository-level coding agent. You are given a bug report and a checkout of the
repository. Your job is to fix the root cause and leave a minimal, reviewable change.

Operating rules:
1. Reproduce first. Run the test command and read the actual failure before changing code.
2. Read before you write. Never edit a file you have not just read in this session.
3. Fix the source. Test files and test configuration are READ-ONLY by contract; edits to them
   are rejected by the tools and fail the task even if the tests would pass.
4. Work in small steps: one tool call per turn, then look at the observation.
5. Prefer bash with narrow commands (e.g. running a single test) over dumping whole files.
6. Before calling submit, run the reproduction command again and confirm it passes on the
   current working tree. If it still fails, keep working.
7. Your reasoning is logged to an external notes file automatically, so do not restate your
   plan for the record. Spend tokens on doing the work.

When you are done, call submit with a summary of the root cause and the fix.
"""


def build_system_prompt(cfg: RunConfig, notes: str = "") -> str:
    parts = [SYSTEM_PROMPT.rstrip()]
    if notes.strip():
        parts.append(
            "Notes from earlier in this run (external memory, may include dead ends):\n"
            + notes.strip()
        )
    return "\n\n".join(parts)


def scratch_hint() -> str:
    """Where a throwaway script belongs.

    Same lesson as shell_hint, one level deeper: the guard refuses any path outside the
    workspace, so "put it in %TEMP%" (which the prompt itself used to say) is advice the
    tools cannot follow. The scratch directory is writable and locally git-excluded, so a
    script there is legal to write and can never reach the submitted diff.
    """
    return (
        f"For anything longer than a one-liner, write a scratch script under `{SCRATCH_DIR}/` "
        "in the repository root (that directory is excluded from the patch) and run it there. "
        "Do not leave scratch files anywhere else in the repository."
    )


def shell_hint(cfg: RunConfig) -> str:
    """Tell the model which shell its command tool actually is.

    Without this, models assume a POSIX shell and burn turns on `ls`, `pwd`, `| tail`
    and `2>/dev/null`, none of which exist in Windows cmd.exe. The second half of the
    lesson came from the traces: models also `cd` into a directory they made up (the task
    id, the harness directory) even though the command already starts in the repository,
    and they inline multi-line Python in `-c` until the quoting breaks. Both cost a step
    and a round trip.
    """
    if cfg.sandbox == "docker":
        return (
            "bash inside a Linux container (POSIX: ls/pwd/cat/head/tail/find/grep are available). "
            "The shell already starts in the repository root: never cd anywhere. " + scratch_hint()
        )
    if os.name == "nt":
        return (
            "Windows cmd.exe (NOT a POSIX shell). `ls`, `pwd`, `cat`, `head`, `tail`, `find` "
            "and `grep` do not exist, and `2>/dev/null` is invalid. Use `dir`, `type`, `cd`, "
            "`findstr`; avoid piping into head/tail - read the whole output or narrow the "
            "command. The shell already starts in the repository root: never cd anywhere. "
            "cmd.exe mangles nested quotes, so prefer a scratch script over `python -c` for "
            "anything non-trivial. " + scratch_hint()
        )
    return (
        "POSIX shell (ls/pwd/cat/head/tail/find/grep are available). The shell already starts "
        "in the repository root: never cd anywhere. " + scratch_hint()
    )


def build_task_message(cfg: RunConfig, overview: str, notes_path: str) -> str:
    budget = cfg.budget
    editable = (
        ", ".join(cfg.editable_globs)
        if cfg.editable_globs
        else "any file except tests and test configuration"
    )
    return "\n".join(
        [
            "# Bug report",
            cfg.task.strip(),
            "",
            "# Repository",
            overview.strip() or "(no file listing available)",
            "",
            "# Environment",
            f"- Test command: {cfg.test_command}",
            f"- Each command is killed after {cfg.bash_timeout_s:.0f}s, so a command that runs "
            "longer than that tells you nothing. Some suites in a repository are far slower than "
            "the code around them (a whole-repo pytest run can take many minutes, and may try to "
            "start local servers). Run the narrow test command above instead of the entire suite.",
            f"- Shell for the command tool: {shell_hint(cfg)}",
            f"- You may edit: {editable}",
            f"- Protected (read-only) patterns: {', '.join(cfg.protected_globs)}",
            f"- Notes file (written for you, do not edit): {notes_path}",
            "",
            "# Budget",
            f"- Max steps: {budget.max_steps}",
            f"- Max wall clock: {budget.max_wall_seconds:.0f}s",
            "- The run terminates the moment the budget is exhausted, so submit as soon as the "
            "reproduction passes.",
        ]
    )
