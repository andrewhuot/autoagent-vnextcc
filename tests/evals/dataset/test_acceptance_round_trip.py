"""Slice A acceptance — end-to-end CLI round-trip for the golden fixture.

Invariant: for the canonical 20-case golden JSONL,
    import  ->  (YAML on disk)  ->  export     ==   original bytes

The test drives the shipped `agentlab eval dataset` CLI through `CliRunner`
so a wiring bug in the YAML intermediate fails here even if the library-level
byte-identity test still passes.
"""
from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from runner import cli

GOLDEN_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "golden_cases.jsonl"
)


# ---------------------------------------------------------------------------
# test_jsonl_round_trip_bit_identical_via_cli
# ---------------------------------------------------------------------------


def test_jsonl_round_trip_bit_identical_via_cli(tmp_path: Path) -> None:
    """JSONL -> YAML (import) -> JSONL (export) must match golden bytes exactly."""
    golden_bytes = GOLDEN_PATH.read_bytes()
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()

    runner = CliRunner()

    import_result = runner.invoke(
        cli,
        [
            "eval", "dataset", "import",
            str(GOLDEN_PATH),
            "--output", str(cases_dir),
            "--dataset-name", "roundtrip",
        ],
    )
    assert import_result.exit_code == 0, import_result.output
    assert (cases_dir / "roundtrip.yaml").exists()

    out_path = tmp_path / "out.jsonl"
    export_result = runner.invoke(
        cli,
        [
            "eval", "dataset", "export",
            str(out_path),
            "--source", str(cases_dir),
        ],
    )
    assert export_result.exit_code == 0, export_result.output

    exported_bytes = out_path.read_bytes()
    if exported_bytes != golden_bytes:
        # Surface the first diverging line to make debugging fast.
        golden_lines = golden_bytes.splitlines()
        exported_lines = exported_bytes.splitlines()
        diff_idx = next(
            (
                i
                for i in range(min(len(golden_lines), len(exported_lines)))
                if golden_lines[i] != exported_lines[i]
            ),
            None,
        )
        detail = (
            f"first diff at line {diff_idx}:\n"
            f"  golden:   {golden_lines[diff_idx] if diff_idx is not None else '(length mismatch)'!r}\n"
            f"  exported: {exported_lines[diff_idx] if diff_idx is not None else '(length mismatch)'!r}"
        )
        raise AssertionError(
            "CLI round-trip JSONL does not match golden bytes.\n" + detail
        )
    assert exported_bytes == golden_bytes

    # Non-ASCII row g04 is the canary for unicode-safe YAML write/read.
    non_ascii_line = (
        b'{"category": "general", "expected_behavior": "answer", '
        b'"expected_keywords": ["h\xc3\xa9llo"], "expected_specialist": "support", '
        b'"expected_tool": null, "id": "g04", "reference_answer": "h\xc3\xa9llo!", '
        b'"safety_probe": false, "split": null, "tags": ["general"], '
        b'"user_message": "h\xc3\xa9llo \xe4\xb8\x96\xe7\x95\x8c"}'
    )
    assert non_ascii_line in exported_bytes


# ---------------------------------------------------------------------------
# Sanity tests
# ---------------------------------------------------------------------------


def test_csv_round_trip_semantic_via_cli(tmp_path: Path) -> None:
    """CSV export from the imported YAML must semantically match the golden JSONL."""
    from evals.dataset import load_csv, load_jsonl

    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    runner = CliRunner()

    r1 = runner.invoke(
        cli,
        [
            "eval", "dataset", "import",
            str(GOLDEN_PATH),
            "--output", str(cases_dir),
            "--dataset-name", "roundtrip",
        ],
    )
    assert r1.exit_code == 0, r1.output

    out_csv = tmp_path / "out.csv"
    r2 = runner.invoke(
        cli,
        [
            "eval", "dataset", "export",
            str(out_csv),
            "--source", str(cases_dir),
        ],
    )
    assert r2.exit_code == 0, r2.output

    originals = load_jsonl(GOLDEN_PATH)
    reloaded = load_csv(out_csv)
    assert len(reloaded) == len(originals) == 20

    for original, loaded in zip(originals, reloaded, strict=True):
        assert original.id == loaded.id
        assert original.category == loaded.category
        assert original.user_message == loaded.user_message
        assert original.expected_specialist == loaded.expected_specialist
        assert original.expected_behavior == loaded.expected_behavior
        assert original.safety_probe == loaded.safety_probe
        assert original.expected_keywords == loaded.expected_keywords
        assert original.expected_tool == loaded.expected_tool
        assert original.split == loaded.split
        assert original.reference_answer == loaded.reference_answer
        # tags may be re-ordered by exporter canonicalization.
        assert sorted(original.tags) == sorted(loaded.tags)


def test_round_trip_preserves_case_count(tmp_path: Path) -> None:
    """After CLI import->export, the case count is exactly 20."""
    cases_dir = tmp_path / "cases"
    cases_dir.mkdir()
    runner = CliRunner()

    r1 = runner.invoke(
        cli,
        [
            "eval", "dataset", "import",
            str(GOLDEN_PATH),
            "--output", str(cases_dir),
            "--dataset-name", "roundtrip",
        ],
    )
    assert r1.exit_code == 0, r1.output
    assert "Imported 20 cases" in r1.output

    out_path = tmp_path / "out.jsonl"
    r2 = runner.invoke(
        cli,
        [
            "eval", "dataset", "export",
            str(out_path),
            "--source", str(cases_dir),
        ],
    )
    assert r2.exit_code == 0, r2.output
    assert "Exported 20 cases" in r2.output

    lines = [ln for ln in out_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 20
