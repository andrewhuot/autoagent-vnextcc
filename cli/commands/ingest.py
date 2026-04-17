"""`agentlab eval ingest --from-traces` — turn production traces into eval cases.

Wraps :class:`evals.trace_converter.TraceToEvalConverter` with the **mandatory**
PII-redaction flow specified in R5 §1.8. Redaction is never optional:

- If the traces contain PII, consent is required before writing output.
- ``--yes`` accepts in scripts / CI.
- An interactive TTY triggers a ``[y/N]`` prompt (default No).
- A non-interactive invocation without ``--yes`` aborts with exit code 20.

The contract: no pass-through mode, no ``--no-redact`` flag, every string
field of every case is rewritten in place before the YAML is written.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import click
import yaml

from evals.dataset.redact import PIIKind, redact, scan
from evals.trace_converter import TraceToEvalConverter


_DEFAULT_OUTPUT = "evals/cases/ingested_traces.yaml"

# Exit code contract — mirrors the R5 plan §3 row C.4.
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_REDACTION_REFUSED = 20


def _read_traces_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file into a list of trace dicts.

    Blank lines are skipped. Malformed JSON raises a ``click.ClickException``
    with the 1-indexed line number so the user can fix their input.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise click.ClickException(f"Traces file not found: {path}") from exc

    traces: list[dict[str, Any]] = []
    for i, line in enumerate(raw.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise click.ClickException(
                f"Malformed JSON on line {i} of {path}: {exc.msg}"
            ) from exc
        if not isinstance(obj, dict):
            raise click.ClickException(
                f"Line {i} of {path}: expected a JSON object, got {type(obj).__name__}"
            )
        traces.append(obj)
    return traces


def _scan_value(value: Any, counts: dict[PIIKind, int]) -> None:
    """Recursively walk *value* and tally :class:`PIIKind` hits into *counts*."""
    if isinstance(value, str):
        for hit in scan(value):
            counts[hit.kind] = counts.get(hit.kind, 0) + 1
    elif isinstance(value, list):
        for v in value:
            _scan_value(v, counts)
    elif isinstance(value, dict):
        for v in value.values():
            _scan_value(v, counts)


def _aggregate_pii(
    cases: list[dict[str, Any]],
) -> tuple[dict[PIIKind, int], dict[PIIKind, int]]:
    """Return ``(total_hits_per_kind, cases_with_any_hit_per_kind)``.

    Walks strings nested inside lists and dicts so no string leaf is
    missed — ``expected_keywords`` and ``metadata`` would otherwise slip
    through ``scan_case``, which is top-level-only by design.
    """
    total: dict[PIIKind, int] = {}
    per_case: dict[PIIKind, int] = {}
    for case in cases:
        case_counts: dict[PIIKind, int] = {}
        _scan_value(case, case_counts)
        for kind, n in case_counts.items():
            total[kind] = total.get(kind, 0) + n
            per_case[kind] = per_case.get(kind, 0) + 1
    return total, per_case


def _print_redaction_summary(
    total: dict[PIIKind, int],
    per_case: dict[PIIKind, int],
) -> None:
    """Emit the human-readable summary block described in the plan."""
    click.echo("Redaction summary:")
    if not total:
        click.echo("  (no PII detected)")
    else:
        # Sort kinds by name for deterministic output.
        for kind in sorted(total.keys(), key=lambda k: k.value):
            n_hits = total[kind]
            n_cases = per_case.get(kind, 0)
            click.echo(
                f"  {kind.value}: {n_hits} hits across {n_cases} cases"
            )
    click.echo("")
    click.echo("Redaction applies the following substitution: <REDACTED:KIND>.")
    click.echo("All original text is overwritten. There is no pass-through mode.")


def _redact_value(value: Any) -> Any:
    """Recursively redact string leaves inside lists and dicts.

    Keeps the outer shape intact — only strings are rewritten. Booleans are
    not strings here; Python's ``isinstance(True, str)`` is False.
    """
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [_redact_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _redact_value(v) for k, v in value.items()}
    return value


def _redact_case_in_place(case: dict[str, Any]) -> None:
    """Apply :func:`redact` to every string found in *case*, including those
    nested inside lists or dicts (e.g. ``expected_keywords``, ``metadata``).

    Mutates *case* directly. Non-string leaves (numbers, bools, ``None``) are
    left alone so callers can rely on the surviving shape matching
    ``TraceToEvalConverter.convert``'s output.
    """
    for key, value in list(case.items()):
        case[key] = _redact_value(value)


def _case_dict_to_yaml_entry(case: dict[str, Any]) -> dict[str, Any]:
    """Map a converter-shaped case dict to the ``_load_cases_from_dir`` shape.

    The converter uses ``case_id``; the YAML loader expects ``id``. We also
    drop keys that aren't part of :class:`TestCase` to keep output minimal,
    while preserving ``metadata`` (and other converter-specific fields) so
    downstream tooling can still trace back to the source trace.
    """
    entry: dict[str, Any] = {
        "id": case.get("case_id", ""),
        "category": case.get("category", "trace_derived"),
        "user_message": case.get("task", ""),
        "expected_specialist": case.get("expected_specialist") or "",
        "expected_behavior": case.get("expected_behavior", "answer"),
        "safety_probe": False,
        "expected_keywords": list(case.get("expected_keywords") or []),
        "reference_answer": case.get("reference_answer", "") or "",
        "tags": list((case.get("metadata") or {}).get("tags") or []),
    }
    if case.get("expected_tool") is not None:
        entry["expected_tool"] = case["expected_tool"]
    if case.get("split") is not None:
        entry["split"] = case["split"]
    return entry


def _is_interactive() -> bool:
    """TTY detection, wrapped so tests can monkeypatch a single symbol.

    ``CliRunner`` swaps ``sys.stdin`` for a ``StringIO`` after any test-level
    ``monkeypatch.setattr('sys.stdin.isatty', ...)`` takes effect, so patching
    the stdlib attribute doesn't survive into command execution. Exposing this
    helper at module scope gives tests a stable patch target.
    """
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def _consent_or_abort(has_pii: bool, yes: bool) -> None:
    """Gate writing on explicit redaction consent.

    Policy (§1.8):

    - No PII → proceed silently.
    - ``--yes`` → proceed.
    - Interactive TTY → prompt, default No.
    - Non-interactive without ``--yes`` → abort with exit code 20.
    """
    if not has_pii or yes:
        return

    if _is_interactive():
        # click.confirm returns the boolean; default=False means "N".
        if click.confirm("Proceed with redaction?", default=False):
            return
        click.echo("Aborted.", err=True)
        sys.exit(EXIT_REDACTION_REFUSED)

    # Non-interactive and no --yes: refuse hard.
    click.echo(
        "Non-interactive run requires --yes to approve redaction.",
        err=True,
    )
    sys.exit(EXIT_REDACTION_REFUSED)


def register_ingest_command(eval_group: click.Group) -> None:
    """Attach `agentlab eval ingest` to *eval_group*."""

    @eval_group.command("ingest")
    @click.option(
        "--from-traces",
        "from_traces",
        required=True,
        type=click.Path(),
        help="Path to a JSONL file of production traces.",
    )
    @click.option(
        "--output",
        default=_DEFAULT_OUTPUT,
        show_default=True,
        type=click.Path(),
        help="Destination YAML path for the ingested cases.",
    )
    @click.option(
        "--yes",
        is_flag=True,
        default=False,
        help="Auto-accept the redaction summary. Required for non-interactive runs.",
    )
    @click.option(
        "--max-cases",
        default=30,
        show_default=True,
        type=click.IntRange(min=1),
        help="Cap on the number of traces to convert.",
    )
    @click.option(
        "--expected-output",
        default=None,
        help="Override the expected output field for every converted case.",
    )
    @click.option(
        "--force",
        is_flag=True,
        default=False,
        help="Overwrite the output YAML if it already exists.",
    )
    def eval_ingest(
        from_traces: str,
        output: str,
        yes: bool,
        max_cases: int,
        expected_output: str | None,
        force: bool,
    ) -> None:
        """Convert production JSONL traces into eval YAML cases.

        Redaction is mandatory. Non-interactive runs without --yes exit 20.

        Examples:
          agentlab eval ingest --from-traces traces.jsonl
          agentlab eval ingest --from-traces traces.jsonl --yes
          agentlab eval ingest --from-traces traces.jsonl --max-cases 10 --force
        """
        src = Path(from_traces)
        out = Path(output)

        # A.6 pattern: refuse to clobber without --force.
        if out.exists() and not force:
            raise click.ClickException(
                f"Refusing to overwrite existing file: {out} (pass --force to replace)."
            )

        traces = _read_traces_jsonl(src)

        converter = TraceToEvalConverter()
        converted: list[dict[str, Any]] = []
        for trace in traces[:max_cases]:
            converted.append(
                converter.convert(trace, expected_output=expected_output)
            )

        total, per_case = _aggregate_pii(converted)
        has_pii = bool(total)
        _print_redaction_summary(total, per_case)

        _consent_or_abort(has_pii=has_pii, yes=yes)

        # Apply redaction to every string field of every case before writing.
        for case in converted:
            _redact_case_in_place(case)

        entries = [_case_dict_to_yaml_entry(c) for c in converted]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            yaml.safe_dump(
                {"cases": entries},
                sort_keys=False,
                default_flow_style=False,
            ),
            encoding="utf-8",
        )
        click.echo(f"Wrote {len(entries)} redacted cases to {out}.")
