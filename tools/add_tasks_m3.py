"""把 M3 批次的 10 条新任务并入 tasks/golden.jsonl（幂等：按 id 去重，保留原顺序）。"""

from __future__ import annotations

import json
from pathlib import Path

PY = "D:/repo-agent/.venv/Scripts/python.exe -m pytest -q"
ROOT = Path("D:/repo-agent")
GOLDEN = ROOT / "tasks" / "golden.jsonl"


def task(
    task_id: str,
    issue_file: str,
    test_command: str,
    fail_to_pass: list[str],
    pass_to_pass: list[str],
    gold: str,
    max_steps: int = 15,
) -> dict:
    return {
        "id": task_id,
        "repo": f"D:/repo-agent/.repos/{task_id}",
        "issue_file": issue_file,
        "test_command": test_command,
        "fail_to_pass": fail_to_pass,
        "pass_to_pass": pass_to_pass,
        "gold_patch": gold,
        "env": {"PYTHONPATH": "src"},
        "max_steps": max_steps,
    }


NEW: list[dict] = [
    task(
        "click-echo-empty",
        "click-echo-empty.issue.md",
        f"{PY} tests/test_utils.py",
        [f"{PY} tests/test_utils.py::test_echo_custom_file"],
        [
            f'{PY} tests/test_utils.py -k "not test_echo_custom_file"',
            f"{PY} tests/test_termui.py",
        ],
        "fixtures/click-echo-empty/gold.patch",
    ),
    task(
        "click-funcparamtype",
        "click-funcparamtype.issue.md",
        f"{PY} tests/test_types.py",
        [f"{PY} tests/test_types.py::test_func_param_type_uses_value_error_message"],
        [
            f'{PY} tests/test_types.py -k "not test_func_param_type_uses_value_error_message"',
            f"{PY} tests/test_arguments.py",
        ],
        "fixtures/click-funcparamtype/gold.patch",
    ),
    task(
        "click-show-default",
        "click-show-default.issue.md",
        f"{PY} tests/test_options.py tests/test_termui.py",
        [
            f"{PY} tests/test_options.py::test_string_show_default_shows_custom_string_in_prompt",
            f"{PY} tests/test_termui.py::test_string_show_default_shows_custom_string_in_prompt",
        ],
        [
            f'{PY} tests/test_options.py -k "not test_string_show_default_shows_custom_string_in_prompt"',
            f'{PY} tests/test_termui.py -k "not test_string_show_default_shows_custom_string_in_prompt"',
        ],
        "fixtures/click-show-default/gold.patch",
    ),
    task(
        "click-unset-defaults",
        "click-unset-defaults.issue.md",
        f"{PY} tests/test_defaults.py",
        [f"{PY} tests/test_defaults.py::test_shared_param_prefers_first_default"],
        [
            f'{PY} tests/test_defaults.py -k "not test_shared_param_prefers_first_default"',
            f"{PY} tests/test_options.py",
        ],
        "fixtures/click-unset-defaults/gold.patch",
    ),
    task(
        "packaging-wheel-regex",
        "packaging-wheel-regex.issue.md",
        f"{PY} tests/test_utils.py",
        [f"{PY} tests/test_utils.py::test_parse_wheel_invalid_filename"],
        [
            f'{PY} tests/test_utils.py -k "not test_parse_wheel_invalid_filename"',
            f"{PY} tests/test_requirements.py",
        ],
        "fixtures/packaging-wheel-regex/gold.patch",
    ),
    task(
        "packaging-tag-count",
        "packaging-tag-count.issue.md",
        f"{PY} tests/test_tags.py",
        [f"{PY} tests/test_tags.py::TestParseTag::test_invalid_component_count_raises"],
        [
            f'{PY} tests/test_tags.py -k "not test_invalid_component_count_raises"',
            f"{PY} tests/test_utils.py",
        ],
        "fixtures/packaging-tag-count/gold.patch",
    ),
    task(
        "packaging-dep-groups",
        "packaging-dep-groups.issue.md",
        f"{PY} tests/test_dependency_groups.py",
        [
            f"{PY} tests/test_dependency_groups.py"
            "::test_resolution_collects_invalid_requirement_with_sibling_errors"
        ],
        [
            f'{PY} tests/test_dependency_groups.py -k "not test_resolution_collects_invalid_requirement_with_sibling_errors"',
            f"{PY} tests/test_requirements.py",
        ],
        "fixtures/packaging-dep-groups/gold.patch",
    ),
    task(
        "werkzeug-range-zero",
        "werkzeug-range-zero.issue.md",
        f"{PY} tests/test_http.py",
        [f"{PY} tests/test_http.py::TestRange::test_range_parsing"],
        [
            f'{PY} tests/test_http.py -k "not test_range_parsing"',
            f"{PY} tests/test_datastructures.py",
        ],
        "fixtures/werkzeug-range-zero/gold.patch",
    ),
    task(
        "werkzeug-if-range-etag",
        "werkzeug-if-range-etag.issue.md",
        f"{PY} tests/test_http.py",
        [f"{PY} tests/test_http.py::TestRange::test_if_range_parsing"],
        [
            f'{PY} tests/test_http.py -k "not test_if_range_parsing"',
            f"{PY} tests/test_datastructures.py",
        ],
        "fixtures/werkzeug-if-range-etag/gold.patch",
    ),
    task(
        "werkzeug-int-url",
        "werkzeug-int-url.issue.md",
        f"{PY} tests/test_routing.py",
        [f"{PY} tests/test_routing.py::test_int_converter_404"],
        [
            f'{PY} tests/test_routing.py -k "not test_int_converter_404"',
            f"{PY} tests/test_http.py",
        ],
        "fixtures/werkzeug-int-url/gold.patch",
        max_steps=20,
    ),
]

# Provenance that must never reappear in the issue text; enforced by harness.run_eval
# before anything is cloned. Sha prefixes first, then the upstream commit subject.
LEAK_TERMS: dict[str, list[str]] = {
    "click-echo-empty": ["4d3db84", "handle empty bytes in echo"],
    "click-funcparamtype": ["fc6c7c4", "3211"],
    "click-show-default": ["607316f", "Support show_default string in prompts"],
    "click-unset-defaults": ["1c20dc6", "defer UNSET normalization"],
    "packaging-wheel-regex": ["8af7590"],
    "packaging-tag-count": ["f0620a9"],
    "packaging-dep-groups": ["30824d9"],
    "werkzeug-range-zero": ["0c419f95", "0c419f9", "reject zero-length suffix"],
    "werkzeug-if-range-etag": ["8e9105fb", "8e9105f", "discard weak etag"],
    "werkzeug-int-url": ["ab16e62d", "ab16e62", "validate host port"],
}

for _row in NEW:
    _row["leak_terms"] = LEAK_TERMS.get(_row["id"], [])


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
    for row in existing:
        print(f"  {row['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
