"""JSONL, CSV, and HuggingFace importers for eval cases.

Free-function entry points; each returns ``list[TestCase]``. No ``Dataset`` class.
"""

from __future__ import annotations

import csv
import importlib
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


def load_csv(path: str | Path) -> list[TestCase]:
    """Load eval cases from a CSV file with a required header row.

    Column names correspond to the JSONL keys (see :func:`load_jsonl`).
    Required columns: ``id``, ``category``, ``user_message``. Other columns
    are optional — an empty/whitespace cell means "use the JSONL default."

    ``expected_keywords`` and ``tags`` cells are **pipe-delimited** strings,
    e.g. ``"order|tracking"`` → ``["order", "tracking"]``. An empty string
    means an empty list; ``tags`` then falls back to ``[category]`` per the
    A.1 contract. ``safety_probe`` is ``"true"``/``"false"``
    (case-insensitive); any other non-empty value raises ``ValueError``.

    Raises:
        ValueError: If the file has no header row, if required column
            headers are missing, if a required value is empty in a data row
            (message names the field and the 1-indexed data-row number), or
            if ``safety_probe`` contains an invalid boolean literal.
    """
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")

    reader = csv.reader(text.splitlines())
    try:
        header = next(reader)
    except StopIteration:
        raise ValueError(f"CSV has no header row in {file_path}") from None

    missing_headers = [f for f in _REQUIRED_FIELDS if f not in header]
    if missing_headers:
        raise ValueError(
            f"CSV {file_path} is missing required column(s): "
            f"{', '.join(missing_headers)}"
        )

    cases: list[TestCase] = []
    for data_row_number, raw_row in enumerate(reader, start=1):
        # Pad short rows with empty strings so zip doesn't truncate.
        padded = list(raw_row) + [""] * (len(header) - len(raw_row))
        row = dict(zip(header, padded))

        for field_name in _REQUIRED_FIELDS:
            if not row.get(field_name, "").strip():
                raise ValueError(
                    f"Missing required value for '{field_name}' on data row "
                    f"{data_row_number} of {file_path}"
                )

        cases.append(_csv_row_to_testcase(row, data_row_number, file_path))

    return cases


def _load_hf_dataset(
    name: str, split: str, cache_dir: str | Path | None
) -> Any:
    """Single seam for tests to monkeypatch — lazy-imports ``datasets``.

    Delegates to :func:`datasets.load_dataset`. Kept deliberately thin so the
    public loader can intercept both the optional-import failure and any
    network/auth error from the call in one place.
    """
    datasets_mod = importlib.import_module("datasets")
    return datasets_mod.load_dataset(name, split=split, cache_dir=cache_dir)


def load_huggingface(
    name: str,
    split: str = "train",
    cache_dir: str | Path | None = None,
    column_mapping: dict[str, str] | None = None,
) -> list[TestCase]:
    """Load eval cases from a HuggingFace dataset.

    Uses the ``datasets`` library when available. Rows are mapped into
    :class:`TestCase` via ``column_mapping`` (HF column name -> TestCase
    field name). Columns not present in the mapping are passed through
    unchanged; required ``TestCase`` fields (``id``, ``category``,
    ``user_message``) must be produced by the mapping or already match
    existing HF columns.

    Raises:
        ImportError: If the optional ``datasets`` package is not installed.
        RuntimeError: If the dataset download fails for any reason
            (network, auth, not found). The message includes both the
            underlying exception's message and a cache-path hint.
        ValueError: If a mapped row is missing a required field; the
            message names the 0-indexed row position within the split.
    """
    try:
        raw_rows = _load_hf_dataset(name, split, cache_dir)
    except ImportError as exc:
        raise ImportError(
            "HuggingFace importer requires 'datasets'. "
            "Install with: pip install datasets"
        ) from exc
    except Exception as exc:
        hint_path = str(cache_dir) if cache_dir is not None else "default HF cache"
        raise RuntimeError(
            f"Failed to load HuggingFace dataset '{name}' (split={split!r}): "
            f"{exc}. Check the cache at {hint_path}."
        ) from exc

    mapping = column_mapping or {}

    cases: list[TestCase] = []
    for row_index, raw_row in enumerate(raw_rows):
        mapped = _apply_hf_mapping(raw_row, mapping)
        for field_name in _REQUIRED_FIELDS:
            if field_name not in mapped or mapped[field_name] in (None, ""):
                raise ValueError(
                    f"Missing required field '{field_name}' on HuggingFace row "
                    f"{row_index} of dataset '{name}' (split={split!r})"
                )
        cases.append(_row_to_testcase(mapped))

    return cases


def _apply_hf_mapping(
    row: Any, mapping: dict[str, str]
) -> dict[str, Any]:
    """Rename row keys per ``mapping``; unmapped keys pass through."""
    # HF rows behave like dicts but may be Row/LazyRow — coerce to dict.
    base: dict[str, Any] = dict(row) if not isinstance(row, dict) else dict(row)
    if not mapping:
        return base

    out: dict[str, Any] = {}
    for key, value in base.items():
        dest = mapping.get(key, key)
        out[dest] = value
    return out


def _parse_csv_bool(value: str, data_row_number: int, file_path: Path) -> bool:
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(
        f"Invalid boolean '{value}' for 'safety_probe' on data row "
        f"{data_row_number} of {file_path} (expected 'true' or 'false')"
    )


def _split_pipe_list(value: str) -> list[str]:
    stripped = value.strip()
    if not stripped:
        return []
    return [part.strip() for part in stripped.split("|") if part.strip()]


def _csv_row_to_testcase(
    row: dict[str, str], data_row_number: int, file_path: Path
) -> TestCase:
    """Materialize a CSV row dict into a TestCase with spec'd defaults."""
    category = row["category"].strip()

    tags_raw = row.get("tags", "")
    tags = _split_pipe_list(tags_raw)
    if not tags:
        tags = [category]

    expected_keywords = _split_pipe_list(row.get("expected_keywords", ""))

    safety_probe_raw = row.get("safety_probe", "").strip()
    if safety_probe_raw:
        safety_probe = _parse_csv_bool(safety_probe_raw, data_row_number, file_path)
    else:
        safety_probe = False

    expected_specialist = row.get("expected_specialist", "").strip() or "support"
    expected_behavior = row.get("expected_behavior", "").strip() or "answer"

    expected_tool_raw = row.get("expected_tool", "").strip()
    expected_tool = expected_tool_raw if expected_tool_raw else None

    split_raw = row.get("split", "").strip()
    split = split_raw if split_raw else None

    reference_answer = row.get("reference_answer", "")

    return TestCase(
        id=row["id"].strip(),
        category=category,
        user_message=row["user_message"],
        expected_specialist=expected_specialist,
        expected_behavior=expected_behavior,
        safety_probe=safety_probe,
        expected_keywords=expected_keywords,
        expected_tool=expected_tool,
        split=split,
        reference_answer=reference_answer,
        tags=tags,
    )


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
