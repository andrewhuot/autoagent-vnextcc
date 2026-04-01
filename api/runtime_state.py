"""Helpers for refreshing runtime-sensitive API app state after settings changes."""

from __future__ import annotations

from fastapi import FastAPI


def refresh_runtime_state(app: FastAPI) -> None:
    """Rebuild runtime-sensitive services after keys or mode settings change.

    WHY: The API server caches provider-aware services at startup. Saving API
    keys or switching mock/auto/live mode in the UI must take effect
    immediately for health, build, eval, and optimize flows without a restart.
    """
    from agent import create_eval_agent
    from agent.tracing import instrument_eval_runner
    from cli.mode import load_runtime_with_builder_live_preference, load_runtime_with_mode_preference
    from evals.execution_mode import requested_live_mode
    from evals.runner import EvalRunner
    from optimizer.providers import build_router_from_runtime_config
    from optimizer.proposer import Proposer
    from optimizer.transcript_intelligence import TranscriptIntelligenceService
    from shared.transcript_report_store import TranscriptReportStore

    runtime = load_runtime_with_mode_preference()
    app.state.runtime_config = runtime

    router = build_router_from_runtime_config(runtime.optimizer)
    app.state.proposer = Proposer(
        use_mock=router.mock_mode,
        llm_router=router,
        mock_reason=router.mock_reason,
    )

    studio_runtime = load_runtime_with_builder_live_preference()
    studio_router = build_router_from_runtime_config(studio_runtime.optimizer)
    report_store = getattr(app.state, "transcript_report_store", None)
    if report_store is None:
        report_store = TranscriptReportStore()
        app.state.transcript_report_store = report_store
    app.state.transcript_intelligence_service = TranscriptIntelligenceService(
        llm_router=studio_router,
        report_store=report_store,
    )

    version_manager = getattr(app.state, "version_manager", None)
    default_config = version_manager.get_active_config() if version_manager is not None else None
    eval_agent = create_eval_agent(
        runtime,
        default_config=default_config,
    )
    eval_runner = EvalRunner(
        agent_fn=eval_agent.run,
        history_db_path=runtime.eval.history_db_path,
        cache_enabled=runtime.eval.cache_enabled,
        cache_db_path=runtime.eval.cache_db_path,
        dataset_strict_integrity=runtime.eval.dataset_strict_integrity,
        random_seed=runtime.eval.random_seed,
        token_cost_per_1k=runtime.eval.token_cost_per_1k,
    )
    eval_runner.eval_agent = eval_agent
    eval_runner.requested_live = requested_live_mode(runtime)
    trace_store = getattr(app.state, "trace_store", None)
    if trace_store is not None:
        instrument_eval_runner(eval_runner, trace_store, agent_path="eval", branch="api")
        app.state.tracing_middleware = getattr(eval_runner, "tracing_middleware", None)
    eval_runner.mock_mode_messages = list(eval_agent.mock_mode_messages)
    app.state.eval_runner = eval_runner
    app.state.results_store = eval_runner.results_store

    optimizer = getattr(app.state, "optimizer", None)
    if optimizer is not None:
        optimizer.eval_runner = eval_runner
        optimizer.proposer = app.state.proposer
        optimizer.significance_alpha = runtime.eval.significance_alpha
        optimizer.significance_min_effect_size = runtime.eval.significance_min_effect_size
        optimizer.significance_iterations = runtime.eval.significance_iterations
        optimizer.significance_min_pairs = runtime.eval.significance_min_pairs

    autofix_engine = getattr(app.state, "autofix_engine", None)
    if autofix_engine is not None:
        autofix_engine.eval_runner = eval_runner
