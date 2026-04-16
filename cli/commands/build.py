"""`agentlab build` commands.

Extracted from runner.py in R2 Slice C.1. register_build_commands(cli)
is called from cli.commands.register_all().
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import click
import yaml


def _runner_module():
    """Late-bound import of runner to avoid circular imports."""
    import runner as _r
    return _r


def _build_show_impl(
    selector: str,
    json_output: bool = False,
    id_only: bool = False,
    path_only: bool = False,
) -> None:
    """Render build-show style output for both canonical and legacy routes."""
    from cli.stream2_helpers import get_latest_build_artifact, json_response

    artifact = get_latest_build_artifact()
    if artifact is None:
        if json_output:
            click.echo(json_response("error", {"message": "No build artifact found"}))
        else:
            click.echo("No build artifact found.")
            click.echo("Run: agentlab build \"Describe your agent\"")
        return

    artifact_path = Path(".agentlab") / "build_artifact_latest.json"
    artifact_id = artifact.get("artifact_id") or artifact.get("id") or selector
    if id_only:
        click.echo(str(artifact_id))
        return
    if path_only:
        click.echo(str(artifact_path))
        return

    if json_output:
        click.echo(json_response("ok", artifact, next_cmd="agentlab eval run"))
        return

    click.echo(click.style("\n✦ Latest Build Artifact", fg="cyan", bold=True))
    click.echo(f"  Prompt:      {artifact.get('source_prompt', '—')}")
    click.echo(f"  Connectors:  {', '.join(artifact.get('connectors', [])) or 'None'}")
    click.echo(f"  Intents:     {len(artifact.get('intents', []))}")
    click.echo(f"  Tools:       {len(artifact.get('tools', []))}")
    click.echo(f"  Guardrails:  {len(artifact.get('guardrails', []))}")
    click.echo(f"  Skills:      {len(artifact.get('skills', []))}")


def register_build_commands(cli: click.Group) -> None:
    """Register the `build` group and the hidden `build-show` alias."""
    runner = _runner_module()
    DefaultCommandGroup = runner.DefaultCommandGroup

    @cli.group("build", cls=DefaultCommandGroup, default_command="run")
    def build_group() -> None:
        """Build agent artifacts or inspect the latest build output.

        Examples:
          agentlab build "Build a support agent for order tracking"
          agentlab build show latest
        """


    @build_group.command("run", hidden=True)
    @click.argument("prompt")
    @click.option(
        "--connector",
        "connectors",
        multiple=True,
        help="Connector to include (repeatable). Example: --connector Shopify",
    )
    @click.option("--output-dir", default=".", show_default=True, help="Directory for generated build artifacts.")
    @click.option(
        "--strict-live/--no-strict-live",
        default=False,
        help="Exit non-zero (12) if the build falls back to pattern matcher (no live LLM).",
    )
    @click.option("--json", "json_output", "-j", is_flag=True, help="Output artifact as JSON only.")
    @click.option(
        "--output-format",
        type=click.Choice(["text", "json", "stream-json"], case_sensitive=False),
        default="text",
        show_default=True,
        help="Render human text, a final JSON envelope, or stream JSON progress events.",
    )
    def build_agent(
        prompt: str,
        connectors: tuple[str, ...],
        output_dir: str,
        strict_live: bool = False,
        json_output: bool = False,
        output_format: str = "text",
    ) -> None:
        """Build an agent artifact from natural language and scaffold eval/deploy handoff files."""
        from cli.output import resolve_output_format
        from cli.progress import PhaseSpinner, ProgressRenderer
        from optimizer.transcript_intelligence import TranscriptIntelligenceService

        resolved_output_format = resolve_output_format(output_format, json_output=json_output)
        progress = ProgressRenderer(output_format=resolved_output_format, render_text=False)
        progress.phase_started("build", message="Generate build artifact from prompt")

        with PhaseSpinner("Preparing workspace", output_format=resolved_output_format) as spinner:
            target = Path(output_dir).resolve()
            workspace = runner.discover_workspace()
            register_in_workspace = workspace is not None and target == workspace.root
            target.mkdir(parents=True, exist_ok=True)
            (target / ".agentlab").mkdir(parents=True, exist_ok=True)
            (target / "configs").mkdir(parents=True, exist_ok=True)
            (target / "evals" / "cases").mkdir(parents=True, exist_ok=True)

            resolved_connectors = [item.strip() for item in connectors if item.strip()]
            if not resolved_connectors:
                resolved_connectors = runner._infer_connectors_from_prompt(prompt)

            spinner.update("Calling LLM to design agent")
            progress.phase_started("build.llm", message="Generate artifact via provider")
            live_artifact, live_model_label, live_failure_reason = runner._build_artifact_live(
                prompt, resolved_connectors
            )
            if live_artifact is not None:
                artifact = live_artifact
                progress.phase_completed(
                    "build.llm",
                    message=f"Generated via {live_model_label}" if live_model_label else "Generated via live LLM",
                )
            else:
                if strict_live:
                    from cli.exit_codes import EXIT_MOCK_FALLBACK
                    from cli.strict_live import MockFallbackError

                    msg = (
                        f"build: live LLM unavailable ({live_failure_reason or 'no provider key'}), "
                        "pattern fallback would be used"
                    )
                    click.echo(MockFallbackError([msg]).args[0], err=True)
                    sys.exit(EXIT_MOCK_FALLBACK)
                service = TranscriptIntelligenceService()
                artifact = service.build_agent_artifact(prompt, resolved_connectors)
                progress.phase_completed(
                    "build.llm",
                    message=(
                        f"Used pattern fallback ({live_failure_reason})"
                        if live_failure_reason
                        else "Used pattern fallback (no provider key)"
                    ),
                )
            artifact["skills"] = runner._build_skill_recommendations(artifact)
            artifact["source_prompt"] = prompt

            spinner.update("Generating eval cases")
            progress.phase_started("build.evals", message="Scaffold eval suite from artifact")
            config = runner._artifact_to_seed_config(prompt, artifact)
            config_yaml = yaml.safe_dump(config, sort_keys=False)
            built_version: int | None = None
            if register_in_workspace and workspace is not None:
                store = runner.ConversationStore(db_path=str(workspace.conversation_db))
                deployer = runner.Deployer(configs_dir=str(workspace.configs_dir), store=store)
                saved_version = deployer.version_manager.save_version(
                    config,
                    scores={"composite": 0.0},
                    status="candidate",
                )
                built_version = saved_version.version
                config_path = workspace.configs_dir / saved_version.filename
                workspace.set_active_config(saved_version.version, filename=saved_version.filename)
            else:
                config_path = runner._next_built_config_path(target / "configs")
                config_path.write_text(config_yaml, encoding="utf-8")
            progress.artifact_written("config", path=str(config_path))

            eval_path = target / "evals" / "cases" / "generated_build.yaml"
            runner._write_generated_eval_cases(eval_path, artifact)
            progress.artifact_written("evals", path=str(eval_path))
            progress.phase_completed("build.evals", message="Eval suite scaffolded")

            spinner.update("Writing build artifacts")
            progress.phase_started("build.artifacts", message="Persist build outputs")
            artifact_path = target / ".agentlab" / "build_artifact_latest.json"
            artifact_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
            progress.artifact_written("artifact", path=str(artifact_path))
            spinner.update("Build complete")

        prompt_summary = " ".join(prompt.split())
        title = prompt_summary[:72] if len(prompt_summary) <= 72 else f"{prompt_summary[:69]}..."
        build_artifact_store = runner.BuildArtifactStore(
            path=target / ".agentlab" / "build_artifacts.json",
            latest_path=artifact_path,
        )
        build_artifact_store.save_latest(
            runner.BuildArtifact(
                id=f"build-{uuid.uuid4().hex[:12]}",
                created_at=datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
                updated_at=datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
                source="cli",
                status="complete",
                config_yaml=config_yaml,
                prompt_used=prompt,
                eval_draft=str(eval_path),
                starter_config_path=str(config_path),
                selector="latest",
                metadata={
                    "title": title or "CLI Build Artifact",
                    "summary": "CLI build generated from a natural-language prompt.",
                    "connectors": artifact.get("connectors", []),
                    "intents": artifact.get("intents", []),
                    "tools": artifact.get("tools", []),
                    "guardrails": artifact.get("guardrails", []),
                    "skills": artifact.get("skills", []),
                    "integration_templates": artifact.get("integration_templates", []),
                    "legacy_payload": artifact,
                },
            ),
            legacy_payload=artifact,
        )
        progress.phase_completed("build.artifacts", message="Wrote build outputs")
        progress.phase_completed("build", message="Build artifact ready")
        progress.next_action("agentlab eval run")

        if resolved_output_format == "stream-json":
            return

        if resolved_output_format == "json":
            click.echo(json.dumps(artifact, indent=2))
            return

        click.echo(click.style("\n\u2726 AgentLab Build", fg="cyan", bold=True))
        if live_model_label:
            click.echo(click.style(f"  \u2713 Generated with live LLM ({live_model_label})", fg="green"))
        elif live_failure_reason:
            click.echo(
                click.style(
                    f"  \u26a0 Live LLM call failed \u2014 used pattern fallback. Reason: {live_failure_reason}",
                    fg="yellow",
                )
            )
        else:
            click.echo(
                click.style(
                    "  \u2139 No provider key \u2014 used pattern fallback. "
                    "Run `agentlab mode set live` after adding a provider key for LLM-generated configs.",
                    dim=True,
                )
            )
        click.echo(f"Prompt: {prompt}")
        click.echo(f"Connectors: {', '.join(artifact.get('connectors', [])) or 'None'}")
        click.echo("")
        click.echo(click.style("Artifact coverage", bold=True))
        click.echo(f"  Intents:               {len(artifact.get('intents', []))}")
        click.echo(f"  Tools:                 {len(artifact.get('tools', []))}")
        click.echo(f"  Guardrails:            {len(artifact.get('guardrails', []))}")
        click.echo(f"  Skills:                {len(artifact.get('skills', []))}")
        click.echo(f"  Integration templates: {len(artifact.get('integration_templates', []))}")
        click.echo("")
        click.echo(click.style("Generated handoff files", bold=True))
        click.echo(f"  Config:   {config_path}")
        if built_version is not None:
            click.echo(f"  Workspace: v{built_version:03d} (selected locally, not deployed)")
        click.echo(f"  Evals:    {eval_path}")
        click.echo(f"  Artifact: {artifact_path}")
        click.echo("")
        click.echo(click.style("Next step:", bold=True))
        if register_in_workspace:
            click.echo("  agentlab eval run")
        else:
            click.echo(f"  agentlab eval run --config {config_path}")
        click.echo("  agentlab optimize --cycles 3")
        click.echo("  agentlab deploy canary --yes")
        click.echo("  agentlab review show pending")


    @build_group.command("show")
    @click.argument("selector", default="latest")
    @click.option("--id-only", is_flag=True, help="Print only the resolved artifact identifier.")
    @click.option("--path-only", is_flag=True, help="Print only the resolved artifact path.")
    @click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
    def build_show(selector: str, id_only: bool, path_only: bool, json_output: bool = False) -> None:
        """Show build output. Currently supports 'latest'.

        Examples:
          agentlab build show latest
          agentlab build show latest --json
        """
        _build_show_impl(selector, json_output=json_output, id_only=id_only, path_only=path_only)


    @cli.command("build-show", hidden=True)
    @click.argument("selector", default="latest")
    @click.option("--id-only", is_flag=True, help="Print only the resolved artifact identifier.")
    @click.option("--path-only", is_flag=True, help="Print only the resolved artifact path.")
    @click.option("--json", "json_output", "-j", is_flag=True, help="Output as JSON.")
    def build_show_alias(selector: str, id_only: bool, path_only: bool, json_output: bool = False) -> None:
        """Deprecated alias for `agentlab build show`."""
        if not json_output:
            runner._echo_deprecation(f"agentlab build-show {selector}", f"agentlab build show {selector}")
        _build_show_impl(selector, json_output=json_output, id_only=id_only, path_only=path_only)
