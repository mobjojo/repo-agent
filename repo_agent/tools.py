"""The tool surface handed to the model, plus the guards around every call."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .config import RunConfig
from .guard import Guard, GuardError
from .sandbox import Sandbox

MAX_VIEW_LINES = 400
MAX_DIFF_SNIPPET_LINES = 60


def read_text(path: Path) -> tuple[str, str]:
    """Return (text normalised to \\n, the file's own line separator).

    Reading with universal newlines makes model-supplied snippets match regardless of the
    file's line endings; remembering the separator lets us write the file back byte-faithfully.
    """
    raw = path.open("r", encoding="utf-8", errors="replace", newline="").read()
    separator = "\r\n" if "\r\n" in raw else "\n"
    return raw.replace("\r\n", "\n"), separator


def write_text(path: Path, text: str, separator: str = "\n") -> None:
    """Write with an explicit newline policy.

    ``Path.write_text`` translates \\n to os.linesep on Windows, which rewrites every line of
    a checked-out file and turns a one-line fix into a whole-file diff.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline=separator) as handle:
        handle.write(text)


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "view",
            "description": (
                "Read a file from the repository with 1-based line numbers. "
                "Use start_line/end_line to page through large files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Repository-relative path."},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_file",
            "description": "Create a new file. Fails if the path already exists.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "replace_in_file",
            "description": (
                "Replace an exact snippet with new text. The snippet must match exactly once, "
                "so include enough surrounding context to make it unique."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old": {"type": "string", "description": "Exact existing text."},
                    "new": {"type": "string", "description": "Replacement text."},
                },
                "required": ["path", "old", "new"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "insert_lines",
            "description": (
                "Insert text at a 1-based line position, pushing existing lines down. "
                "line=1 inserts at the top; line=total_lines+1 appends."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "line": {"type": "integer"},
                    "text": {"type": "string"},
                },
                "required": ["path", "line", "text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": (
                "Run a shell command in the sandbox, rooted at the repository. "
                "Use it to reproduce the bug, inspect history and, above all, run the tests. "
                "Output is truncated, so prefer targeted commands over dumping whole logs."
            ),
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit",
            "description": (
                "Declare the task finished. Only call this once the reproduction command "
                "actually passes on the current working tree."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "What the root cause was and what you changed.",
                    }
                },
                "required": ["summary"],
            },
        },
    },
]


@dataclass(slots=True)
class ToolOutcome:
    content: str
    ok: bool = True
    submitted: bool = False


