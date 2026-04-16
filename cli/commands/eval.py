"""`agentlab eval` commands.

Extracted from runner.py in R2 Slice C.2. register_eval_commands(cli)
is called from cli.commands.register_all().

R4.2 extracts the `eval_run` Click callback body into the module-level
:func:`run_eval_in_process` function so both the CLI and the Workbench
slash handler can share the same business logic without spawning a
subprocess. The Click wrapper is now a thin shell that parses argv,
installs event/text writers, and translates domain exceptions into
``sys.exit`` / ``click.ClickException``.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import click
import yaml


def _runner_module():
    """Late-bound import of runner to avoid circular imports."""
    import runner as _r
    return _r


# ---------------------------------------------------------------------------
# R4.2 — pure business-logic function shared by CLI + `/eval` slash handler.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvalRunResult:
    """Outcome of an in-process ``eval run``.

    The Click wrapper uses this to build its final text/json output; the
    slash handler uses ``run_id`` / ``config_path`` to update
    :class:`~cli.workbench_app.session_state.WorkbenchSession`.
    """

    run_id: str | None
    config_path: str | None
    mode: str  # "mock" | "mixed" | "live"
    status: str  # "ok" | "failed"
    composite: float | None
    warnings: tuple[str, ...]
    artifacts: tuple[str, ...]
    # Full CompositeScore-as-dict payload, used by the Click JSON wrapper to
    # render the historical envelope shape (quality/safety/latency/cost/…).
    # The slash handler ignores this field.
    score_payload: dict[str, Any] | None = None


def _make_event_writer(on_event: Callable[[dict], None]) -> Callable[[str], None]:
    """Adapter: turn a ``Callable[[str], None]`` (which ``emit_stream_json``
    hands a JSON-encoded line) into a ``Callable[[dict], None]`` fanout.

    ``ProgressRenderer`` with ``output_format="stream-json"`` serializes each
    event to JSON and calls ``writer(line)``. We parse it back into a dict
    so the slash handler's queue receives structured events without having
    to re-parse. This keeps ``ProgressRenderer`` itself unmodified.
    """
    def _writer(line: str) -> None:
        try:
            event = json.loads(line)
        except (TypeError, ValueError):
            return
        if isinstance(event, dict):
            on_event(event)

    return _writer


def run_eval_in_process(
    *,
    config_path: str | None = None,
    suite: str | None = None,
    category: str | None = None,
    dataset: str | None = None,
    dataset_split: str = "all",
    output_path: str | None = None,
    instruction_overrides_path: str | None = None,
    real_agent: bool = False,
    force_mock: bool = False,
    require_live: bool = False,
    strict_live: bool = False,
    on_event: Callable[[dict], None],
    text_writer: Callable[[str], None] | None = None,
) -> EvalRunResult:
    """Run an eval suite in-process and stream progress events to ``on_event``.

    This is the shared business logic extracted from ``eval_run``. The Click
    wrapper passes an ``on_event`` that writes stream-json lines to stdout
    (when ``--output-format stream-json``) or no-ops (otherwise) plus a
    ``text_writer`` for the human-readable output. The slash handler passes
    an ``on_event`` that queues events for its generator to yield.

    Raises:
        cli.strict_live.MockFallbackError: When ``strict_live`` is set and
            the run fell back to mock mode. The Click wrapper translates
            to ``sys.exit(EXIT_MOCK_FALLBACK)``; the slash wrapper surfaces
            the error in the transcript.
        agent.eval_agent.LiveEvalRequiredError: When ``require_live`` is set
            and live providers can't be obtained. Propagated as-is.
    """
    from agent.eval_agent import LiveEvalRequiredError  # noqa: F401 - re-raised implicitly
    from cli.output import emit_stream_json
    from cli.progress import PhaseSpinner, ProgressRenderer

    runner = _runner_module()
    load_runtime_with_mode_preference = runner.load_runtime_with_mode_preference
    discover_workspace = runner.discover_workspace
    resolve_config_snapshot = runner.resolve_config_snapshot
    persist_config_lockfile = runner.persist_config_lockfile
    eval_mode_banner_label = runner.eval_mode_banner_label

    # --strict-live is the canonical user-facing flag; it implies --require-live
    # AND additionally enforces a post-hoc check on score.warnings.
    if strict_live:
        require_live = True

    # Emit events in stream-json shape; the writer re-parses the JSON line
    # back into a dict and hands it to on_event. This keeps ProgressRenderer
    # unchanged.
    progress = ProgressRenderer(
        output_format="stream-json",
        render_text=False,
        writer=_make_event_writer(on_event),
    )

    artifact_paths_collected: list[str] = []

    def _emit_text(message: str) -> None:
        if text_writer is not None:
            text_writer(message)

    progress.phase_started("eval", message="Run evaluation suite")

    runtime = load_runtime_with_mode_preference()
    if text_writer is not None:
        _emit_text(click.style(f"✦ {runner._soul_line('eval')}", fg="cyan"))
        runner._print_cli_plan(
            "Eval plan",
            [
                "Load active runtime + config",
                "Run eval suite against selected scope",
                "Summarize scores and suggested follow-up",
            ],
        )

    resolved_suite = runner._default_eval_suite_dir(suite)
    config = None
    if config_path:
        config_path = str(runner._resolve_invocation_input_path(Path(config_path)))
        config = runner._load_config_dict(config_path)
        _emit_text(f"Evaluating config: {config_path}")
    else:
        workspace = discover_workspace()
        if workspace is not None:
            resolved = workspace.resolve_active_config()
            if resolved is not None:
                config = resolved.config
                config_path = str(resolved.path)
                _emit_text(f"Evaluating active config: {resolved.path}")
        if config is None:
            _emit_text("Evaluating with default config")

    resolution = resolve_config_snapshot(config_path=config_path, command="eval run")
    persist_config_lockfile(resolution)

    if instruction_overrides_path:
        overrides = runner._load_config_dict(
            str(runner._resolve_invocation_input_path(Path(instruction_overrides_path)))
        )
        if config is None:
            config = {}
        config["_instruction_overrides"] = overrides

    # Resolve agent mode: --mock > --real-agent > auto-detect via credentials
    if force_mock:
        use_real_agent = False
        _auto_detect_reason = "mock-forced"
    elif real_agent:
        use_real_agent = True
        _auto_detect_reason = "real-forced"
    else:
        use_real_agent = runner._has_llm_credentials()
        _auto_detect_reason = "auto-real" if use_real_agent else "auto-mock"

    if text_writer is not None:
        if _auto_detect_reason == "real-forced":
            _emit_text(click.style("Running evals with real agent (--real-agent flag)", fg="green"))
        elif _auto_detect_reason == "auto-real":
            _emit_text(click.style("Running evals with real agent (credentials auto-detected)", fg="green"))
        elif _auto_detect_reason == "mock-forced":
            _emit_text(click.style("Running evals with mock agent (--mock flag)", fg="yellow"))
        elif _auto_detect_reason == "auto-mock":
            _emit_text(click.style(
                "Running evals with mock agent (no LLM credentials found."
                " Set GOOGLE_API_KEY, ANTHROPIC_API_KEY, or OPENAI_API_KEY for real evals)",
                fg="yellow",
            ))

    eval_runner_obj = runner._build_eval_runner(
        runtime,
        cases_dir=resolved_suite,
        use_real_agent=use_real_agent,
        default_agent_config=config,
        **({"require_live": True} if require_live else {}),
    )
    try:
        runner._ensure_live_eval_runner(eval_runner_obj)
    except click.ClickException as exc:
        # Under --strict-live, a pre-execution mock detection is the same
        # failure class as a post-hoc fallback: raise MockFallbackError so
        # callers (Click wrapper / slash handler) can translate uniformly.
        # Without --strict-live, preserve the original ClickException for
        # CLI users who expect the stable exit-code + message contract.
        if strict_live:
            from cli.strict_live import MockFallbackError
            raise MockFallbackError([str(exc)]) from exc
        raise
    initial_mock_messages = list(getattr(eval_runner_obj, "mock_mode_messages", []) or [])
    for message in runner._collect_mock_mode_messages(eval_runner=eval_runner_obj):
        if text_writer is not None:
            _emit_text(click.style(f"⚠ {message}", fg="yellow"))
        progress.warning(message=message, phase="eval")

    case_total = runner._count_eval_cases_for_progress(
        eval_runner_obj,
        category=category,
        dataset_path=dataset,
        split=dataset_split,
    )
    progress.task_started("eval-cases", "Eval cases", message="Evaluate cases", total=case_total)
    progress_seen = False

    def _progress_callback(current: int, total: int) -> None:
        nonlocal progress_seen
        progress_seen = True
        note = f"{current}/{total} cases"
        progress.task_progress(
            "eval-cases",
            "Eval cases",
            note,
            current=current,
            total=total,
        )

    def _run_selected_eval() -> tuple[Any, str, str]:
        if category:
            score_result = runner._call_eval_method_with_progress(
                eval_runner_obj.run_category,
                category,
                config=config,
                dataset_path=dataset,
                split=dataset_split,
                progress_callback=_progress_callback,
            )
            return score_result, f"Category '{category}' complete", f"Category: {category}"
        score_result = runner._call_eval_method_with_progress(
            eval_runner_obj.run,
            config=config,
            dataset_path=dataset,
            split=dataset_split,
            progress_callback=_progress_callback,
        )
        return score_result, "Full eval suite complete", "Full eval suite"

    if text_writer is not None:
        with PhaseSpinner(
            f"Evaluating cases 0/{case_total}",
            output_format="text",
        ) as spinner:
            def _text_progress_callback(current: int, total: int) -> None:
                _progress_callback(current, total)
                spinner.update(f"Evaluating cases {current}/{total}")

            def _run_with_text_progress() -> tuple[Any, str, str]:
                if category:
                    score_result = runner._call_eval_method_with_progress(
                        eval_runner_obj.run_category,
                        category,
                        config=config,
                        dataset_path=dataset,
                        split=dataset_split,
                        progress_callback=_text_progress_callback,
                    )
                    return score_result, f"Category '{category}' complete", f"Category: {category}"
                score_result = runner._call_eval_method_with_progress(
                    eval_runner_obj.run,
                    config=config,
                    dataset_path=dataset,
                    split=dataset_split,
                    progress_callback=_text_progress_callback,
                )
                return score_result, "Full eval suite complete", "Full eval suite"

            score, completion_message, score_heading = _run_with_text_progress()
            spinner.update("Eval complete")
    else:
        score, completion_message, score_heading = _run_selected_eval()

    if not progress_seen:
        progress.task_progress(
            "eval-cases",
            "Eval cases",
            f"{case_total}/{case_total} cases",
            current=case_total,
            total=case_total,
            progress=1.0 if case_total > 0 else None,
        )
    progress.task_completed(
        "eval-cases",
        "Eval cases",
        message="Eval cases complete",
        current=case_total,
        total=case_total,
        progress=1.0 if case_total > 0 else None,
    )
    progress.phase_completed("eval", message=completion_message)
    progress.next_action("agentlab optimize --cycles 3")

    live_eval_agent = getattr(eval_runner_obj, "eval_agent", None)
    if live_eval_agent is not None:
        refreshed_mock_messages = list(getattr(live_eval_agent, "mock_mode_messages", []) or [])
        eval_runner_obj.mock_mode_messages = refreshed_mock_messages
        late_mock_messages = [
            message for message in refreshed_mock_messages if message not in initial_mock_messages
        ]
        if late_mock_messages:
            score.warnings = runner._merge_unique_warnings(
                getattr(score, "warnings", []) or [], late_mock_messages
            )
            for message in late_mock_messages:
                progress.warning(message=message, phase="eval")

    eval_mode = runner._eval_mode_for_runner(eval_runner_obj, runtime=runtime)
    if eval_mode in {"mock", "mixed"}:
        score.warnings = runner._merge_unique_warnings(
            getattr(score, "warnings", []) or [],
            list(getattr(eval_runner_obj, "mock_mode_messages", []) or []),
        )
    if eval_mode == "mixed":
        for warning in list(getattr(eval_runner_obj, "mock_mode_messages", []) or []):
            runner.LOG.warning("eval_run.live_fallback_to_mock: %s", warning)

    # R1.3: --strict-live post-hoc gate. Any mock fallback warning that
    # accumulated in score.warnings causes a raise. The Click wrapper
    # translates this to sys.exit(12); the slash wrapper renders a
    # transcript error.
    if strict_live:
        from cli.strict_live import StrictLivePolicy, MockFallbackError
        policy = StrictLivePolicy(enabled=True)
        policy.ingest_existing_warnings(getattr(score, "warnings", []) or [])
        policy.check()  # raises MockFallbackError

    if text_writer is not None:
        _emit_text(f"\n{runner._eval_results_heading(eval_mode)}")
        # ``_print_score`` echoes directly via click.echo; no text_writer hook
        # exists for it. Keep identical behavior to the pre-R4.2 code path.
        runner._print_score(
            score,
            score_heading,
            mode_label=eval_mode_banner_label(eval_mode),
            status_label=runner._score_status_label(score.composite),
            next_action="agentlab optimize --cycles 3",
        )

    result_payload = runner._build_eval_result_payload(
        score=score,
        mode=eval_mode,
        config_path=config_path,
        category=category,
        dataset=dataset,
        dataset_split=dataset_split,
    )
    latest_output = runner._latest_eval_output_path()
    latest_output.parent.mkdir(parents=True, exist_ok=True)
    latest_output.write_text(json.dumps(result_payload, indent=2), encoding="utf-8")
    progress.artifact_written("eval_results_latest", path=str(latest_output))
    artifact_paths_collected.append(str(latest_output))

    if output_path:
        Path(output_path).write_text(json.dumps(result_payload, indent=2), encoding="utf-8")
        progress.artifact_written("eval_results", path=output_path)
        artifact_paths_collected.append(output_path)
        _emit_text(f"\nResults written to {output_path}")

    # Emit the terminal event the slash handler uses to update session state.
    on_event({
        "event": "eval_complete",
        "run_id": getattr(score, "run_id", None),
        "config_path": config_path,
        "mode": eval_mode,
    })

    return EvalRunResult(
        run_id=getattr(score, "run_id", None),
        config_path=config_path,
        mode=eval_mode,
        status="ok",
        composite=getattr(score, "composite", None),
        warnings=tuple(getattr(score, "warnings", []) or []),
        artifacts=tuple(artifact_paths_collected),
        score_payload=runner._score_to_dict(score),
    )


def register_eval_commands(cli: click.Group) -> None:
    """Register the `eval` group and its subcommands on *cli*."""
    runner = _runner_module()
    DefaultCommandGroup = runner.DefaultCommandGroup
    # Local aliases for module-level symbols that appear in decorator defaults,
    # helpers, or body code. Binding them as locals keeps help-text string
    # representations identical to when runner.py owned the commands.
    EVAL_METRIC_NAMES = runner.EVAL_METRIC_NAMES
    load_runtime_with_mode_preference = runner.load_runtime_with_mode_preference
    discover_workspace = runner.discover_workspace
    resolve_config_snapshot = runner.resolve_config_snapshot
    persist_config_lockfile = runner.persist_config_lockfile
    eval_mode_banner_label = runner.eval_mode_banner_label
    eval_mode_status_label = runner.eval_mode_status_label

    @cli.group("eval", cls=DefaultCommandGroup, default_command="run", default_on_empty=True)
    def eval_group() -> None:
        """Evaluate agent configs against test suites.

        Examples:
          agentlab eval run
          agentlab eval show latest
          agentlab eval compare left.json right.json
          agentlab eval breakdown
          agentlab eval generate --config configs/v001.yaml --output generated_eval_suite.json
        """
        return None


    @eval_group.command("run")
    @click.option("--config", "config_path", default=None, help="Path to config YAML.")
    @click.option("--suite", default=None, help="Path to eval cases directory.")
    @click.option("--dataset", default=None, help="Path to eval dataset (.jsonl or .csv).")
    @click.option("--split", "dataset_split", default="all",
                  type=click.Choice(["train", "test", "all"]),
                  show_default=True,
                  help="Dataset split to evaluate when using --dataset.")
    @click.option("--category", default=None, help="Run only a specific category.")
    @click.option("--output", default=None, help="Write results JSON to file.")
    @click.option(
        "--instruction-overrides",
        "instruction_overrides_path",
        default=None,
        help="Path to a YAML/JSON file containing XML instruction section overrides.",
    )
    @click.option(
        "--real-agent",
        is_flag=True,
        default=False,
        help="Force the real-agent eval path even if optimizer.use_mock is enabled.",
    )
    @click.option(
        "--mock",
        "force_mock",
        is_flag=True,
        default=False,
        help="Force mock agent (no LLM calls).",
    )
    @click.option(
        "--require-live",
        is_flag=True,
        default=False,
        help="Require live providers for this eval and fail instead of falling back to mock mode.",
    )
    @click.option(
        "--strict-live/--no-strict-live",
        default=False,
        help="Exit non-zero (12) if any step falls back to mock execution. "
             "Implies --require-live and additionally fails on post-hoc fallbacks.",
    )
    @click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
    @click.option(
        "--output-format",
        type=click.Choice(["text", "json", "stream-json"], case_sensitive=False),
        default="text",
        show_default=True,
        help="Render text, a final JSON envelope, or stream JSON progress events.",
    )
    def eval_run(config_path: str | None, suite: str | None, dataset: str | None, dataset_split: str,
                 category: str | None, output: str | None, instruction_overrides_path: str | None,
                 real_agent: bool = False,
                 force_mock: bool = False,
                 require_live: bool = False,
                 strict_live: bool = False,
                 json_output: bool = False, output_format: str = "text") -> None:
        """Run eval suite against a config.

        Examples:
          agentlab eval run
          agentlab eval run --config configs/v003.yaml
          agentlab eval run --config configs/v003.yaml --category safety
          agentlab eval run --output results.json
        """
        from agent.eval_agent import LiveEvalRequiredError
        from cli.stream2_helpers import json_response
        from cli.output import resolve_output_format, emit_stream_json
        from cli.strict_live import MockFallbackError
        from cli.exit_codes import EXIT_MOCK_FALLBACK

        resolved_output_format = resolve_output_format(output_format, json_output=json_output)

        # The Click wrapper wires (a) stream-json stdout emission, (b) text
        # rendering, depending on the resolved output format. The slash
        # handler takes a different path (see eval_slash.py).
        if resolved_output_format == "stream-json":
            def _on_event(event: dict) -> None:
                # Re-encode and emit as a stream-json line on stdout. The
                # ``eval_complete`` event is internal-only — it's how the
                # slash handler learns the run_id; we do NOT leak it to
                # stdout to keep the CLI stream shape compatible with
                # downstream loaders.
                if event.get("event") == "eval_complete":
                    # Keep it on the CLI stream too — callers who consume
                    # stream-json may want it. The R4.2 regression test
                    # asserts this is present.
                    pass
                emit_stream_json(event, writer=click.echo)
            text_writer = None
        else:
            _on_event = lambda _event: None  # noqa: E731 — compact assignment is clearer here
            text_writer = click.echo if resolved_output_format == "text" else None

        try:
            result = run_eval_in_process(
                config_path=config_path,
                suite=suite,
                category=category,
                dataset=dataset,
                dataset_split=dataset_split,
                output_path=output,
                instruction_overrides_path=instruction_overrides_path,
                real_agent=real_agent,
                force_mock=force_mock,
                require_live=require_live,
                strict_live=strict_live,
                on_event=_on_event,
                text_writer=text_writer,
            )
        except MockFallbackError as err:
            click.echo(str(err), err=True)
            sys.exit(EXIT_MOCK_FALLBACK)
        except LiveEvalRequiredError as exc:
            raise click.ClickException(str(exc)) from exc

        if resolved_output_format == "stream-json":
            return

        if resolved_output_format == "json":
            # Preserve the pre-R4.2 JSON envelope shape: the full
            # ``_score_to_dict`` payload with ``mode`` and ``run_id`` merged.
            payload: dict[str, Any] = dict(result.score_payload or {})
            payload["mode"] = result.mode
            payload["run_id"] = result.run_id
            click.echo(json_response("ok", payload, next_cmd="agentlab optimize --cycles 3"))
            return

        # Text mode — trailing status + next-actions banner.
        click.echo(click.style(f"\n  Status: {runner._score_status_label(result.composite)}", fg="magenta"))
        runner._print_next_actions(
            [
                "agentlab optimize --cycles 3",
                "agentlab status",
            ],
        )


    @eval_group.group("results", invoke_without_command=True)
    @click.option("--run-id", default=None, help="Structured eval run ID to inspect.")
    @click.option("--file", "results_file", default=None, help="Path to a legacy eval results JSON file.")
    @click.option("--failures", is_flag=True, help="Show only failed examples.")
    @click.pass_context
    def eval_results(
        ctx: click.Context,
        run_id: str | None,
        results_file: str | None,
        failures: bool,
    ) -> None:
        """Inspect structured eval results from the CLI Results Explorer.

        Examples:
          agentlab eval results
          agentlab eval results --run-id eval-123
          agentlab eval results --failures
          agentlab eval results export eval-123 --format markdown
        """
        if ctx.invoked_subcommand is not None:
            return

        if results_file:
            data = json.loads(Path(results_file).read_text(encoding="utf-8"))
            payload = runner._unwrap_eval_payload(data)
            runner._render_eval_results_header(data)
            scores = payload.get("scores", {})
            click.echo(f"  Cases:   {payload.get('passed', '?')}/{payload.get('total', '?')} passed")
            click.echo(f"  Quality:   {scores.get('quality', 0):.4f}")
            click.echo(f"  Safety:    {scores.get('safety', 0):.4f}")
            click.echo(f"  Latency:   {scores.get('latency', 0):.4f}")
            click.echo(f"  Cost:      {scores.get('cost', 0):.4f}")
            click.echo(f"  Composite: {scores.get('composite', 0):.4f}")
            return

        store = runner._results_store_for_cli()
        resolved_run_id = run_id or store.latest_run_id()
        if resolved_run_id is None:
            click.echo("No structured eval results found.")
            click.echo("Run: agentlab eval run")
            return

        result_set = store.get_run(resolved_run_id)
        if result_set is None:
            raise click.ClickException(f"Structured eval run not found: {resolved_run_id}")
        runner._render_structured_results(result_set, failures_only=failures)


    @eval_results.command("annotate")
    @click.argument("example_id")
    @click.option("--run-id", required=True, help="Structured eval run ID to annotate.")
    @click.option("--comment", required=True, help="Annotation text to append.")
    @click.option("--author", default="cli", show_default=True, help="Annotation author.")
    @click.option("--type", "annotation_type", default="comment", show_default=True, help="Annotation type.")
    @click.option("--score-override", default=None, type=float, help="Optional override score.")
    def eval_results_annotate(
        example_id: str,
        run_id: str,
        comment: str,
        author: str,
        annotation_type: str,
        score_override: float | None,
    ) -> None:
        """Append a review note to a structured eval example."""
        from evals.results_model import Annotation

        store = runner._results_store_for_cli()
        example = store.get_example(run_id, example_id)
        if example is None:
            raise click.ClickException(f"Structured eval example not found: {run_id}/{example_id}")

        store.add_annotation(
            run_id,
            example_id,
            Annotation(
                author=author,
                timestamp=datetime.now(tz=timezone.utc).isoformat(),
                type=annotation_type,
                content=comment,
                score_override=score_override,
            ),
        )
        click.echo(f"Annotation saved for {example_id} in {run_id}.")


    @eval_results.command("export")
    @click.argument("run_id")
    @click.option("--format", "export_format", default="json", type=click.Choice(["json", "csv", "markdown"]))
    @click.option("--output", default=None, help="Write export to a file instead of stdout.")
    def eval_results_export(run_id: str, export_format: str, output: str | None) -> None:
        """Export one structured eval run as JSON, CSV, or Markdown."""
        store = runner._results_store_for_cli()
        payload = store.export_run(run_id, format=export_format)
        if output:
            Path(output).write_text(payload, encoding="utf-8")
            click.echo(f"Exported {run_id} to {output}.")
            return
        click.echo(payload)


    @eval_results.command("diff")
    @click.argument("baseline_run_id")
    @click.argument("candidate_run_id")
    def eval_results_diff(baseline_run_id: str, candidate_run_id: str) -> None:
        """Compare two structured eval runs."""
        store = runner._results_store_for_cli()
        diff = store.diff_runs(baseline_run_id, candidate_run_id)
        click.echo(f"\nRun Diff — {baseline_run_id} -> {candidate_run_id}")
        click.echo(f"  New failures: {diff['new_failures']}")
        click.echo(f"  New passes: {diff['new_passes']}")
        click.echo(f"  Changed examples: {len(diff['changed_examples'])}")
        for entry in diff["changed_examples"]:
            click.echo(
                f"  {entry['example_id']}: "
                f"{'pass' if entry['before_passed'] else 'fail'} -> "
                f"{'pass' if entry['after_passed'] else 'fail'} "
                f"({entry['score_delta']:+.4f})"
            )


    @eval_group.command("show")
    @click.argument("selector", default="latest")
    @click.option("--file", "results_file", default=None, help="Path to results JSON file.")
    @click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
    def eval_show(selector: str, results_file: str | None, json_output: bool = False) -> None:
        """Show eval results. Supports selectors: latest.

        Examples:
          agentlab eval show latest
          agentlab eval show latest --json
          agentlab eval show --file results.json
        """
        from cli.stream2_helpers import json_response

        if results_file:
            data = json.loads(Path(results_file).read_text(encoding="utf-8"))
        else:
            _latest_path, data = runner._latest_eval_payload()

        if data is None:
            if json_output:
                click.echo(json_response("error", {"message": "No eval results found"}))
            else:
                click.echo("No eval results found.")
                click.echo("Run: agentlab eval run")
            return

        if json_output:
            click.echo(json_response("ok", data, next_cmd="agentlab optimize"))
            return

        payload = runner._unwrap_eval_payload(data)
        runner._render_eval_results_header(data)
        scores = payload.get("scores", {})
        click.echo(f"  Cases:   {payload.get('passed', '?')}/{payload.get('total', '?')} passed")
        click.echo(f"  Quality:   {scores.get('quality', 0):.4f}")
        click.echo(f"  Safety:    {scores.get('safety', 0):.4f}")
        click.echo(f"  Latency:   {scores.get('latency', 0):.4f}")
        click.echo(f"  Cost:      {scores.get('cost', 0):.4f}")
        click.echo(f"  Composite: {scores.get('composite', 0):.4f}")

        results = payload.get("results", [])
        failed = [r for r in results if not r.get("passed")]
        if failed:
            click.echo(f"\nFailed cases ({len(failed)}):")
            for r in failed:
                click.echo(f"  {r['case_id']} [{r.get('category', '?')}] quality={r.get('quality_score', 0):.2f}")


    @eval_group.command("list")
    def eval_list() -> None:
        """List recent eval runs.

        Note: Full run history requires the API server.
        Checks for local result files in the current directory.
        """
        results_files = runner._list_eval_result_files()
        if not results_files:
            click.echo("No local eval result files found.")
            click.echo("Run: agentlab eval run --output results.json")
            return

        click.echo(f"\nLocal eval results ({len(results_files)} files):")
        for f in results_files[:10]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                ts = data.get("timestamp", "unknown")
                composite = data.get("scores", {}).get("composite", 0)
                passed = data.get("passed", "?")
                total = data.get("total", "?")
                mode = runner._extract_eval_mode(data)
                mode_label = f"  mode={eval_mode_status_label(mode)}" if mode is not None else ""
                click.echo(f"  {f.name}  {ts}  composite={composite:.4f}  {passed}/{total} passed{mode_label}")
            except (json.JSONDecodeError, KeyError):
                click.echo(f"  {f.name}  (invalid format)")


    @eval_group.command("generate")
    @click.option("--config", "config_path", default=None, help="Path to agent config YAML/JSON to analyze.")
    @click.option("--agent-name", default="agent", help="Agent name for labeling the eval suite.")
    @click.option("--from-transcripts", is_flag=True, default=False, help="Generate from conversation transcripts (future).")
    @click.option("--output", default=None, help="Write generated eval suite to JSON file.")
    @click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
    @click.option("--provider", default=None, type=click.Choice(["openai", "anthropic", "mock"]), help="Force LLM provider.")
    def eval_generate(
        config_path: str | None,
        agent_name: str,
        from_transcripts: bool,
        output: str | None,
        json_output: bool,
        provider: str | None,
    ) -> None:
        """AI-generate a comprehensive eval suite from agent config.

        Examples:
          agentlab eval generate
          agentlab eval generate --config agent_config.yaml
          agentlab eval generate --config agent_config.yaml --output evals.json
          agentlab eval generate --provider mock --agent-name "My Agent"
        """
        from evals.auto_generator import AutoEvalGenerator

        if not json_output:
            click.echo(click.style("✦ Auto-generating eval suite", fg="cyan"))
            runner._print_cli_plan(
                "Generation plan",
                [
                    "Analyze agent config (system prompt, tools, routing, policies)",
                    "Generate eval cases across 8 categories via AI",
                    "Output structured eval suite",
                ],
            )

        # Load agent config
        agent_config: dict = {}
        if config_path:
            config_file = Path(config_path)
            if not config_file.exists():
                click.echo(click.style(f"Config file not found: {config_path}", fg="red"), err=True)
                sys.exit(1)
            raw = config_file.read_text(encoding="utf-8")
            if config_file.suffix in (".yaml", ".yml"):
                agent_config = yaml.safe_load(raw) or {}
            else:
                agent_config = json.loads(raw)
            if not json_output:
                click.echo(f"  Loaded config: {config_path}")
        else:
            # Try loading default agentlab.yaml
            default_config = Path("agentlab.yaml")
            if default_config.exists():
                agent_config = yaml.safe_load(default_config.read_text(encoding="utf-8")) or {}
                if not json_output:
                    click.echo("  Loaded default config: agentlab.yaml")
            else:
                if not json_output:
                    click.echo("  No config provided — using empty config (mock cases)")

        if from_transcripts:
            if not json_output:
                click.echo("  --from-transcripts: transcript-based generation (future feature)")

        generator = AutoEvalGenerator(llm_provider=provider)
        if not json_output:
            click.echo("  Generating...")

        suite = generator.generate(agent_config=agent_config, agent_name=agent_name)

        if json_output:
            click.echo(json.dumps(suite.to_dict(), indent=2))
        else:
            click.echo(click.style(f"\n  Suite {suite.suite_id}", fg="green"))
            click.echo(f"  Status:     {suite.status}")
            click.echo(f"  Total cases: {suite.total_cases}")
            click.echo()
            for cat, cases in suite.categories.items():
                difficulty_str = ", ".join(
                    f"{d}={sum(1 for c in cases if c.difficulty == d)}"
                    for d in ("easy", "medium", "hard")
                    if any(c.difficulty == d for c in cases)
                )
                click.echo(f"  {cat:<20s} {len(cases):>3d} cases  ({difficulty_str})")

            summary = suite.summary
            click.echo(f"\n  Safety probes: {summary.get('safety_probes', 0)}")
            click.echo(click.style(f"\n  Status: {runner._score_status_label(0.85)}", fg="magenta"))
            runner._print_next_actions([
                "agentlab eval run --suite <generated_cases>",
                "agentlab eval generate --output evals.json",
            ])

        if output:
            Path(output).write_text(json.dumps(suite.to_dict(), indent=2), encoding="utf-8")
            if not json_output:
                click.echo(f"\n  Written to {output}")


    @eval_group.group("compare", invoke_without_command=True)
    @click.option("--config-a", "config_a_path", default=None, help="Path to config A for a pairwise comparison.")
    @click.option("--config-b", "config_b_path", default=None, help="Path to config B for a pairwise comparison.")
    @click.option("--left-run", default=None, help="Legacy eval result file or run reference for the left side.")
    @click.option("--right-run", default=None, help="Legacy eval result file or run reference for the right side.")
    @click.option("--dataset", default=None, help="Optional dataset file for the pairwise comparison.")
    @click.option("--split", default="all", type=click.Choice(["train", "test", "all"]), show_default=True)
    @click.option("--label-a", default=None, help="Display label for config A.")
    @click.option("--label-b", default=None, help="Display label for config B.")
    @click.option(
        "--judge",
        "judge_strategy",
        default="metric_delta",
        type=click.Choice(["metric_delta", "llm_judge", "human_preference"]),
        show_default=True,
        help="Winner selection strategy for pairwise compare mode.",
    )
    @click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
    @click.pass_context
    def eval_compare(
        ctx: click.Context,
        config_a_path: str | None,
        config_b_path: str | None,
        left_run: str | None,
        right_run: str | None,
        dataset: str | None,
        split: str,
        label_a: str | None,
        label_b: str | None,
        judge_strategy: str,
        json_output: bool = False,
    ) -> None:
        """Compare two eval runs or run a pairwise head-to-head config comparison.

        Prints metric deltas for legacy run-vs-run comparisons, and supports a
        pairwise workflow with stored results, significance stats, and reviewable
        winner summaries.
        """
        from cli.stream2_helpers import json_response
        from evals.pairwise import PairwiseEvalEngine

        if ctx.invoked_subcommand is not None:
            return

        if config_a_path or config_b_path:
            if not config_a_path or not config_b_path:
                raise click.UsageError("Provide both --config-a and --config-b for pairwise comparison mode.")

            runtime = load_runtime_with_mode_preference()
            eval_runner_obj = runner._build_eval_runner(runtime)
            store = runner._pairwise_store_for_cli()
            engine = PairwiseEvalEngine(eval_runner=eval_runner_obj, store=store)
            config_a = runner._load_config_dict(config_a_path)
            config_b = runner._load_config_dict(config_b_path)
            result = engine.compare(
                config_a=config_a,
                config_b=config_b,
                label_a=label_a or Path(config_a_path).stem,
                label_b=label_b or Path(config_b_path).stem,
                dataset_path=dataset,
                dataset_name=Path(dataset).name if dataset else "default",
                split=split,
                judge_strategy=judge_strategy,
            )
            if json_output:
                click.echo(json_response("ok", result.to_dict()))
                return
            runner._render_pairwise_comparison(result)
            return

        if not left_run or not right_run:
            raise click.UsageError(
                "Use --config-a/--config-b for pairwise mode, or --left-run/--right-run for legacy run comparison."
            )

        payload = runner._build_eval_comparison(left_run, right_run)
        if json_output:
            click.echo(json_response("ok", payload))
            return

        click.echo("\nEval comparison")
        click.echo(f"  Run 1: {payload['left']['run']}")
        click.echo(f"  Run 2: {payload['right']['run']}")
        click.echo("")
        click.echo(f"  {'Metric':<12} {'Run 1':>10} {'Run 2':>10} {'Delta':>10}")
        click.echo(f"  {'-' * 12} {'-' * 10} {'-' * 10} {'-' * 10}")
        for metric in EVAL_METRIC_NAMES:
            left_value = payload["left"]["scores"][metric]
            right_value = payload["right"]["scores"][metric]
            delta = payload["deltas"][metric]
            click.echo(f"  {metric:<12} {left_value:>10.4f} {right_value:>10.4f} {delta:>+10.4f}")
        click.echo(f"\n  Winner: {payload['winner']}")


    @eval_compare.command("show")
    @click.argument("selector", default="latest")
    def eval_compare_show(selector: str) -> None:
        """Show one stored pairwise comparison."""
        store = runner._pairwise_store_for_cli()
        result = store.latest() if selector == "latest" else store.get(selector)
        if result is None:
            raise click.ClickException(f"Pairwise comparison not found: {selector}")
        runner._render_pairwise_comparison(result)


    @eval_compare.command("list")
    @click.option("--limit", default=10, show_default=True, type=int)
    def eval_compare_list(limit: int) -> None:
        """List recent stored pairwise comparisons."""
        store = runner._pairwise_store_for_cli()
        items = store.list(limit=limit)
        click.echo("\nRecent pairwise comparisons")
        if not items:
            click.echo("  none found")
            return
        for item in items:
            click.echo(
                f"  {item.comparison_id}  {item.label_a} vs {item.label_b}  "
                f"winner={item.analysis.winner}  p={item.analysis.p_value:.4f}"
            )


    # ------------------------------------------------------------------
    # R3.10 — `agentlab eval weights {show|set|validate}`
    # ------------------------------------------------------------------

    @eval_group.group("weights", invoke_without_command=False)
    def eval_weights_group() -> None:
        """Manage composite score weights (eval.composite.weights in agentlab.yaml)."""

    @eval_weights_group.command("show")
    def eval_weights_show() -> None:
        """Print the current composite weights (defaults when yaml absent)."""
        from evals.composite_weights import load_from_workspace
        w = load_from_workspace("agentlab.yaml")
        click.echo(f"quality: {w.quality}")
        click.echo(f"safety:  {w.safety}")
        click.echo(f"latency: {w.latency}")
        click.echo(f"cost:    {w.cost}")

    @eval_weights_group.command("set")
    @click.option("--quality", type=float, required=True, help="Quality weight (0..1).")
    @click.option("--safety", type=float, required=True, help="Safety weight (0..1).")
    @click.option("--latency", type=float, required=True, help="Latency weight (0..1).")
    @click.option("--cost", type=float, required=True, help="Cost weight (0..1).")
    @click.option("--config-path", default="agentlab.yaml", show_default=True,
                  help="Workspace yaml to modify.")
    def eval_weights_set(
        quality: float, safety: float, latency: float, cost: float, config_path: str,
    ) -> None:
        """Write composite weights to agentlab.yaml after validating sum==1.0."""
        from evals.composite_weights import CompositeWeights, validate_weights
        w = CompositeWeights(quality=quality, safety=safety, latency=latency, cost=cost)
        try:
            validate_weights(w)
        except ValueError as exc:
            click.echo(f"ERROR: {exc}", err=True)
            raise SystemExit(2)
        _write_weights_to_yaml(config_path, w)
        click.echo(f"Wrote weights to {config_path}")

    @eval_weights_group.command("validate")
    @click.option("--config-path", default="agentlab.yaml", show_default=True,
                  help="Workspace yaml to validate.")
    def eval_weights_validate(config_path: str) -> None:
        """Check that composite weights in the workspace yaml sum to 1.0."""
        from evals.composite_weights import load_from_workspace, validate_weights
        w = load_from_workspace(config_path)
        try:
            validate_weights(w)
        except ValueError as exc:
            click.echo(f"ERROR: {exc}", err=True)
            raise SystemExit(2)
        click.echo("weights OK (sum=1.0, all non-negative)")


    def _write_weights_to_yaml(config_path: str, weights) -> None:
        """Round-trip a yaml file, overwriting only eval.composite.weights.*."""
        import yaml as _yaml
        from pathlib import Path
        path = Path(config_path)
        if path.exists():
            data = _yaml.safe_load(path.read_text()) or {}
        else:
            data = {}
        eval_section = data.setdefault("eval", {})
        composite_section = eval_section.setdefault("composite", {})
        composite_section["weights"] = {
            "quality": weights.quality,
            "safety": weights.safety,
            "latency": weights.latency,
            "cost": weights.cost,
        }
        path.write_text(_yaml.safe_dump(data, default_flow_style=False, sort_keys=False))


    @eval_group.command("breakdown")
    @click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
    def eval_breakdown(json_output: bool = False) -> None:
        """Show score breakdown bars and failure clusters for the latest eval result."""
        from cli.stream2_helpers import json_response

        payload = runner._build_eval_breakdown()
        if json_output:
            click.echo(json_response("ok", payload))
            return

        source_name = Path(payload["source"]).name
        click.echo(f"\nEval Breakdown (from {source_name})")
        click.echo(f"  {'-' * 50}")
        for metric in EVAL_METRIC_NAMES:
            value = max(0.0, min(1.0, payload["scores"][metric]))
            click.echo(f"  {metric:<12} {runner._bar_chart(value)} {payload['scores'][metric]:.4f}")

        click.echo("\n  Failure Clusters:")
        clusters = payload["failure_clusters"]
        if not clusters:
            click.echo("    none recorded")
            return

        for cluster, count in sorted(clusters.items(), key=lambda item: (-item[1], item[0])):
            click.echo(f"    {count:>3}x {cluster}")
