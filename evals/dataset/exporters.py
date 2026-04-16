"""JSONL and CSV exporters for eval cases.

Free-function entry points that mirror :mod:`evals.dataset.importers`. The
JSONL exporter emits a bit-stable canonical form (sorted keys, sorted tags,
one trailing newline) so the pair ``load_jsonl → export_jsonl`` is a
byte-identity round-trip against a canonical golden fixture. The CSV
exporter is semantic-only: tags get sorted alphabetically before being
pipe-joined to match the A.3 importer's re-inflation.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from evals.runner import TestCase

_CSV_COLUMNS: tuple[str, ...] = (
    "id",
    "category",
    "user_message",
    "expected_specialist",
    "expected_behavior",
    "safety_probe",
    "expected_keywords",
    "expected_tool",
    "split",
    "reference_answer",
    "tags",
)


def _validate_parent(path: Path) -> None:
    parent = path.parent
    # ``Path("foo.jsonl").parent`` is ``Path(".")`` which always exists.
    if not parent.exists():
        raise FileNotFoundError(
            f"Parent directory does not exist for output path: {parent}"
        )


def _case_to_canonical_dict(case: TestCase) -> dict:
    """Return the canonical dict form of a TestCase.

    Tags are sorted alphabetically (they are treated as an unordered set).
    ``expected_keywords`` is preserved verbatim — order matters to graders.
    All fields are emitted even when they equal the dataclass default.
    """
    return {
        "id": case.id,
        "category": case.category,
        "user_message": case.user_message,
        "expected_specialist": case.expected_specialist,
        "expected_behavior": case.expected_behavior,
        "safety_probe": bool(case.safety_probe),
        "expected_keywords": list(case.expected_keywords),
        "expected_tool": case.expected_tool,
        "split": case.split,
        "reference_answer": case.reference_answer,
        "tags": sorted(case.tags),
    }


def export_jsonl(cases: list[TestCase], path: str | Path) -> None:
    """Write ``cases`` to ``path`` as canonical JSONL.

    One JSON object per line, keys alphabetically sorted, tags alphabetically
    sorted, ``expected_keywords`` preserved in original order,
    ``ensure_ascii=False`` for clean non-ASCII round-trips. File ends with a
    single trailing newline; empty ``cases`` produces a zero-byte file.

    Raises:
        FileNotFoundError: If the parent directory of ``path`` does not
            exist.
    """
    file_path = Path(path)
    _validate_parent(file_path)

    if not cases:
        file_path.write_bytes(b"")
        return

    lines: list[str] = []
    for case in cases:
        payload = _case_to_canonical_dict(case)
        lines.append(json.dumps(payload, sort_keys=True, ensure_ascii=False))

    # Join with `\n` and append a single trailing `\n`.
    file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def export_csv(cases: list[TestCase], path: str | Path) -> None:
    """Write ``cases`` to ``path`` as CSV with the A.3 importer's column set.

    ``expected_keywords`` and ``tags`` are pipe-delimited; tags are sorted
    alphabetically before joining (matches the canonical JSONL form and
    round-trips losslessly with ``load_csv`` up to tag order).
    ``safety_probe`` is written as ``"true"``/``"false"``. ``expected_tool``
    and ``split`` are written as the empty string when ``None``. Fields are
    quoted via ``csv.QUOTE_ALL`` so embedded delimiters survive.

    Raises:
        FileNotFoundError: If the parent directory of ``path`` does not
            exist.
    """
    file_path = Path(path)
    _validate_parent(file_path)

    with file_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL)
        writer.writerow(_CSV_COLUMNS)
        for case in cases:
            writer.writerow(
                [
                    case.id,
                    case.category,
                    case.user_message,
                    case.expected_specialist,
                    case.expected_behavior,
                    "true" if case.safety_probe else "false",
                    "|".join(case.expected_keywords),
                    case.expected_tool if case.expected_tool is not None else "",
                    case.split if case.split is not None else "",
                    case.reference_answer,
                    "|".join(sorted(case.tags)),
                ]
            )
