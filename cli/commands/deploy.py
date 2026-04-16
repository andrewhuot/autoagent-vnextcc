"""`agentlab deploy` command.

Extracted from runner.py in R2 Slice C.4 — the final runner.py
extraction. register_deploy_commands(cli) is called from
cli.commands.register_all().

Preserves R1 invariants: --force-deploy-degraded / --reason gating
and lineage emission via --attempt-id (Slice A.5).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
import yaml


def _runner_module():
    """Late-bound import of runner to avoid circular imports."""
    import runner as _r
    return _r


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
        from cli.output import resolve_output_format
        from cli.permissions import PermissionManager
        from cli.progress import ProgressRenderer

        resolved_output_format = resolve_output_format(output_format, json_output=json_output)
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
