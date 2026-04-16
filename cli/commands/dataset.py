"""`agentlab eval dataset` subcommands.

Thin wrapper over :mod:`evals.dataset.importers` / :mod:`evals.dataset.exporters`
that wires JSONL, CSV, and HuggingFace sources into the CLI. Added in R5 Slice
A.6 — the dataset subgroup is nested under the existing `eval` group.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Iterable

import click
import yaml

_DEFAULT_OUTPUT_DIR = "evals/cases"


def _infer_format(source: str) -> str:
    """Pick an importer format based on file extension.

    Returns ``"jsonl"`` for ``.jsonl``/``.ndjson`` and ``"csv"`` for ``.csv``.
    For HuggingFace datasets the caller must pass ``--format hf`` explicitly —
    we do not try to guess from the bare dataset name.
    """
    suffix = Path(source).suffix.lower()
    if suffix in (".jsonl", ".ndjson"):
        return "jsonl"
    if suffix == ".csv":
        return "csv"
    raise click.ClickException(
        f"Could not infer format from '{source}'. Pass --format jsonl|csv|hf explicitly."
    )


def _case_to_yaml_dict(case) -> dict:
    """Serialize a TestCase to the dict shape that `_load_cases_from_dir` reads."""
    entry: dict = {
        "id": case.id,
        "category": case.category,
        "user_message": case.user_message,
        "expected_specialist": case.expected_specialist,
        "expected_behavior": case.expected_behavior,
        "safety_probe": bool(case.safety_probe),
        "expected_keywords": list(case.expected_keywords),
        "reference_answer": case.reference_answer,
        "tags": list(case.tags),
    }
    if case.expected_tool is not None:
        entry["expected_tool"] = case.expected_tool
    if case.split is not None:
        entry["split"] = case.split
    return entry


def _write_cases_yaml(cases: Iterable, path: Path) -> None:
    payload = {"cases": [_case_to_yaml_dict(c) for c in cases]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


def _load_cases_with_sources(src_dir: Path):
    """Read YAML case files under *src_dir* and track each case's source file.

    Returns ``(cases, case_sources, file_order)`` where ``case_sources`` maps
    ``case.id -> Path`` and ``file_order`` is the sorted list of YAML files.
    We don't reuse ``EvalRunner.load_cases()`` because it doesn't expose
    source-file provenance, which the rewrite step needs.
    """
    from evals.runner import TestCase

    file_order = sorted(p for p in src_dir.iterdir() if p.suffix in (".yaml", ".yml"))
    cases: list = []
    case_sources: dict[str, Path] = {}
    seen_ids: set[str] = set()

    for yaml_path in file_order:
        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise click.ClickException(
                f"Failed to parse {yaml_path}: {exc}"
            ) from exc
        entries = data.get("cases") or []
        if not isinstance(entries, list):
            raise click.ClickException(
                f"{yaml_path}: 'cases' must be a list (got {type(entries).__name__})"
            )
        for entry in entries:
            if not isinstance(entry, dict) or "id" not in entry:
                raise click.ClickException(
                    f"{yaml_path}: every case must be a mapping with an 'id'"
                )
            case_id = str(entry["id"])
            if case_id in seen_ids:
                raise click.ClickException(
                    f"Duplicate case id '{case_id}' found across YAML files "
                    "(cannot dedupe with ambiguous ids)"
                )
            seen_ids.add(case_id)
            case = TestCase(
                id=case_id,
                category=str(entry.get("category", "")),
                user_message=str(entry.get("user_message", "")),
                expected_specialist=str(entry.get("expected_specialist", "")),
                expected_behavior=str(entry.get("expected_behavior", "")),
                safety_probe=bool(entry.get("safety_probe", False)),
                expected_keywords=list(entry.get("expected_keywords", []) or []),
                expected_tool=entry.get("expected_tool"),
                split=entry.get("split"),
                reference_answer=str(entry.get("reference_answer", "")),
                tags=list(entry.get("tags", []) or []),
            )
            cases.append(case)
            case_sources[case_id] = yaml_path

    return cases, case_sources, file_order


def _print_dedupe_report(report, threshold: float) -> None:
    """Print the dedupe summary as specified in the plan."""
    click.echo(f"Dedupe @ threshold={threshold}")
    click.echo(f"Kept: {len(report.kept)}")
    click.echo(f"Dropped: {len(report.dropped_ids)}")
    for kept_id, dropped_id, sim in report.dropped_pairs:
        click.echo(f"  {kept_id} \u2190 {dropped_id} (sim={sim:.3f})")


def _rewrite_source_dir(
    src_dir: Path,
    kept_cases: list,
    case_sources: dict,
    file_order: list,
) -> None:
    """Rewrite each source YAML to contain only its surviving cases.

    YAML files that end up with zero cases are deleted.
    """
    kept_ids = {c.id for c in kept_cases}
    # Group kept cases by source file, preserving each file's original order
    # (we iterate kept_cases which is already in original load order).
    by_file: dict[Path, list] = {p: [] for p in file_order}
    for case in kept_cases:
        src = case_sources.get(case.id)
        if src is None:  # pragma: no cover — defensive
            continue
        by_file.setdefault(src, []).append(case)

    for yaml_path in file_order:
        remaining = by_file.get(yaml_path, [])
        if not remaining:
            # Entire file dropped — remove it.
            if yaml_path.exists():
                yaml_path.unlink()
            continue
        _write_cases_yaml(remaining, yaml_path)
    # Sanity: every kept case must have been written somewhere.
    assert kept_ids.issubset(
        {c.id for cases in by_file.values() for c in cases}
    ), "dedupe rewrite dropped a kept case"


def register_dataset_commands(eval_group: click.Group) -> None:
    """Attach the `dataset` subgroup (import/export) to *eval_group*."""

    @eval_group.group("dataset")
    def dataset_group() -> None:
        """Import/export eval case datasets (JSONL, CSV, HuggingFace)."""

    @dataset_group.command("import")
    @click.argument("source", required=True)
    @click.option(
        "--format", "fmt",
        type=click.Choice(["auto", "jsonl", "csv", "hf"]),
        default="auto",
        show_default=True,
        help="Input format. 'auto' picks by file extension.",
    )
    @click.option(
        "--output",
        default=_DEFAULT_OUTPUT_DIR,
        show_default=True,
        help="Directory for the resulting YAML file.",
    )
    @click.option(
        "--dataset-name",
        default=None,
        help="Stem for the output YAML file. Required for --format hf; "
             "defaults to the source filename stem for jsonl/csv.",
    )
    @click.option(
        "--hf-split",
        default="train",
        show_default=True,
        help="HuggingFace split to load (when --format hf).",
    )
    @click.option(
        "--cache-dir",
        default=None,
        help="Cache directory passed through to HuggingFace loader.",
    )
    @click.option(
        "--force",
        is_flag=True,
        default=False,
        help="Overwrite the output YAML if it already exists.",
    )
    def dataset_import(
        source: str,
        fmt: str,
        output: str,
        dataset_name: str | None,
        hf_split: str,
        cache_dir: str | None,
        force: bool,
    ) -> None:
        """Import an eval dataset from JSONL, CSV, or HuggingFace into YAML.

        Examples:
          agentlab eval dataset import cases.jsonl
          agentlab eval dataset import cases.csv --output evals/cases
          agentlab eval dataset import my/hf-set --format hf --dataset-name my_cases
        """
        from evals.dataset import importers

        resolved_format = fmt
        if resolved_format == "auto":
            resolved_format = _infer_format(source)

        if resolved_format == "hf" and not dataset_name:
            raise click.ClickException(
                "--dataset-name is required when --format hf is used."
            )

        # Resolve the output YAML path.
        out_dir = Path(output)
        if dataset_name:
            stem = dataset_name
        else:
            stem = Path(source).stem
        out_path = out_dir / f"{stem}.yaml"

        if out_path.exists() and not force:
            raise click.ClickException(
                f"Refusing to overwrite existing file: {out_path} (pass --force to replace)."
            )

        try:
            if resolved_format == "jsonl":
                cases = importers.load_jsonl(source)
            elif resolved_format == "csv":
                cases = importers.load_csv(source)
            elif resolved_format == "hf":
                cases = importers.load_huggingface(
                    source, split=hf_split, cache_dir=cache_dir,
                )
            else:  # pragma: no cover — click.Choice already restricts
                raise click.ClickException(f"Unsupported format: {resolved_format}")
        except FileNotFoundError as exc:
            raise click.ClickException(f"Source not found: {exc}") from exc
        except (ValueError, ImportError, RuntimeError) as exc:
            raise click.ClickException(str(exc)) from exc

        _write_cases_yaml(cases, out_path)
        click.echo(f"Imported {len(cases)} cases from {source} \u2192 {out_path}")

    @dataset_group.command("dedupe")
    @click.option(
        "--source",
        default=_DEFAULT_OUTPUT_DIR,
        show_default=True,
        help="Directory of YAML case files to read.",
    )
    @click.option(
        "--threshold",
        type=float,
        default=0.95,
        show_default=True,
        help="Cosine similarity threshold.",
    )
    @click.option(
        "--dry-run",
        is_flag=True,
        default=False,
        help="Report drops without modifying any files.",
    )
    @click.option(
        "--output",
        default=None,
        type=click.Path(),
        help="If set, write kept cases to a single YAML at this path "
             "instead of rewriting --source.",
    )
    def dataset_dedupe(
        source: str,
        threshold: float,
        dry_run: bool,
        output: str | None,
    ) -> None:
        """Remove near-duplicate eval cases by cosine similarity.

        Examples:
          agentlab eval dataset dedupe --source evals/cases --dry-run
          agentlab eval dataset dedupe --threshold 0.9
          agentlab eval dataset dedupe --output deduped.yaml
        """
        from evals.dataset import get_default_embedder
        from evals.dataset.dedupe import dedupe as _dedupe

        src_dir = Path(source)
        if not src_dir.is_dir():
            raise click.ClickException(f"Source directory not found: {src_dir}")

        cases, case_sources, file_order = _load_cases_with_sources(src_dir)
        if not cases:
            raise click.ClickException(f"No cases found under {src_dir}")

        try:
            embedder = get_default_embedder()
        except RuntimeError as exc:
            raise click.ClickException(str(exc)) from exc

        try:
            report = _dedupe(cases, embedder, threshold=threshold)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc

        _print_dedupe_report(report, threshold)

        if dry_run:
            return

        if output:
            out_path = Path(output)
            _write_cases_yaml(report.kept, out_path)
            click.echo(f"Wrote {len(report.kept)} kept cases \u2192 {out_path}")
            return

        # Rewrite the source directory in place.
        _rewrite_source_dir(src_dir, report.kept, case_sources, file_order)

    @dataset_group.command("balance")
    @click.option(
        "--source",
        default=_DEFAULT_OUTPUT_DIR,
        show_default=True,
        help="Directory of YAML case files to read.",
    )
    @click.option(
        "--by",
        type=click.Choice(["category", "tag"]),
        default="category",
        show_default=True,
        help="Bucket key: category (disjoint) or tag (multi-bucket).",
    )
    @click.option(
        "--json",
        "json_output",
        is_flag=True,
        default=False,
        help="Emit the balance report as JSON (for scripting).",
    )
    def dataset_balance(source: str, by: str, json_output: bool) -> None:
        """Report the histogram of cases per category or per tag.

        Read-only — prints recommendations targeting the median bucket size
        but never modifies files. Use --json for a machine-readable dict with
        keys by, histogram, median, recommendations.

        Examples:
          agentlab eval dataset balance
          agentlab eval dataset balance --by tag
          agentlab eval dataset balance --json
        """
        from evals.dataset.balance import balance as _balance
        from evals.runner import EvalRunner

        src_dir = Path(source)
        if not src_dir.is_dir():
            raise click.ClickException(f"Source directory not found: {src_dir}")

        eval_runner = EvalRunner(cases_dir=source)
        cases = eval_runner.load_cases()
        if not cases:
            raise click.ClickException(f"No cases found under {src_dir}")

        report = _balance(cases, by=by)

        if json_output:
            click.echo(
                json.dumps(
                    {
                        "by": report.by,
                        "histogram": report.histogram,
                        "median": report.median,
                        "recommendations": report.recommendations,
                    }
                )
            )
            return

        click.echo(f"Balance by {report.by} (median: {report.median})")
        # Alphabetical bucket listing. Align counts with a width derived from
        # the longest bucket name so humans can scan quickly.
        if report.histogram:
            name_width = max(len(name) for name in report.histogram) + 1
            for name in sorted(report.histogram):
                count = report.histogram[name]
                if count == report.median:
                    annotation = "(at median)"
                elif count < report.median:
                    annotation = f"[+{report.median - count}]"
                else:
                    annotation = f"[-{count - report.median} recommended]"
                click.echo(f"  {name:<{name_width}} {count:>4}  {annotation}")

        if report.recommendations:
            click.echo("Recommendations:")
            for rec in report.recommendations:
                click.echo(f"  {rec}")

    @dataset_group.command("export")
    @click.argument("output", required=True, type=click.Path())
    @click.option(
        "--format", "fmt",
        type=click.Choice(["jsonl", "csv"]),
        default=None,
        help="Output format. Inferred from file extension if omitted.",
    )
    @click.option(
        "--source",
        default=_DEFAULT_OUTPUT_DIR,
        show_default=True,
        help="Directory of YAML case files to read from.",
    )
    def dataset_export(output: str, fmt: str | None, source: str) -> None:
        """Export YAML eval cases to JSONL or CSV.

        Examples:
          agentlab eval dataset export out.jsonl
          agentlab eval dataset export out.csv --source evals/cases
        """
        from evals.dataset import exporters
        from evals.runner import EvalRunner

        resolved_format = fmt
        if resolved_format is None:
            suffix = Path(output).suffix.lower()
            if suffix in (".jsonl", ".ndjson"):
                resolved_format = "jsonl"
            elif suffix == ".csv":
                resolved_format = "csv"
            else:
                raise click.ClickException(
                    f"Could not infer format from '{output}'. Pass --format jsonl|csv."
                )

        eval_runner = EvalRunner(cases_dir=source)
        cases = eval_runner.load_cases()

        out_path = Path(output)
        try:
            if resolved_format == "jsonl":
                exporters.export_jsonl(cases, out_path)
            else:
                exporters.export_csv(cases, out_path)
        except FileNotFoundError as exc:
            raise click.ClickException(str(exc)) from exc

        click.echo(f"Exported {len(cases)} cases to {out_path}")
