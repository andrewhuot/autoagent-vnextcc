"""`agentlab eval dataset` subcommands.

Thin wrapper over :mod:`evals.dataset.importers` / :mod:`evals.dataset.exporters`
that wires JSONL, CSV, and HuggingFace sources into the CLI. Added in R5 Slice
A.6 — the dataset subgroup is nested under the existing `eval` group.
"""
from __future__ import annotations

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
