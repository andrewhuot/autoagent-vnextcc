"""CLI commands for unified skill management (core.skills).

Provides commands for managing both build-time and run-time skills:
- List, show, search skills
- Install from marketplace or URL
- Create new skills interactively
- Test skill validation
- Compose multiple skills into skillsets
- Publish skills to marketplace
- Track effectiveness metrics

Usage:
  autoagent skill list [--kind build|runtime] [--domain <domain>] [--tags <tag1,tag2>]
  autoagent skill show <skill-id>
  autoagent skill create --kind build|runtime --interactive
  autoagent skill install <url-or-name>
  autoagent skill test <skill-id>
  autoagent skill compose <skill-ids...> --output skillset.yaml
  autoagent skill publish <skill-id> [--api-key <key>]
  autoagent skill effectiveness <skill-id>
  autoagent skill search <query> [--kind build|runtime]
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import click
import yaml

from cli.json_envelope import render_json_envelope
from core.skills.composer import SkillComposer
from core.skills.marketplace import SkillMarketplace
from core.skills.store import SkillStore
from core.skills.types import SkillKind
from core.skills.validator import SkillValidator
from cli.workspace import DEFAULT_LIFECYCLE_SKILL_DB

# Default database path
DEFAULT_SKILLS_DB = os.environ.get("AUTOAGENT_SKILLS_DB", str(DEFAULT_LIFECYCLE_SKILL_DB))


def _get_store(db_path: str | None = None) -> SkillStore:
    """Get a SkillStore instance with the specified or default DB path."""
    return SkillStore(db_path or DEFAULT_SKILLS_DB)


def _get_marketplace() -> SkillMarketplace:
    """Get a SkillMarketplace instance."""
    return SkillMarketplace()


def _get_validator() -> SkillValidator:
    """Get a SkillValidator instance."""
    return SkillValidator()


def _get_composer() -> SkillComposer:
    """Get a SkillComposer instance."""
    return SkillComposer()


# ---------------------------------------------------------------------------
# skill list
# ---------------------------------------------------------------------------

@click.command("list")
@click.option("--kind", type=click.Choice(["build", "runtime"]), help="Filter by skill kind.")
@click.option("--domain", help="Filter by domain (e.g., customer-support, sales).")
@click.option("--tags", help="Filter by tags (comma-separated).")
@click.option("--status", help="Filter by status (active, draft, deprecated).")
@click.option("--db", default=DEFAULT_SKILLS_DB, show_default=True, help="Skills database path.")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def skill_list(
    kind: str | None,
    domain: str | None,
    tags: str | None,
    status: str | None,
    db: str,
    json_output: bool,
) -> None:
    """List all skills with optional filters.

    Examples:
      autoagent skill list
      autoagent skill list --kind build
      autoagent skill list --domain customer-support --tags routing,safety
      autoagent skill list --status active --json
    """
    store = _get_store(db)

    try:
        skill_kind = SkillKind(kind) if kind else None
        tag_list = tags.split(",") if tags else None

        skills = store.list(
            kind=skill_kind,
            domain=domain,
            tags=tag_list,
            status=status,
        )

        if not skills:
            if json_output:
                click.echo(render_json_envelope("ok", []))
            else:
                click.echo("No skills found.")
            return

        if json_output:
            data = [
                {
                    "id": s.id,
                    "name": s.name,
                    "kind": s.kind.value,
                    "version": s.version,
                    "domain": s.domain,
                    "status": s.status,
                    "tags": s.tags,
                    "effectiveness": {
                        "times_applied": s.effectiveness.times_applied,
                        "success_rate": s.effectiveness.success_rate,
                        "avg_improvement": s.effectiveness.avg_improvement,
                    },
                }
                for s in skills
            ]
            click.echo(render_json_envelope("ok", data))
            return

        # Table output
        click.echo(f"\nSkills ({len(skills)} found)\n")
        click.echo(f"{'Name':<35} {'Kind':<8} {'Ver':<8} {'Domain':<15} {'Applied':<8} {'Success':<10} {'Status':<10}")
        click.echo("─" * 105)

        for skill in skills:
            eff = skill.effectiveness
            success_rate = f"{eff.success_rate:.1%}" if eff.times_applied > 0 else "—"

            click.echo(
                f"{skill.name:<35} {skill.kind.value:<8} {skill.version:<8} "
                f"{skill.domain:<15} {eff.times_applied:<8} {success_rate:<10} {skill.status:<10}"
            )

    finally:
        store.close()


# ---------------------------------------------------------------------------
# skill show
# ---------------------------------------------------------------------------

@click.command("show")
@click.argument("skill_id")
@click.option("--db", default=DEFAULT_SKILLS_DB, show_default=True, help="Skills database path.")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def skill_show(skill_id: str, db: str, json_output: bool) -> None:
    """Show detailed information about a skill.

    Examples:
      autoagent skill show keyword_expansion
      autoagent skill show my-skill-123 --json
    """
    store = _get_store(db)

    try:
        skill = store.get(skill_id)

        if skill is None:
            click.echo(f"Skill not found: {skill_id}", err=True)
            raise SystemExit(1)

        if json_output:
            click.echo(json.dumps(skill.to_dict(), indent=2))
            return

        # YAML output for readability
        click.echo(yaml.dump(skill.to_dict(), default_flow_style=False, sort_keys=False, allow_unicode=True))

    finally:
        store.close()


# ---------------------------------------------------------------------------
# skill create
# ---------------------------------------------------------------------------

@click.command("create")
@click.option("--kind", type=click.Choice(["build", "runtime"]), required=True, help="Skill kind.")
@click.option("--interactive", is_flag=True, help="Create skill interactively with prompts.")
@click.option("--from-file", type=click.Path(exists=True), help="Create from YAML file.")
@click.option("--db", default=DEFAULT_SKILLS_DB, show_default=True, help="Skills database path.")
def skill_create(kind: str, interactive: bool, from_file: str | None, db: str) -> None:
    """Create a new skill.

    Examples:
      autoagent skill create --kind build --interactive
      autoagent skill create --kind runtime --from-file my_skill.yaml
    """
    if from_file:
        # Load from YAML file
        from core.skills.loader import SkillLoader
        loader = SkillLoader()
        skills = loader.load_from_yaml(from_file)

        if not skills:
            click.echo(f"No skills found in {from_file}", err=True)
            raise SystemExit(1)

        store = _get_store(db)
        try:
            for skill in skills:
                skill_id = store.create(skill)
                click.echo(f"Created skill: {skill.name} (ID: {skill_id})")
        finally:
            store.close()
        return

    if interactive:
        click.echo("Interactive skill creation is not yet implemented.")
        click.echo("Please create a YAML file and use --from-file option.")
        click.echo("\nExample YAML structure:")

        if kind == "build":
            example = {
                "skills": [
                    {
                        "id": "my_build_skill",
                        "name": "My Build Skill",
                        "kind": "build",
                        "version": "1.0.0",
                        "description": "Description of what this skill does",
                        "domain": "general",
                        "tags": ["optimization", "quality"],
                        "mutations": [
                            {
                                "name": "example_mutation",
                                "description": "What this mutation does",
                                "target_surface": "instruction",
                                "operator_type": "append",
                                "template": "Template content here",
                            }
                        ],
                        "triggers": [
                            {
                                "failure_family": "quality_issue",
                            }
                        ],
                        "eval_criteria": [
                            {
                                "metric": "quality",
                                "target": 0.8,
                                "operator": "gte",
                            }
                        ],
                    }
                ]
            }
        else:
            example = {
                "skills": [
                    {
                        "id": "my_runtime_skill",
                        "name": "My Runtime Skill",
                        "kind": "runtime",
                        "version": "1.0.0",
                        "description": "Description of what this skill does",
                        "domain": "general",
                        "tags": ["tool", "utility"],
                        "instructions": "Instructions for using this skill",
                        "tools": [
                            {
                                "name": "example_tool",
                                "description": "What this tool does",
                                "parameters": {},
                                "sandbox_policy": "read_only",
                            }
                        ],
                    }
                ]
            }

        click.echo(yaml.dump(example, default_flow_style=False, sort_keys=False, allow_unicode=True))
        return

    click.echo("Please specify either --interactive or --from-file", err=True)
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# skill install
# ---------------------------------------------------------------------------

@click.command("install")
@click.argument("source")
@click.option("--db", default=DEFAULT_SKILLS_DB, show_default=True, help="Skills database path.")
def skill_install(source: str, db: str) -> None:
    """Install a skill from marketplace, URL, or file.

    Source can be:
    - Marketplace skill ID: keyword_expansion
    - URL: https://example.com/skills/my_skill.yaml
    - Local file: ./skills/my_skill.yaml

    Examples:
      autoagent skill install keyword_expansion
      autoagent skill install https://example.com/skills/routing_fix.yaml
      autoagent skill install ./my_custom_skill.yaml
    """
    store = _get_store(db)
    marketplace = _get_marketplace()

    try:
        skill = marketplace.install(source, store)
        click.echo(f"Successfully installed: {skill.name} v{skill.version} (ID: {skill.id})")

    except Exception as e:
        click.echo(f"Installation failed: {e}", err=True)
        raise SystemExit(1)
    finally:
        store.close()


# ---------------------------------------------------------------------------
# skill test
# ---------------------------------------------------------------------------

@click.command("test")
@click.argument("skill_id")
@click.option("--db", default=DEFAULT_SKILLS_DB, show_default=True, help="Skills database path.")
@click.option("--full", is_flag=True, help="Run full validation including dependencies.")
def skill_test(skill_id: str, db: str, full: bool) -> None:
    """Validate and test a skill.

    Examples:
      autoagent skill test keyword_expansion
      autoagent skill test my-skill --full
    """
    store = _get_store(db)
    validator = _get_validator()

    try:
        skill = store.get(skill_id)

        if skill is None:
            click.echo(f"Skill not found: {skill_id}", err=True)
            raise SystemExit(1)

        click.echo(f"Validating skill: {skill.name} v{skill.version}")

        if full:
            result = validator.validate_full(skill, store)
        else:
            result = validator.validate_schema(skill)

        # Print results
        if result.is_valid:
            click.echo(click.style("✓ Validation passed", fg="green", bold=True))
        else:
            click.echo(click.style("✗ Validation failed", fg="red", bold=True))

        if result.errors:
            click.echo("\nErrors:")
            for error in result.errors:
                click.echo(click.style(f"  • {error}", fg="red"))

        if result.warnings:
            click.echo("\nWarnings:")
            for warning in result.warnings:
                click.echo(click.style(f"  • {warning}", fg="yellow"))

        if result.test_results:
            click.echo("\nTest Results:")
            for test_name, passed in result.test_results.items():
                status = click.style("✓ PASS", fg="green") if passed else click.style("✗ FAIL", fg="red")
                click.echo(f"  {test_name}: {status}")

        if not result.is_valid:
            raise SystemExit(1)

    finally:
        store.close()


# ---------------------------------------------------------------------------
# skill compose
# ---------------------------------------------------------------------------

@click.command("compose")
@click.argument("skill_ids", nargs=-1, required=True)
@click.option("--output", required=True, help="Output YAML file path.")
@click.option("--name", default="composed_skillset", help="Name for the skillset.")
@click.option("--description", default="", help="Description for the skillset.")
@click.option("--db", default=DEFAULT_SKILLS_DB, show_default=True, help="Skills database path.")
def skill_compose(skill_ids: tuple[str, ...], output: str, name: str, description: str, db: str) -> None:
    """Compose multiple skills into a skillset.

    Examples:
      autoagent skill compose skill1 skill2 skill3 --output my_skillset.yaml
      autoagent skill compose routing_fix safety_guard --name "Core Skillset" --output core.yaml
    """
    if not skill_ids:
        click.echo("Please provide at least one skill ID", err=True)
        raise SystemExit(1)

    store = _get_store(db)
    composer = _get_composer()

    try:
        # Load all skills
        skills = []
        for skill_id in skill_ids:
            skill = store.get(skill_id)
            if skill is None:
                click.echo(f"Skill not found: {skill_id}", err=True)
                raise SystemExit(1)
            skills.append(skill)

        click.echo(f"Composing {len(skills)} skills...")

        # Compose
        try:
            skillset = composer.compose(
                skills=skills,
                store=store,
                name=name,
                description=description,
            )
        except ValueError as e:
            click.echo(f"Composition failed: {e}", err=True)
            raise SystemExit(1)

        # Report conflicts
        if skillset.conflicts:
            click.echo(f"\n⚠ Found {len(skillset.conflicts)} conflict(s):")
            for conflict in skillset.conflicts:
                severity_color = "red" if conflict.severity.value == "error" else "yellow"
                click.echo(click.style(
                    f"  [{conflict.severity.value.upper()}] {conflict.description}",
                    fg=severity_color,
                ))

        if not skillset.validate():
            click.echo("\n✗ Skillset validation failed - cannot compose due to blocking conflicts", err=True)
            raise SystemExit(1)

        # Save to file
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(skillset.to_yaml(), encoding="utf-8")

        click.echo(f"\n✓ Successfully composed skillset: {name}")
        click.echo(f"  Output: {output}")
        click.echo(f"  Skills: {len(skillset.skills)}")
        click.echo(f"  Conflicts: {len(skillset.conflicts)}")

    finally:
        store.close()


# ---------------------------------------------------------------------------
# skill publish
# ---------------------------------------------------------------------------

@click.command("publish")
@click.argument("skill_id")
@click.option("--api-key", help="API key for marketplace authentication.")
@click.option("--db", default=DEFAULT_SKILLS_DB, show_default=True, help="Skills database path.")
def skill_publish(skill_id: str, api_key: str | None, db: str) -> None:
    """Publish a skill to the marketplace.

    Examples:
      autoagent skill publish my_skill
      autoagent skill publish my_skill --api-key <key>
    """
    store = _get_store(db)
    marketplace = _get_marketplace()

    try:
        skill = store.get(skill_id)

        if skill is None:
            click.echo(f"Skill not found: {skill_id}", err=True)
            raise SystemExit(1)

        click.echo(f"Publishing skill: {skill.name} v{skill.version}")

        try:
            success = marketplace.publish(skill, api_key=api_key)
            if success:
                click.echo(click.style("✓ Successfully published to marketplace", fg="green"))
            else:
                click.echo(click.style("✗ Publishing failed", fg="red"), err=True)
                raise SystemExit(1)

        except Exception as e:
            click.echo(f"Publishing failed: {e}", err=True)
            raise SystemExit(1)

    finally:
        store.close()


# ---------------------------------------------------------------------------
# skill effectiveness
# ---------------------------------------------------------------------------

@click.command("effectiveness")
@click.argument("skill_id")
@click.option("--db", default=DEFAULT_SKILLS_DB, show_default=True, help="Skills database path.")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def skill_effectiveness(skill_id: str, db: str, json_output: bool) -> None:
    """Show effectiveness metrics for a skill.

    Examples:
      autoagent skill effectiveness keyword_expansion
      autoagent skill effectiveness my_skill --json
    """
    store = _get_store(db)

    try:
        skill = store.get(skill_id)

        if skill is None:
            click.echo(f"Skill not found: {skill_id}", err=True)
            raise SystemExit(1)

        metrics = skill.effectiveness

        if json_output:
            data = {
                "skill_id": skill.id,
                "skill_name": skill.name,
                "times_applied": metrics.times_applied,
                "success_count": metrics.success_count,
                "success_rate": metrics.success_rate,
                "avg_improvement": metrics.avg_improvement,
                "total_improvement": metrics.total_improvement,
                "last_applied": metrics.last_applied,
            }
            click.echo(json.dumps(data, indent=2))
            return

        # Rich formatted output
        click.echo(f"\nEffectiveness Metrics: {skill.name} v{skill.version}")
        click.echo("=" * 60)
        click.echo(f"  Times Applied:     {metrics.times_applied}")
        click.echo(f"  Success Count:     {metrics.success_count}")
        click.echo(f"  Success Rate:      {metrics.success_rate:.1%}")
        click.echo(f"  Avg Improvement:   {metrics.avg_improvement:+.4f}")
        click.echo(f"  Total Improvement: {metrics.total_improvement:+.4f}")

        if metrics.last_applied:
            from datetime import datetime, timezone
            last_applied_dt = datetime.fromtimestamp(metrics.last_applied, tz=timezone.utc)
            click.echo(f"  Last Applied:      {last_applied_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        else:
            click.echo(f"  Last Applied:      Never")

    finally:
        store.close()


# ---------------------------------------------------------------------------
# skill search
# ---------------------------------------------------------------------------

@click.command("search")
@click.argument("query")
@click.option("--kind", type=click.Choice(["build", "runtime"]), help="Filter by skill kind.")
@click.option("--db", default=DEFAULT_SKILLS_DB, show_default=True, help="Skills database path.")
@click.option("--marketplace", is_flag=True, help="Search marketplace instead of local store.")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def skill_search(query: str, kind: str | None, db: str, marketplace: bool, json_output: bool) -> None:
    """Search for skills by query string.

    Searches across skill names, descriptions, capabilities, and tags.

    Examples:
      autoagent skill search routing
      autoagent skill search "safety policy" --kind build
      autoagent skill search refund --marketplace
    """
    if marketplace:
        mp = _get_marketplace()
        skill_kind = SkillKind(kind) if kind else None
        results = mp.search(query, kind=skill_kind)

        if not results:
            if json_output:
                click.echo(json.dumps([], indent=2))
            else:
                click.echo("No skills found in marketplace.")
            return

        if json_output:
            click.echo(json.dumps(results, indent=2))
            return

        # Table output for marketplace metadata
        click.echo(f"\nMarketplace Search Results ({len(results)} found)\n")
        click.echo(f"{'Name':<35} {'Kind':<8} {'Version':<10} {'Description':<50}")
        click.echo("─" * 105)

        for metadata in results:
            desc = metadata.get("description", "")
            desc = desc[:47] + "..." if len(desc) > 50 else desc
            click.echo(
                f"{metadata.get('name', ''):<35} {metadata.get('kind', ''):<8} "
                f"{metadata.get('version', ''):<10} {desc:<50}"
            )
        return

    # Search local store
    store = _get_store(db)

    try:
        skill_kind = SkillKind(kind) if kind else None
        skills = store.search(query, kind=skill_kind)

        if not skills:
            if json_output:
                click.echo(json.dumps([], indent=2))
            else:
                click.echo("No skills found.")
            return

        if json_output:
            data = [
                {
                    "id": s.id,
                    "name": s.name,
                    "kind": s.kind.value,
                    "version": s.version,
                    "description": s.description,
                    "domain": s.domain,
                    "tags": s.tags,
                }
                for s in skills
            ]
            click.echo(json.dumps(data, indent=2))
            return

        # Table output
        click.echo(f"\nSearch Results ({len(skills)} found)\n")
        click.echo(f"{'Name':<35} {'Kind':<8} {'Version':<10} {'Description':<50}")
        click.echo("─" * 105)

        for skill in skills:
            desc = skill.description[:47] + "..." if len(skill.description) > 50 else skill.description
            click.echo(
                f"{skill.name:<35} {skill.kind.value:<8} {skill.version:<10} {desc:<50}"
            )

    finally:
        store.close()


# ---------------------------------------------------------------------------
# skill recommend
# ---------------------------------------------------------------------------

@click.command("recommend")
@click.option("--failure-family", help="Filter by failure family (e.g., routing_error, hallucination).")
@click.option("--metric", help="Filter by metric name.")
@click.option("--db", default=DEFAULT_SKILLS_DB, show_default=True, help="Skills database path.")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def skill_recommend(
    failure_family: str | None,
    metric: str | None,
    db: str,
    json_output: bool,
) -> None:
    """Recommend skills based on failure patterns or metrics.

    Examples:
      autoagent skill recommend
      autoagent skill recommend --failure-family routing_error
      autoagent skill recommend --metric accuracy --json
    """
    store = _get_store(db)

    try:
        # Get all active build skills
        all_skills = store.list(kind=SkillKind.BUILD, status="active")

        # Filter by triggers if criteria provided
        matching_skills = []
        if failure_family or metric:
            for skill in all_skills:
                for trigger in skill.triggers:
                    if failure_family and trigger.failure_family == failure_family:
                        matching_skills.append(skill)
                        break
                    if metric and trigger.metric_name == metric:
                        matching_skills.append(skill)
                        break
        else:
            # No filters, return all
            matching_skills = all_skills

        if not matching_skills:
            if json_output:
                click.echo(render_json_envelope("ok", []))
            else:
                click.echo("No matching skills found.")
            return

        if json_output:
            # Format for JSON output as expected by tests
            data = [
                {
                    "name": s.name,
                    "category": s.domain,
                    "description": s.description,
                    "proven_improvement": s.effectiveness.avg_improvement,
                }
                for s in matching_skills
            ]
            click.echo(render_json_envelope("ok", data))
            return

        # Table output
        click.echo(f"\nRecommended Skills ({len(matching_skills)} found)\n")
        click.echo(f"{'Name':<35} {'Domain':<20} {'Avg Improvement':<15} {'Success Rate':<15}")
        click.echo("─" * 90)

        for skill in matching_skills:
            click.echo(
                f"{skill.name:<35} {skill.domain:<20} "
                f"{skill.effectiveness.avg_improvement:<15.3f} "
                f"{skill.effectiveness.success_rate:<15.3f}"
            )

    finally:
        store.close()


# ---------------------------------------------------------------------------
# skill review (draft skill promotion)
# ---------------------------------------------------------------------------

@click.command("review")
@click.option("--db", default=DEFAULT_SKILLS_DB, show_default=True, help="Skills database path.")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
@click.option("--min-effectiveness", type=float, help="Filter by minimum success rate.")
def skill_review(db: str, json_output: bool, min_effectiveness: float | None) -> None:
    """Interactive review of draft skills for promotion.

    Examples:
      autoagent skill review
      autoagent skill review --min-effectiveness 0.5
      autoagent skill review --json
    """
    from core.skills.promotion import SkillPromotionWorkflow

    store = _get_store(db)
    workflow = SkillPromotionWorkflow(store=store)

    try:
        drafts = workflow.list_draft_skills(min_effectiveness=min_effectiveness)

        if not drafts:
            if json_output:
                click.echo(json.dumps([], indent=2))
            else:
                click.echo("No draft skills found for review.")
            return

        if json_output:
            data = [
                {
                    "skill_id": d["skill"].id,
                    "name": d["skill"].name,
                    "source": d["source"],
                    "source_improvement": d["source_improvement"],
                    "times_applied": d["times_applied"],
                    "success_rate": d["success_rate"],
                    "avg_improvement": d["avg_improvement"],
                }
                for d in drafts
            ]
            click.echo(json.dumps(data, indent=2))
            return

        # Table output
        click.echo(click.style("\n📋 Draft Skills for Review", fg="cyan", bold=True))
        click.echo(f"\nFound {len(drafts)} draft skills\n")
        click.echo(f"{'Name':<30} {'Source':<20} {'Applied':<8} {'Success':<10} {'Avg Δ':<10}")
        click.echo("─" * 85)

        for draft in drafts:
            skill = draft["skill"]
            source = draft["source"][:17] + "..." if len(draft["source"]) > 20 else draft["source"]
            success_rate = f"{draft['success_rate']:.1%}" if draft["times_applied"] > 0 else "—"
            avg_improvement = f"+{draft['avg_improvement']:.3f}" if draft["avg_improvement"] > 0 else f"{draft['avg_improvement']:.3f}"

            click.echo(
                f"{skill.name:<30} {source:<20} {draft['times_applied']:<8} "
                f"{success_rate:<10} {avg_improvement:<10}"
            )

        click.echo("\nUse 'autoagent skill promote <id>' to promote a draft to active.")
        click.echo("Use 'autoagent skill archive <id>' to archive (reject) a draft.")

    finally:
        store.close()


@click.command("promote")
@click.argument("skill_id")
@click.option("--reason", default="", help="Reason for promotion.")
@click.option("--db", default=DEFAULT_SKILLS_DB, show_default=True, help="Skills database path.")
def skill_promote(skill_id: str, reason: str, db: str) -> None:
    """Promote a draft skill to active status.

    Examples:
      autoagent skill promote autolearn-abc123
      autoagent skill promote autolearn-abc123 --reason "Proven effective"
    """
    from core.skills.promotion import SkillPromotionWorkflow

    store = _get_store(db)
    workflow = SkillPromotionWorkflow(store=store)

    try:
        # Get draft details first
        details = workflow.get_draft_details(skill_id)
        if not details:
            click.echo(click.style("✗ ", fg="red") + f"Draft skill not found: {skill_id}")
            return

        skill = details["skill"]
        click.echo(click.style("\n⚡ Promoting Skill", fg="cyan", bold=True))
        click.echo(f"\nSkill: {click.style(skill.name, fg='cyan')}")
        click.echo(f"ID: {skill_id}")
        click.echo(f"Source: {details['source']}")
        click.echo(f"Success rate: {details['effectiveness']['success_rate']:.1%}")
        click.echo("")

        # Promote
        success = workflow.promote_skill(skill_id, reason=reason)

        if success:
            click.echo(click.style("✓ ", fg="green") + "Successfully promoted to active")
            if reason:
                click.echo(f"Reason: {reason}")
        else:
            click.echo(click.style("✗ ", fg="red") + "Failed to promote skill")

    finally:
        store.close()


@click.command("archive")
@click.argument("skill_id")
@click.option("--reason", required=True, help="Reason for archiving (required).")
@click.option("--db", default=DEFAULT_SKILLS_DB, show_default=True, help="Skills database path.")
def skill_archive(skill_id: str, reason: str, db: str) -> None:
    """Archive (reject) a draft skill.

    Examples:
      autoagent skill archive autolearn-abc123 --reason "Not effective enough"
    """
    from core.skills.promotion import SkillPromotionWorkflow

    store = _get_store(db)
    workflow = SkillPromotionWorkflow(store=store)

    try:
        # Get draft details first
        details = workflow.get_draft_details(skill_id)
        if not details:
            click.echo(click.style("✗ ", fg="red") + f"Draft skill not found: {skill_id}")
            return

        skill = details["skill"]
        click.echo(click.style("\n🗄️  Archiving Skill", fg="yellow", bold=True))
        click.echo(f"\nSkill: {click.style(skill.name, fg='yellow')}")
        click.echo(f"ID: {skill_id}")
        click.echo(f"Reason: {reason}")
        click.echo("")

        # Archive
        success = workflow.archive_skill(skill_id, reason=reason)

        if success:
            click.echo(click.style("✓ ", fg="green") + "Successfully archived")
        else:
            click.echo(click.style("✗ ", fg="red") + "Failed to archive skill")

    finally:
        store.close()


# ---------------------------------------------------------------------------
# Command registration helper
# ---------------------------------------------------------------------------

def register_skill_commands(cli_group: click.Group) -> None:
    """Register all skill commands to a Click group.

    Args:
        cli_group: The Click group to register commands to.
    """
    commands = [
        skill_list,
        skill_show,
        skill_create,
        skill_install,
        skill_test,
        skill_compose,
        skill_publish,
        skill_effectiveness,
        skill_search,
        skill_recommend,
        skill_review,
        skill_promote,
        skill_archive,
    ]

    for cmd in commands:
        cli_group.add_command(cmd)
