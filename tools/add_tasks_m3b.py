"""把 M3 第二批 7 条任务并入 tasks/golden.jsonl（幂等：按 id 更新或追加）。"""

from __future__ import annotations

import json
from pathlib import Path

PY = "D:/repo-agent/.venv/Scripts/python.exe -m pytest -q"
GOLDEN = Path("D:/repo-agent/tasks/golden.jsonl")


def task(
    task_id: str,
    test_command: str,
    fail_to_pass: list[str],
    pass_to_pass: list[str],
    leak_terms: list[str],
    max_steps: int = 15,
) -> dict:
    return {
        "id": task_id,
        "repo": f"D:/repo-agent/.repos/{task_id}",
        "issue_file": f"{task_id}.issue.md",
        "test_command": test_command,
        "fail_to_pass": fail_to_pass,
        "pass_to_pass": pass_to_pass,
        "gold_patch": f"fixtures/{task_id}/gold.patch",
        "leak_terms": leak_terms,
        "env": {"PYTHONPATH": "src"},
        "max_steps": max_steps,
    }


NEW: list[dict] = [
    task(
        "packaging-interp-tags",
        f"{PY} tests/test_tags.py tests/test_utils.py",
        [
            f"{PY} tests/test_tags.py::TestParseTag::test_invalid_interpreter_raises",
            f"{PY} tests/test_utils.py::test_parse_wheel_invalid_filename",
        ],
        [
            f'{PY} tests/test_tags.py -k "not test_invalid_interpreter_raises"',
            f'{PY} tests/test_utils.py -k "not test_parse_wheel_invalid_filename"',
        ],
        ["26fa1d42", "1351"],
    ),
    task(
        "packaging-specifier-group",
        f"{PY} tests/test_specifiers.py",
        [f"{PY} tests/test_specifiers.py::TestSpecifier::test_specifiers_invalid"],
        [
            f'{PY} tests/test_specifiers.py -k "not test_specifiers_invalid"',
            f"{PY} tests/test_requirements.py",
        ],
        ["f14a0933", "1384"],
    ),
    task(
        "werkzeug-int-str-strict",
        f"{PY} tests/test_internal.py",
        [f"{PY} tests/test_internal.py::test_plain_int"],
        [
            f'{PY} tests/test_internal.py -k "not test_plain_int"',
            f"{PY} tests/test_http.py",
        ],
        ["b9761b5b"],
    ),
    task(
        "werkzeug-route-sort",
        f"{PY} tests/test_routing.py",
        [f"{PY} tests/test_routing.py::test_part_converter_order"],
        [
            f'{PY} tests/test_routing.py -k "not test_part_converter_order"',
            f"{PY} tests/test_http.py",
        ],
        ["6d7c0b4e"],
    ),
    task(
        "werkzeug-url-empty-port",
        f"{PY} tests/test_urls.py",
        [
            f"{PY} tests/test_urls.py::test_uri_empty_auth",
            f"{PY} tests/test_urls.py::test_uri_port_0",
        ],
        [
            f'{PY} tests/test_urls.py -k "not test_uri_empty_auth and not test_uri_port_0"',
            f"{PY} tests/test_http.py",
        ],
        ["4da3786f"],
    ),
    task(
        "click-deprecated-label",
        f"{PY} tests/test_commands.py tests/test_options.py",
        [
            f"{PY} tests/test_commands.py::test_deprecated_empty_help_no_leading_space",
            f"{PY} tests/test_options.py::test_deprecated_empty_help_no_leading_space",
        ],
        [
            f'{PY} tests/test_commands.py -k "not test_deprecated_empty_help_no_leading_space"',
            f'{PY} tests/test_options.py -k "not test_deprecated_empty_help_no_leading_space"',
        ],
        ["82f377c5"],
    ),
    task(
        "itsdangerous-tz-aware",
        f"{PY} tests/test_itsdangerous/test_timed.py",
        [f"{PY} tests/test_itsdangerous/test_timed.py"],
        [
            f"{PY} tests/test_itsdangerous/test_signer.py",
            f"{PY} tests/test_itsdangerous/test_serializer.py",
        ],
        ["910a7a94"],
        max_steps=20,
    ),
]


def main() -> int:
    existing = [
        json.loads(line)
        for line in GOLDEN.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_id = {row["id"]: row for row in existing}
    added = 0
    for row in NEW:
        if row["id"] in by_id:
            by_id[row["id"]].update(row)
        else:
            existing.append(row)
            by_id[row["id"]] = row
            added += 1
    GOLDEN.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in existing) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"tasks: {len(existing)} (added {added})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