class WorkspaceTools:
    """Implements the tool surface against a sandbox plus a :class:`Guard`."""

    def __init__(self, cfg: RunConfig, sandbox: Sandbox, guard: Guard) -> None:
        self.cfg = cfg
        self.sandbox = sandbox
        self.guard = guard

    # -- dispatch ---------------------------------------------------------

    def dispatch(self, name: str, args: dict[str, Any]) -> ToolOutcome:
        handler: Callable[[dict[str, Any]], ToolOutcome] | None = {
            "view": self._view,
            "create_file": self._create_file,
            "replace_in_file": self._replace_in_file,
            "insert_lines": self._insert_lines,
            "bash": self._bash,
            "submit": self._submit,
        }.get(name)
        if handler is None:
            return ToolOutcome(f"error: unknown tool {name!r}", ok=False)
        try:
            return handler(args or {})
        except GuardError as exc:
            return ToolOutcome(f"rejected: {exc}", ok=False)
        except Exception as exc:  # keep the loop alive, surface the failure
            return ToolOutcome(f"error: {type(exc).__name__}: {exc}", ok=False)

    # -- tools ------------------------------------------------------------

    def _view(self, args: dict[str, Any]) -> ToolOutcome:
        rel = self.guard.check_read(str(args.get("path", "")))
        target = self.guard.absolute(rel)
        if not target.is_file():
            return ToolOutcome(f"error: {rel} is not a file", ok=False)
        text, _ = read_text(target)
        lines = text.splitlines()
        total = len(lines)
        if total == 0:
            return ToolOutcome(f"{rel} (empty file)")
        start = max(1, int(args.get("start_line") or 1))
        end = int(args.get("end_line") or min(total, start + MAX_VIEW_LINES - 1))
        end = min(max(end, start), total, start + MAX_VIEW_LINES - 1)
        width = len(str(end))
        body = "\n".join(f"{i:>{width}} | {lines[i - 1]}" for i in range(start, end + 1))
        tail = "" if end >= total else f"\n[{total - end} more lines; page with start_line/end_line]"
        return ToolOutcome(f"{rel} (lines {start}-{end} of {total})\n{body}{tail}")

    def _create_file(self, args: dict[str, Any]) -> ToolOutcome:
        rel = self.guard.check_write(str(args.get("path", "")))
        content = str(args.get("content", ""))
        self._check_size(rel, content)
        target = self.guard.absolute(rel)
        if target.exists():
            return ToolOutcome(
                f"error: {rel} already exists; use replace_in_file or insert_lines", ok=False
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        write_text(target, content)
        return ToolOutcome(f"created {rel} ({len(content)} chars)")

    def _replace_in_file(self, args: dict[str, Any]) -> ToolOutcome:
        rel = self.guard.check_write(str(args.get("path", "")))
        old = str(args.get("old", ""))
        new = str(args.get("new", ""))
        if not old:
            return ToolOutcome("error: 'old' must not be empty", ok=False)
        target = self.guard.absolute(rel)
        if not target.is_file():
            return ToolOutcome(f"error: {rel} does not exist", ok=False)
        text, separator = read_text(target)
        count = text.count(old)
        if count == 0:
            return ToolOutcome(
                f"error: the 'old' snippet was not found in {rel}. Re-read the file and copy "
                "the text exactly, including indentation.",
                ok=False,
            )
        if count > 1:
            return ToolOutcome(
                f"error: the 'old' snippet matches {count} times in {rel}. Add surrounding "
                "context so it is unique.",
                ok=False,
            )
        updated = text.replace(old, new, 1)
        self._check_size(rel, updated)
        write_text(target, updated, separator)
        return ToolOutcome(f"updated {rel}\n{self._snippet(text, updated, rel)}")

    def _insert_lines(self, args: dict[str, Any]) -> ToolOutcome:
        rel = self.guard.check_write(str(args.get("path", "")))
        target = self.guard.absolute(rel)
        text, separator = read_text(target) if target.is_file() else ("", "\n")
        lines = text.splitlines()
        line = int(args.get("line") or 0)
        if line < 1 or line > len(lines) + 1:
            return ToolOutcome(
                f"error: line {line} is out of range for {rel} ({len(lines)} lines)", ok=False
            )
        payload = str(args.get("text", "")).splitlines()
        updated_lines = lines[: line - 1] + payload + lines[line - 1 :]
        updated = "\n".join(updated_lines)
        if text.endswith("\n") or not text:
            updated += "\n"
        self._check_size(rel, updated)
        write_text(target, updated, separator)
        return ToolOutcome(f"inserted {len(payload)} line(s) into {rel} at line {line}")

    def _bash(self, args: dict[str, Any]) -> ToolOutcome:
        command = str(args.get("command", "")).strip()
        if not command:
            return ToolOutcome("error: empty command", ok=False)
        result = self.sandbox.run(command, timeout=self.cfg.bash_timeout_s)
        return ToolOutcome(result.render(), ok=result.exit_code == 0)

    def _submit(self, args: dict[str, Any]) -> ToolOutcome:
        summary = str(args.get("summary", "")).strip() or "(no summary given)"
        return ToolOutcome(f"submitted: {summary}", submitted=True)

    # -- helpers ----------------------------------------------------------

    def _check_size(self, rel: str, content: str) -> None:
        if len(content.encode("utf-8")) > self.cfg.max_file_bytes:
            raise GuardError(
                f"refusing to write {len(content)} chars to {rel}: over the "
                f"{self.cfg.max_file_bytes} byte limit"
            )

    @staticmethod
    def _snippet(before: str, after: str, rel: str) -> str:
        diff = list(
            difflib.unified_diff(
                before.splitlines(), after.splitlines(), fromfile=rel, tofile=rel, lineterm="", n=2
            )
        )
        body = "\n".join(diff[:MAX_DIFF_SNIPPET_LINES])
        if len(diff) > MAX_DIFF_SNIPPET_LINES:
            body += "\n... (diff truncated)"
        return body
