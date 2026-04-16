"""JSONL importer for eval cases.

Free-function entry point; returns ``list[TestCase]``. No ``Dataset`` class.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evals.runner import TestCase

_REQUIRED_FIELDS: tuple[str, ...] = ("id", "category", "user_message")


def load_jsonl(path: str | Path) -> list[TestCase]:
    """Load eval cases from a JSONL file, one case per line.

    Each non-blank, non-comment line must be a JSON object with at least the
    required keys: ``id``, ``category``, ``user_message``. Optional keys:
    ``expected_specialist`` (default ``"support"``), ``expected_behavior``
    (default ``"answer"``), ``safety_probe`` (default ``False``),
    ``expected_keywords`` (default ``[]``), ``expected_tool`` (default
    ``None``), ``split`` (default ``None``), ``reference_answer`` (default
    ``""``), ``tags`` (default ``[category]`` when missing or empty).

    Blank lines and lines whose first non-whitespace character is ``#`` are
    silently skipped — this is a convenience, not a supported comment syntax.

    Raises:
        ValueError: If any line has malformed JSON or is missing a required
            field. The error message includes the 1-indexed line number.
    """
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")

    cases: list[TestCase] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        try:
            row = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Malformed JSON on line {line_number} of {file_path}: {exc.msg}"
            ) from exc

        if not isinstance(row, dict):
            raise ValueError(
                f"Line {line_number} of {file_path} is not a JSON object"
            )

        for field_name in _REQUIRED_FIELDS:
            if field_name not in row:
                raise ValueError(
                    f"Missing required field '{field_name}' on line {line_number} of {file_path}"
                )

        cases.append(_row_to_testcase(row))

    return cases


def _row_to_testcase(row: dict[str, Any]) -> TestCase:
    """Materialize a JSONL row dict into a TestCase with spec'd defaults."""
    category = str(row["category"])

    raw_tags = row.get("tags")
    if isinstance(raw_tags, list) and raw_tags:
        tags = [str(tag) for tag in raw_tags]
    else:
        tags = [category]

    expected_keywords_raw = row.get("expected_keywords", [])
    if isinstance(expected_keywords_raw, list):
        expected_keywords = [str(item) for item in expected_keywords_raw]
    else:
        expected_keywords = []

    expected_tool_raw = row.get("expected_tool")
    expected_tool = str(expected_tool_raw) if expected_tool_raw else None

    split_raw = row.get("split")
    split = str(split_raw) if split_raw else None

    return TestCase(
        id=str(row["id"]),
        category=category,
        user_message=str(row["user_message"]),
        expected_specialist=str(row.get("expected_specialist", "support")),
        expected_behavior=str(row.get("expected_behavior", "answer")),
        safety_probe=bool(row.get("safety_probe", False)),
        expected_keywords=expected_keywords,
        expected_tool=expected_tool,
        split=split,
        reference_answer=str(row.get("reference_answer", "")),
        tags=tags,
    )
