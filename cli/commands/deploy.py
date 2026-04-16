"""`agentlab deploy` command.

Extracted from runner.py in R2 Slice C.4 — the final runner.py
extraction. register_deploy_commands(cli) is called from
cli.commands.register_all().

Preserves R1 invariants: --force-deploy-degraded / --reason gating
and lineage emission via --attempt-id (Slice A.5).

R4.6 extracts the `deploy` Click callback body into the module-level
:func:`run_deploy_in_process` function so both the CLI and the Workbench
``/deploy`` slash handler can share the same business logic without
spawning a subprocess. The Click wrapper delegates the stream-json path
to it; the legacy text/JSON paths are preserved as-is to avoid churn.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import click
import yaml

from cli.commands._in_process import make_event_writer as _make_event_writer


def _runner_module():
    """Late-bound import of runner to avoid circular imports."""
    import runner as _r
    return _r


# ---------------------------------------------------------------------------
# R4.6 — pure business-logic function shared by CLI + `/deploy` slash handler.
# ---------------------------------------------------------------------------


class DeployCommandError(RuntimeError):
    """Raised by ``run_deploy_in_process`` for domain-level deploy failures.

    The Click wrapper translates this to :class:`click.ClickException`;
    the slash handler surfaces the message as a transcript error.
    """


class DeployVerdictBlockedError(DeployCommandError):
    """Raised when the R1.9 deploy verdict gate blocks a deploy.

    The Click wrapper translates this to ``sys.exit(EXIT_DEGRADED_DEPLOY)``
    (the R1-established exit code 13); the slash handler surfaces the
    message as a transcript error. The in-process runner emits a terminal
    ``deploy_complete`` event with ``status="blocked"`` BEFORE raising so
    consumers see a well-formed envelope either way.
    """


@dataclass(frozen=True)
class DeployRunResult:
    """Outcome of an in-process ``deploy`` invocation.

    The ``/deploy`` slash handler uses this to build its summary; the
    Click wrapper ignores it (stream-json is the authoritative output).
    """

    attempt_id: str | None
    deployment_id: str | None
    verdict: str | None       # "approved" | "blocked" | None
    status: str               # "ok" | "failed" | "blocked" | "cancelled"
    failure_reason: str | None = None


def _strict_live_gate(*, strict_live: bool, warnings: list[str]) -> None:
    """Apply the strict-live gate on accumulated fallback warnings.

    Extracted as a module-level function so tests can monkeypatch it to
    inject a :class:`MockFallbackError` without going through the full
    deploy flow. Real strict-live enforcement happens via
    :class:`cli.strict_live.StrictLivePolicy`.
    """
    if not strict_live or not warnings:
        return
    from cli.strict_live import MockFallbackError

    raise MockFallbackError(warnings)


def run_deploy_in_process(
    *,
    workflow: str | None = None,
    config_version: int | None = None,
    strategy: str = "canary",
    configs_dir: str | None = None,
    db: str | None = None,
    target: str = "agentlab",
    dry_run: bool = False,
    acknowledge: bool = False,
    auto_review: bool = False,
    force_deploy_degraded: bool = False,
    force_reason: str | None = None,
    attempt_id: str | None = None,
    release_experiment_id: str | None = None,
    strict_live: bool = False,
    on_event: Callable[[dict[str, Any]], None],
    text_writer: Callable[[str], None] | None = None,
) -> DeployRunResult:
    """Execute a non-CX deploy flow in-process; stream events to ``on_event``.

    This extraction covers the non-CX-studio deploy paths (canary,
    immediate, rollback, status, dry-run). CX export remains on the
    legacy Click callback — it involves interactive state that does not
    map onto the event-streaming model.

    Invariants preserved from R1:
      - The degraded-verdict gate runs before any state mutation.
      - A blocked verdict raises :class:`DeployVerdictBlockedError`
        (Click wrapper → ``sys.exit(EXIT_DEGRADED_DEPLOY)``). Before
        raising, a terminal ``deploy_complete`` event is emitted with
        ``status="blocked"`` / ``verdict="blocked"``.
      - ``--force-deploy-degraded`` with a ``--reason`` of at least 10
        characters overrides the gate.
    """
    from cli.progress import ProgressRenderer
    from cli.stream2_helpers import json_response

    runner = _runner_module()
    resolved_configs_dir = configs_dir if configs_dir is not None else runner.CONFIGS_DIR
    resolved_db = db if db is not None else runner.DB_PATH
    ConversationStore = runner.ConversationStore
    Deployer = runner.Deployer

    # Stream-json-shaped ProgressRenderer; the writer re-parses each JSON
    # line back into a dict and hands it to on_event.
    progress = ProgressRenderer(
        output_format="stream-json",
        render_text=False,
        writer=_make_event_writer(on_event),
    )

    warnings_collected: list[str] = []
    terminal_verdict: str | None = None
    terminal_deployment_id: str | None = None

    def _emit_text(message: str) -> None:
        if text_writer is not None:
            text_writer(message)

    def _emit_terminal(
        *,
        status: str,
        verdict: str | None,
        deployment_id: str | None,
        failure_reason: str | None = None,
    ) -> DeployRunResult:
        event: dict[str, Any] = {
            "event": "deploy_complete",
            "attempt_id": attempt_id,
            "deployment_id": deployment_id,
            "status": status,
            "verdict": verdict,
        }
        if failure_reason is not None:
            event["failure_reason"] = failure_reason
        on_event(event)
        return DeployRunResult(
            attempt_id=attempt_id,
            deployment_id=deployment_id,
            verdict=verdict,
            status=status,
            failure_reason=failure_reason,
        )

    # Optional auto-review (replicates ship behavior) — unchanged from R1.
    if auto_review:
        try:
            from optimizer.change_card import ChangeCardStore

            card_store = ChangeCardStore()
            pending = card_store.list_pending(limit=200)
            if not dry_run:
                for card in pending:
                    card_store.approve(card.card_id)
        except Exception:
            pass

    progress.phase_started("deploy", message="Prepare deployment")

    # R1.9 verdict gate — translate sys.exit into DeployVerdictBlockedError.
    try:
        runner._deploy_gate_check(
            force_deploy_degraded=force_deploy_degraded,
            force_reason=force_reason,
            output_format="stream-json",
        )
    except SystemExit as exc:
        # Gate decided to block. Emit terminal event, then raise.
        code = int(exc.code) if isinstance(exc.code, int) else 1
        from cli.exit_codes import EXIT_DEGRADED_DEPLOY
        if code == EXIT_DEGRADED_DEPLOY:
            _emit_terminal(
                status="blocked",
                verdict="blocked",
                deployment_id=None,
                failure_reason="deploy gate: degraded eval verdict",
            )
            raise DeployVerdictBlockedError(
                "Deploy blocked: latest eval verdict is degraded. "
                "Use --force-deploy-degraded --reason \"...\" to override."
            ) from exc
        # Other exit codes (e.g. 2 for bad --reason) re-raise as-is.
        raise

    # Workflow positional resolves strategy.
    if workflow is not None:
        if workflow == "release":
            strategy = "immediate"
        elif workflow != "rollback":
            strategy = workflow

    store = ConversationStore(db_path=resolved_db)
    deployer = Deployer(configs_dir=resolved_configs_dir, store=store)
    history = deployer.version_manager.get_version_history()

    if workflow == "status":
        snapshot = deployer.status()
        progress.phase_completed("deploy", message="Status read")
        _strict_live_gate(strict_live=strict_live, warnings=warnings_collected)
        return _emit_terminal(status="ok", verdict=None, deployment_id=None)

    if not history:
        progress.warning(message="No config versions available", phase="deploy")
        warnings_collected.append("no config versions available")
        _strict_live_gate(strict_live=strict_live, warnings=warnings_collected)
        return _emit_terminal(
            status="failed",
            verdict=None,
            deployment_id=None,
            failure_reason="no config versions available",
        )

    if workflow == "rollback":
        rollback_version = config_version or deployer.version_manager.manifest.get(
            "canary_version"
        )
        if rollback_version is None:
            progress.warning(
                message="No active canary deployment to roll back", phase="deploy"
            )
            return _emit_terminal(
                status="failed",
                verdict=None,
                deployment_id=None,
                failure_reason="no canary deployment to roll back",
            )
        if dry_run:
            progress.phase_completed(
                "deploy",
                message=f"Dry-run rollback preview v{rollback_version:03d}",
            )
            progress.next_action("agentlab deploy rollback")
            _strict_live_gate(strict_live=strict_live, warnings=warnings_collected)
            return _emit_terminal(
                status="ok",
                verdict="approved",
                deployment_id=None,
            )
        deployer.version_manager.rollback(rollback_version)
        deployment_id = f"rollback-v{rollback_version:03d}"
        _emit_deploy_lineage(
            attempt_id=attempt_id,
            deployment_id=deployment_id,
            version=rollback_version,
            strategy="rollback",
        )
        progress.phase_completed(
            "deploy", message=f"Rolled back canary v{rollback_version:03d}"
        )
        progress.next_action("agentlab status")
        terminal_deployment_id = deployment_id
        terminal_verdict = "approved"
        _strict_live_gate(strict_live=strict_live, warnings=warnings_collected)
        return _emit_terminal(
            status="ok",
            verdict=terminal_verdict,
            deployment_id=terminal_deployment_id,
        )

    active_version = deployer.version_manager.manifest.get("active_version")
    if config_version is None:
        deployable_candidates = [
            entry["version"]
            for entry in history
            if entry["version"] != active_version
            and entry.get("status") in {"candidate", "evaluated", "canary", "imported"}
        ]
        if strategy == "canary":
            if not deployable_candidates:
                reason = (
                    "No candidate config version available to deploy. "
                    "Run `agentlab optimize --cycles 1`, review/apply a candidate, "
                    "or pass --config-version."
                )
                progress.warning(message=reason, phase="deploy")
                _strict_live_gate(strict_live=strict_live, warnings=warnings_collected)
                _emit_terminal(
                    status="failed",
                    verdict=None,
                    deployment_id=None,
                    failure_reason=reason,
                )
                raise DeployCommandError(reason)
            config_version = max(deployable_candidates)
        else:
            config_version = history[-1]["version"]

    found = None
    for v in history:
        if v["version"] == config_version:
            found = v
            break
    if found is None:
        reason = f"Version {config_version} not found"
        progress.warning(message=reason, phase="deploy")
        _strict_live_gate(strict_live=strict_live, warnings=warnings_collected)
        return _emit_terminal(
            status="failed",
            verdict=None,
            deployment_id=None,
            failure_reason=reason,
        )

    if strategy == "canary" and config_version == active_version:
        reason = (
            f"Cannot deploy active version v{config_version:03d} as its own canary. "
            "Choose a non-active candidate version."
        )
        progress.warning(message=reason, phase="deploy")
        _strict_live_gate(strict_live=strict_live, warnings=warnings_collected)
        _emit_terminal(
            status="failed",
            verdict=None,
            deployment_id=None,
            failure_reason=reason,
        )
        raise DeployCommandError(reason)

    filepath = Path(resolved_configs_dir) / found["filename"]
    with filepath.open("r", encoding="utf-8") as f:
        _config = yaml.safe_load(f)
    del _config

    if dry_run:
        progress.phase_completed("deploy", message="Dry-run deployment preview ready")
        progress.next_action("agentlab deploy")
        _strict_live_gate(strict_live=strict_live, warnings=warnings_collected)
        return _emit_terminal(
            status="ok",
            verdict="approved",
            deployment_id=None,
        )

    created_release: dict[str, Any] | None = None
    if auto_review:
        from cli.stream2_helpers import ReleaseStore

        created_release = ReleaseStore().create(
            release_experiment_id or f"ship-v{config_version:03d}",
            config_version=config_version,
        )

    if strategy == "immediate":
        deployer.version_manager.promote(config_version)
        deployment_id = f"promote-v{config_version:03d}"
        _emit_deploy_lineage(
            attempt_id=attempt_id,
            deployment_id=deployment_id,
            version=config_version,
            strategy="immediate",
        )
        progress.phase_completed(
            "deploy", message=f"Deployed v{config_version:03d} immediately"
        )
        progress.next_action("agentlab status")
        terminal_deployment_id = deployment_id
        terminal_verdict = "approved"
    else:
        deployer.version_manager.mark_canary(config_version)
        deployment_id = f"canary-v{config_version:03d}"
        _emit_deploy_lineage(
            attempt_id=attempt_id,
            deployment_id=deployment_id,
            version=config_version,
            strategy="canary",
        )
        progress.phase_completed(
            "deploy", message=f"Deployed v{config_version:03d} as canary"
        )
        progress.next_action("agentlab status")
        terminal_deployment_id = deployment_id
        terminal_verdict = "approved"

    _strict_live_gate(strict_live=strict_live, warnings=warnings_collected)
    return _emit_terminal(
        status="ok",
        verdict=terminal_verdict,
        deployment_id=terminal_deployment_id,
    )


def _emit_deploy_lineage(
    *,
    attempt_id: str | None,
    deployment_id: str,
    version: int,
    strategy: str,
) -> None:
    """Emit a deployment event to the improvement lineage store. Guarded."""
    if not attempt_id:
        return
    db_path = os.environ.get(
        "AGENTLAB_IMPROVEMENT_LINEAGE_DB",
        ".agentlab/improvement_lineage.db",
    )
    if not db_path:
        return
    try:
        from optimizer.improvement_lineage import ImprovementLineageStore
        store = ImprovementLineageStore(db_path=db_path)
        store.record_deployment(
            attempt_id=attempt_id,
            deployment_id=deployment_id,
            version=version,
            strategy=strategy,
        )
    except Exception:
        pass


def register_deploy_commands(cli: click.Group) -> None:
    """Register the `deploy` command on *cli*."""
    runner = _runner_module()
    # Local aliases for module-level symbols that appear in decorator defaults.
    # Binding them as locals keeps help-text string representations identical
    # to when runner.py owned the command.
    DB_PATH = runner.DB_PATH
    CONFIGS_DIR = runner.CONFIGS_DIR
    ConversationStore = runner.ConversationStore
    Deployer = runner.Deployer

    @cli.command("deploy")
    @click.argument("workflow", required=False, type=click.Choice(["canary", "immediate", "release", "rollback", "status"]))
    @click.option("--config-version", type=int, default=None,
                  help="Config version to deploy. Defaults to latest accepted.")
    @click.option("--strategy", type=click.Choice(["canary", "immediate"]),
                  default="canary", show_default=True, help="Deployment strategy.")
    @click.option("--configs-dir", default=CONFIGS_DIR, show_default=True, help="Configs directory.")
    @click.option("--db", default=DB_PATH, show_default=True, help="Conversation store DB.")
    @click.option(
        "--target",
        type=click.Choice(["agentlab", "cx-studio"]),
        default="agentlab",
        show_default=True,
        help="Deployment target.",
    )
    @click.option("--project", default=None, help="GCP project ID (required for CX push).")
    @click.option("--location", default="global", show_default=True, help="CX agent location.")
    @click.option("--agent-id", default=None, help="CX agent ID (required for CX push).")
    @click.option("--snapshot", default=None, help="CX snapshot JSON path from `agentlab cx import`.")
    @click.option("--credentials", default=None, help="Path to service account JSON for CX calls.")
    @click.option("--output", default=None, help="Output path for CX export package JSON.")
    @click.option("--push/--no-push", default=False, show_default=True, help="Push to CX now (otherwise package only).")
    @click.option("--dry-run", is_flag=True, help="Preview the deployment plan without mutating state.")
    @click.option("-y", "--yes", "acknowledge", is_flag=True, default=False, help="Skip interactive deployment confirmation.")
    @click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
    @click.option(
        "--output-format",
        type=click.Choice(["text", "json", "stream-json"], case_sensitive=False),
        default="text",
        show_default=True,
        help="Render text, a final JSON envelope, or stream JSON progress events.",
    )
    @click.option("--auto-review", is_flag=True, default=False,
                  help="Apply all pending review cards before deploying (replicates ship behavior).")
    @click.option(
        "--force-deploy-degraded",
        is_flag=True,
        default=False,
        help="Override the degraded-eval gate. Requires --reason.",
    )
    @click.option(
        "--reason",
        "force_reason",
        default=None,
        help="Required justification when using --force-deploy-degraded (min 10 chars).",
    )
    @click.option(
        "--attempt-id",
        default=None,
        help="Link this deployment to a specific improve attempt for lineage tracking.",
    )
    @click.option("--release-experiment-id", default=None, hidden=True)
    def deploy(
        workflow: str | None,
        config_version: int | None,
        strategy: str,
        configs_dir: str,
        db: str,
        target: str,
        project: str | None,
        location: str,
        agent_id: str | None,
        snapshot: str | None,
        credentials: str | None,
        output: str | None,
        push: bool,
        dry_run: bool,
        acknowledge: bool,
        json_output: bool = False,
        output_format: str = "text",
        auto_review: bool = False,
        force_deploy_degraded: bool = False,
        force_reason: str | None = None,
        attempt_id: str | None = None,
        release_experiment_id: str | None = None,
    ) -> None:
        """Deploy a config version with canary, release, and rollback-friendly workflows.

        Examples:
          agentlab deploy canary
          agentlab deploy --config-version 5 --strategy canary
          agentlab deploy --strategy immediate
          agentlab deploy canary --yes
          agentlab deploy --target cx-studio
        """
        if auto_review:
            try:
                from optimizer.change_card import ChangeCardStore
                card_store = ChangeCardStore()
                pending = card_store.list_pending(limit=200)
                if not dry_run:
                    for card in pending:
                        card_store.approve(card.card_id)
                if pending and output_format == "text" and not dry_run:
                    click.echo(click.style(f"  Auto-reviewed: {len(pending)} pending card(s)", fg="green"))
            except Exception:
                pass
        from cli.output import resolve_output_format, emit_stream_json
        from cli.permissions import PermissionManager
        from cli.progress import ProgressRenderer

        resolved_output_format = resolve_output_format(output_format, json_output=json_output)

        # R4.6 — stream-json mode delegates to run_deploy_in_process so
        # the /deploy slash handler + CLI share the exact same event
        # sequence and terminal envelope. The legacy text/json paths
        # below keep their original shape.
        if resolved_output_format == "stream-json" and target != "cx-studio":
            from cli.exit_codes import EXIT_DEGRADED_DEPLOY, EXIT_MOCK_FALLBACK
            from cli.strict_live import MockFallbackError

            def _on_event(event: dict[str, Any]) -> None:
                emit_stream_json(event, writer=click.echo)

            try:
                run_deploy_in_process(
                    workflow=workflow,
                    config_version=config_version,
                    strategy=strategy,
                    configs_dir=configs_dir,
                    db=db,
                    target=target,
                    dry_run=dry_run,
                    acknowledge=acknowledge,
                    auto_review=auto_review,
                    force_deploy_degraded=force_deploy_degraded,
                    force_reason=force_reason,
                    attempt_id=attempt_id,
                    release_experiment_id=release_experiment_id,
                    on_event=_on_event,
                    text_writer=None,
                )
            except DeployVerdictBlockedError as exc:
                click.echo(str(exc), err=True)
                sys.exit(EXIT_DEGRADED_DEPLOY)
            except MockFallbackError as exc:
                click.echo(str(exc), err=True)
                sys.exit(EXIT_MOCK_FALLBACK)
            except DeployCommandError as exc:
                raise click.ClickException(str(exc)) from exc
            return

        progress = ProgressRenderer(output_format=resolved_output_format, render_text=False)
        progress.phase_started("deploy", message="Prepare deployment")

        runner._deploy_gate_check(
            force_deploy_degraded=force_deploy_degraded,
            force_reason=force_reason,
            output_format=resolved_output_format,
        )

        if workflow is not None:
            if workflow == "release":
                strategy = "immediate"
            elif workflow != "rollback":
                strategy = workflow

        if target == "cx-studio":
            try:
                selected_version, config, selected_path = runner._load_versioned_config(configs_dir, config_version)
            except FileNotFoundError as exc:
                click.echo(str(exc))
                click.echo("Run: agentlab build \"Describe your agent\" or agentlab init")
                return

            package_dir = Path(".agentlab")
            package_dir.mkdir(parents=True, exist_ok=True)
            output_path = Path(output) if output else package_dir / f"cx_export_v{selected_version:03d}.json"
            package = {
                "generated_at": datetime.now(tz=timezone.utc).isoformat(),
                "target": "cx-studio",
                "config_version": selected_version,
                "project": project,
                "location": location,
                "agent_id": agent_id,
                "config": config,
            }
            output_path.write_text(json.dumps(package, indent=2), encoding="utf-8")
            progress.artifact_written("cx-export", path=str(output_path))
            if resolved_output_format == "text":
                click.echo(f"CX export package written: {output_path}")

            if snapshot:
                try:
                    from cx_studio import CxAuth, CxClient, CxExporter

                    auth = CxAuth.__new__(CxAuth)
                    auth._token = None
                    auth._token_expiry = 0.0
                    auth._project_id = project
                    auth._credentials_path = credentials
                    client = CxClient.__new__(CxClient)
                    client._auth = auth
                    client._timeout = 30.0
                    client._max_retries = 3
                    exporter = CxExporter(client)
                    changes = exporter.preview_changes(config, snapshot)
                    click.echo(f"Preview: {len(changes)} change(s) ready for CX export")
                except Exception as exc:
                    progress.warning(message=f"CX preview unavailable ({exc})", phase="deploy")
                    if resolved_output_format == "text":
                        click.echo(click.style(f"Warning: CX preview unavailable ({exc})", fg="yellow"))

            if not push:
                progress.phase_completed("deploy", message="CX package ready")
                progress.next_action("agentlab cx export --project <project> --location <location> --agent <agent-id> --config <config> --snapshot <snapshot>")
                if resolved_output_format == "stream-json":
                    return
                click.echo("No remote CX push performed (`--no-push`).")
                click.echo("Next step:")
                click.echo(
                    "  agentlab cx export --project <project> --location "
                    f"{location} --agent <agent-id> --config {selected_path} --snapshot <snapshot>"
                )
                return

            if not project or not agent_id or not snapshot:
                click.echo("CX push requires --project, --agent-id, and --snapshot.")
                raise SystemExit(2)

            from cx_studio import CxAuth, CxClient, CxExporter
            from cx_studio.types import CxAgentRef

            auth = CxAuth(credentials_path=credentials)
            client = CxClient(auth)
            exporter = CxExporter(client)
            ref = CxAgentRef(project=project, location=location, agent_id=agent_id)
            result = exporter.export_agent(config, ref, snapshot_path=snapshot, dry_run=False)
            progress.phase_completed("deploy", message="CX export pushed")
            progress.next_action("agentlab status")
            if resolved_output_format == "stream-json":
                return
            click.echo(f"CX export pushed: {result.resources_updated} resource(s) updated")
            return

        from cli.stream2_helpers import json_response

        store = ConversationStore(db_path=db)
        deployer = Deployer(configs_dir=configs_dir, store=store)
        history = deployer.version_manager.get_version_history()

        if workflow == "status":
            snapshot = deployer.status()
            if json_output:
                click.echo(json_response("ok", snapshot, next_cmd="agentlab status"))
            else:
                active_version = snapshot.get("active_version")
                canary_version = snapshot.get("canary_version")
                click.echo("\nDeployment status")
                click.echo(f"  Active:  {f'v{active_version:03d}' if active_version is not None else 'none'}")
                click.echo(f"  Canary:  {f'v{canary_version:03d}' if canary_version is not None else 'none'}")
                click.echo(f"  Versions: {snapshot.get('total_versions', 0)} tracked")
            return

        if not history:
            if json_output:
                click.echo(json_response("error", {"message": "No config versions available"}))
            else:
                click.echo("No config versions available. Run: agentlab optimize")
            return

        if workflow == "rollback":
            rollback_version = config_version or deployer.version_manager.manifest.get("canary_version")
            if rollback_version is None:
                if json_output:
                    click.echo(json_response("error", {"message": "No active canary deployment to roll back"}))
                else:
                    click.echo("No active canary deployment to roll back.")
                return
            if dry_run:
                payload = {"version": rollback_version, "strategy": "rollback", "target": target}
                if json_output:
                    click.echo(json_response("ok", payload, next_cmd="agentlab deploy rollback"))
                else:
                    click.echo("Dry run: deployment rollback preview")
                    click.echo(f"  Version: {rollback_version}")
                    click.echo(f"  Target:  {target}")
                return
            deployer.version_manager.rollback(rollback_version)
            _emit_deploy_lineage(
                attempt_id=attempt_id,
                deployment_id=f"rollback-v{rollback_version:03d}",
                version=rollback_version,
                strategy="rollback",
            )
            if json_output:
                click.echo(json_response("ok", {"version": rollback_version, "strategy": "rollback", "status": "rolled_back"}, next_cmd="agentlab status"))
            else:
                click.echo(click.style(f"Applied: rolled back canary v{rollback_version:03d}", fg="green"))
            return

        active_version = deployer.version_manager.manifest.get("active_version")
        if config_version is None:
            deployable_candidates = [
                entry["version"]
                for entry in history
                if entry["version"] != active_version
                and entry.get("status") in {"candidate", "evaluated", "canary", "imported"}
            ]
            if strategy == "canary":
                if not deployable_candidates:
                    raise click.ClickException(
                        "No candidate config version available to deploy. "
                        "Run `agentlab optimize --cycles 1`, review/apply a candidate, "
                        "or pass --config-version."
                    )
                config_version = max(deployable_candidates)
            else:
                config_version = history[-1]["version"]
            if not json_output:
                click.echo(f"Deploying latest version: v{config_version:03d}")

        found = None
        for v in history:
            if v["version"] == config_version:
                found = v
                break
        if found is None:
            if json_output:
                click.echo(json_response("error", {"message": f"Version {config_version} not found"}))
            else:
                click.echo(f"Version {config_version} not found.")
            return

        if strategy == "canary" and config_version == active_version:
            raise click.ClickException(
                f"Cannot deploy active version v{config_version:03d} as its own canary. "
                "Choose a non-active candidate version."
            )

        filepath = Path(configs_dir) / found["filename"]
        with filepath.open("r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        scores = found.get("scores", {"composite": 0.0})
        del scores

        if dry_run:
            payload = {"version": config_version, "strategy": strategy, "target": target}
            progress.phase_completed("deploy", message="Dry-run deployment preview ready")
            progress.next_action("agentlab deploy")
            if resolved_output_format == "stream-json":
                return
            if resolved_output_format == "json":
                click.echo(json_response("ok", payload, next_cmd="agentlab deploy"))
            else:
                click.echo("Dry run: deployment preview")
                click.echo(f"  Version:  v{config_version:03d}")
                click.echo(f"  Strategy: {strategy}")
                click.echo(f"  Target:   {target}")
            return

        if not acknowledge and not auto_review:
            PermissionManager().require(
                f"deploy.{strategy}",
                prompt=f"Deploy v{config_version:03d} using the {strategy} strategy?",
                default=False,
            )

        created_release: dict[str, Any] | None = None
        if auto_review:
            from cli.stream2_helpers import ReleaseStore

            created_release = ReleaseStore().create(
                release_experiment_id or f"ship-v{config_version:03d}",
                config_version=config_version,
            )

        if strategy == "immediate":
            deployer.version_manager.promote(config_version)
            _emit_deploy_lineage(
                attempt_id=attempt_id,
                deployment_id=f"promote-v{config_version:03d}",
                version=config_version,
                strategy="immediate",
            )
            progress.phase_completed("deploy", message=f"Deployed v{config_version:03d} immediately")
            progress.next_action("agentlab status")
            if resolved_output_format == "stream-json":
                return
            if resolved_output_format == "json":
                payload = {"version": config_version, "strategy": "immediate", "status": "active"}
                if created_release is not None:
                    payload["release"] = created_release
                click.echo(json_response("ok", payload, next_cmd="agentlab status"))
            else:
                if created_release is not None:
                    click.echo(click.style(f"Applied: created release {created_release['release_id']}", fg="green"))
                click.echo(click.style(f"Applied: deployed v{config_version:03d} immediately (promoted to active).", fg="green"))
        else:
            deployer.version_manager.mark_canary(config_version)
            _emit_deploy_lineage(
                attempt_id=attempt_id,
                deployment_id=f"canary-v{config_version:03d}",
                version=config_version,
                strategy="canary",
            )
            result = f"Deployed v{config_version:03d} as canary (10% traffic)"
            progress.phase_completed("deploy", message=f"Deployed v{config_version:03d} as canary")
            progress.next_action("agentlab status")
            if resolved_output_format == "stream-json":
                return
            if resolved_output_format == "json":
                payload = {"version": config_version, "strategy": "canary", "result": str(result)}
                if created_release is not None:
                    payload["release"] = created_release
                click.echo(json_response("ok", payload, next_cmd="agentlab status"))
            else:
                if created_release is not None:
                    click.echo(click.style(f"Applied: created release {created_release['release_id']}", fg="green"))
                click.echo(click.style(f"Applied: deployed v{config_version:03d} as canary.", fg="green"))
                click.echo(f"  {result}")
