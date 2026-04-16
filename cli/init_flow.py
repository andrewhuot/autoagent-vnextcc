"""Guided init flow: import agent → card → eval cases → coverage → first eval.

Invoked via `agentlab init [PATH]`. Takes a user from "I have an agent" to
"I have eval results" in one command.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cli.provider_keys import validate_provider_key
from cli.workspace_env import (
    PROVIDER_API_KEY_ENV_VARS,
    hydrate_provider_key_aliases,
    write_workspace_env_values,
)

_MAX_KEY_ATTEMPTS = 3


@dataclass
class InitResult:
    """Outcome of the init flow."""

    agent_name: str = ""
    card_path: str = ""
    cases_generated: int = 0
    gaps_filled: int = 0
    eval_mode: str = ""  # "real" or "mock"
    steps_completed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str = ""


class InitFlow:
    """Guided init: import → card → eval cases → coverage → first eval."""

    def __init__(
        self,
        workspace: str | Path = ".",
        *,
        skip_eval: bool = False,
        skip_generate: bool = False,
        force_mock: bool = False,
        interactive: bool = True,
        output_fn: Any = None,
    ) -> None:
        self.workspace = Path(workspace)
        self.skip_eval = skip_eval
        self.skip_generate = skip_generate
        self.force_mock = force_mock
        self.interactive = interactive
        self._print = output_fn or print

    def run(self, agent_source: str | None = None) -> InitResult:
        """Execute the full init flow."""
        result = InitResult()

        try:
            # Step 1: Detect and load agent config
            config, agent_name = self._step_import(agent_source, result)
            if config is None:
                return result

            # Step 2: Generate Agent Card
            card = self._step_generate_card(config, agent_name, result)
            if card is None:
                return result

            # Step 3: Generate test cases
            if not self.skip_generate:
                cases = self._step_generate_cases(card, result)
                # Step 4: Coverage analysis + gap fill
                if cases:
                    self._step_coverage(card, cases, result)

            # Step 4.5: Provider key setup (inline) — ensures users don't
            # silently land in mock mode just because they skipped key entry.
            self._step_provider_key(result)

            # Step 5: Suggest next steps
            self._step_suggest(result)

        except Exception as exc:
            result.error = str(exc)
            self._print(f"\nError: {exc}")

        return result

    def _step_import(
        self,
        agent_source: str | None,
        result: InitResult,
    ) -> tuple[dict | None, str]:
        """Detect source and load config."""
        self._print("\n[1/5] Detecting agent source...")

        source_path = Path(agent_source) if agent_source else None

        if source_path is None:
            source_path = self._auto_detect()

        if source_path is None:
            self._print("  No agent found. Creating starter config.")
            config = _starter_config()
            result.agent_name = "my_agent"
            result.steps_completed.append("import:starter")
            return config, "my_agent"

        if source_path.is_dir() and (source_path / "agent.py").exists():
            return self._import_adk(source_path, result)

        if source_path.is_file() and source_path.suffix in (".yaml", ".yml"):
            return self._import_yaml(source_path, result)

        self._print(f"  Unknown source: {source_path}. Using starter config.")
        result.warnings.append(f"Unknown source type: {source_path}")
        config = _starter_config()
        result.agent_name = "my_agent"
        result.steps_completed.append("import:starter")
        return config, "my_agent"

    def _import_adk(
        self, path: Path, result: InitResult,
    ) -> tuple[dict | None, str]:
        self._print(f"  Found ADK agent: {path}")
        try:
            from adk.importer import AdkImporter
            import yaml

            importer = AdkImporter()
            imp = importer.import_agent(
                str(path),
                output_dir=str(self.workspace / "configs"),
                save_snapshot=True,
            )
            self._print(f"  Imported '{imp.agent_name}' ({imp.tools_imported} tools)")
            result.agent_name = imp.agent_name
            result.steps_completed.append("import:adk")

            config_path = Path(imp.config_path)
            if config_path.is_file():
                return yaml.safe_load(config_path.read_text()), imp.agent_name
        except Exception as exc:
            self._print(f"  ADK import failed: {exc}")
            result.warnings.append(f"ADK import error: {exc}")

        return _starter_config(), path.name

    def _import_yaml(
        self, path: Path, result: InitResult,
    ) -> tuple[dict | None, str]:
        self._print(f"  Loading config: {path}")
        try:
            import yaml
            config = yaml.safe_load(path.read_text())
            if not isinstance(config, dict):
                config = _starter_config()
            name = config.get("name", config.get("agent_name", path.stem))
            result.agent_name = name
            result.steps_completed.append("import:yaml")
            return config, name
        except Exception as exc:
            self._print(f"  YAML load failed: {exc}")
            result.warnings.append(str(exc))
            return _starter_config(), path.stem

    def _step_generate_card(
        self, config: dict, name: str, result: InitResult,
    ) -> Any:
        """Generate and persist Agent Card."""
        self._print("\n[2/5] Generating Agent Card...")
        try:
            from agent_card.persistence import generate_and_save_from_config

            card = generate_and_save_from_config(
                config, name=name, workspace=str(self.workspace),
                reason="agentlab init",
            )
            card_path = str(self.workspace / ".agentlab" / "agent_card.md")
            result.card_path = card_path
            result.steps_completed.append("card:generated")

            summary = card.surface_summary()
            self._print(f"  Agent: {card.name}")
            for label, key in [
                ("Sub-agents", "sub_agents"),
                ("Tools", "tools"),
                ("Routing rules", "routing_rules"),
                ("Guardrails", "guardrails"),
            ]:
                self._print(f"  {label}: {summary.get(key, 0)}")
            self._print(f"  Saved: {card_path}")
            return card
        except Exception as exc:
            self._print(f"  Card generation failed: {exc}")
            result.warnings.append(str(exc))
            return None

    def _step_generate_cases(
        self, card: Any, result: InitResult,
    ) -> list[Any]:
        """Generate test cases from card."""
        self._print("\n[3/5] Generating eval test cases...")
        try:
            from evals.card_case_generator import CardCaseGenerator

            gen = CardCaseGenerator()
            cases = gen.generate_all(card, count_per_category=5)
            result.cases_generated = len(cases)
            result.steps_completed.append(f"cases:generated({len(cases)})")

            # Export
            out_dir = self.workspace / "evals" / "cases"
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = str(out_dir / "generated_from_card.yaml")
            gen.export_to_yaml(cases, out_path)
            self._print(f"  Generated {len(cases)} test cases → {out_path}")

            # Category breakdown
            by_cat: dict[str, int] = {}
            for c in cases:
                cat = getattr(c, "category", "unknown")
                by_cat[cat] = by_cat.get(cat, 0) + 1
            for cat in sorted(by_cat):
                self._print(f"    {cat}: {by_cat[cat]}")

            return cases
        except Exception as exc:
            self._print(f"  Case generation failed: {exc}")
            result.warnings.append(str(exc))
            return []

    def _step_coverage(
        self, card: Any, cases: list[Any], result: InitResult,
    ) -> None:
        """Analyze coverage and fill gaps."""
        self._print("\n[4/5] Analyzing coverage...")
        try:
            from evals.coverage_analyzer import CoverageAnalyzer

            analyzer = CoverageAnalyzer()
            case_dicts = [
                {
                    "id": getattr(c, "id", ""),
                    "category": getattr(c, "category", ""),
                    "user_message": getattr(c, "user_message", ""),
                    "expected_specialist": getattr(c, "expected_specialist", ""),
                    "expected_tool": getattr(c, "expected_tool", None),
                    "safety_probe": getattr(c, "safety_probe", False),
                    "expected_behavior": getattr(c, "expected_behavior", ""),
                }
                for c in cases
            ]

            report = analyzer.analyze(card, case_dicts)
            self._print(f"  Coverage: {report.overall_score:.0%}")
            self._print(f"  Gaps: {len(report.gaps)} ({len(report.critical_gaps)} critical)")

            if report.critical_gaps or report.high_gaps:
                from evals.card_case_generator import CardCaseGenerator
                gen = CardCaseGenerator()
                new_cases = analyzer.fill_gaps(card, case_dicts, gen)
                if new_cases:
                    result.gaps_filled = len(new_cases)
                    self._print(f"  Filled {len(new_cases)} gaps")
                    result.steps_completed.append(f"gaps:filled({len(new_cases)})")

            result.steps_completed.append("coverage:analyzed")
        except Exception as exc:
            self._print(f"  Coverage analysis failed: {exc}")
            result.warnings.append(str(exc))

    def _step_provider_key(self, result: InitResult) -> None:
        """Inline provider-key setup so users don't silently fall into mock mode."""
        if self.force_mock:
            self._print("\n[4.5/5] Provider key: skipped (mock mode requested).")
            result.eval_mode = "mock"
            result.steps_completed.append("provider_key:skipped:force_mock")
            return

        # Refresh aliases so e.g. GEMINI_API_KEY is promoted to GOOGLE_API_KEY.
        hydrate_provider_key_aliases()
        existing = next(
            (v for v in PROVIDER_API_KEY_ENV_VARS if str(os.environ.get(v) or "").strip()),
            None,
        )
        if existing:
            self._print(f"\n[4.5/5] Provider key: detected {existing} (live mode).")
            result.eval_mode = "real"
            result.steps_completed.append(f"provider_key:detected:{existing}")
            return

        if not self.interactive:
            self._print(
                "\n[4.5/5] Provider key: none detected and non-interactive; "
                "falling back to mock mode."
            )
            result.eval_mode = "mock"
            result.warnings.append(
                "No provider API key detected; eval mode will be mock. "
                "Set OPENAI_API_KEY / ANTHROPIC_API_KEY / GOOGLE_API_KEY and rerun."
            )
            result.steps_completed.append("provider_key:skipped:noninteractive")
            return

        self._print("\n[4.5/5] Provider key setup")
        try:
            import click
        except Exception as exc:  # pragma: no cover — click is a hard dep
            self._print(f"  Could not load click ({exc}); skipping key prompt.")
            result.eval_mode = "mock"
            result.warnings.append("click unavailable; eval mode will be mock.")
            result.steps_completed.append("provider_key:skipped:no_click")
            return

        provider_choices = (
            ("1", "OpenAI", "OPENAI_API_KEY"),
            ("2", "Anthropic", "ANTHROPIC_API_KEY"),
            ("3", "Google / Gemini", "GOOGLE_API_KEY"),
        )
        for number, label, env_name in provider_choices:
            self._print(f"    {number}) Paste {label} key ({env_name})")

        try:
            choice = click.prompt(
                "  Choose",
                type=click.Choice(["1", "2", "3"]),
                default="1",
                show_choices=False,
            )
        except click.Abort:
            result.eval_mode = "mock"
            result.warnings.append("Provider-key selection aborted; eval mode will be mock.")
            result.steps_completed.append("provider_key:aborted")
            return

        env_name = next(
            (env for number, _label, env in provider_choices if number == choice),
            "OPENAI_API_KEY",
        )

        key_value = ""
        attempts = 0
        while not key_value:
            raw = click.prompt(
                f"  Paste your {env_name}",
                hide_input=True,
                confirmation_prompt=False,
                default="",
                show_default=False,
            ).strip()
            attempts += 1
            validation = validate_provider_key(env_name, raw)
            if validation.ok:
                key_value = raw
                break
            self._print(f"  {validation.message}")
            if attempts >= _MAX_KEY_ATTEMPTS:
                self._print(
                    f"  Too many invalid attempts ({attempts}); falling back to mock mode."
                )
                result.eval_mode = "mock"
                result.warnings.append(
                    "Too many invalid provider-key attempts; eval mode will be mock."
                )
                result.steps_completed.append("provider_key:failed")
                return

        write_workspace_env_values({env_name: key_value})
        os.environ[env_name] = key_value
        hydrate_provider_key_aliases()
        self._print(f"  Saved {env_name} to .agentlab/.env (mode: live).")
        result.eval_mode = "real"
        result.steps_completed.append(f"provider_key:saved:{env_name}")

    def _step_suggest(self, result: InitResult) -> None:
        """Print next-step suggestions."""
        self._print("\n[5/5] Ready!")

        if not result.eval_mode:
            mode = "mock"
            if not self.force_mock and _has_credentials():
                mode = "real"
            result.eval_mode = mode
        mode = result.eval_mode

        self._print(f"\n  Agent: {result.agent_name}")
        self._print(f"  Card:  {result.card_path}")
        self._print(f"  Cases: {result.cases_generated} generated, {result.gaps_filled} gap-fills")
        self._print(f"  Mode:  {mode}")
        self._print("\n  Next steps:")
        self._print("    agentlab card show          # review your Agent Card")
        self._print("    agentlab eval run            # run the eval suite")
        self._print("    agentlab eval coverage       # check coverage gaps")
        self._print("    agentlab optimize            # optimize your agent")
        result.steps_completed.append("done")

    def _auto_detect(self) -> Path | None:
        """Find an agent source in the workspace."""
        if (self.workspace / "agent.py").is_file():
            return self.workspace
        configs = self.workspace / "configs"
        if configs.is_dir():
            yamls = sorted(configs.glob("v*.yaml"))
            if yamls:
                return yamls[-1]
        for f in sorted(self.workspace.glob("*.yaml")):
            if f.name not in ("agentlab.yaml", "agentlab.lock"):
                return f
        return None


def _starter_config() -> dict:
    return {
        "name": "my_agent",
        "description": "A new agent — customize this config to get started.",
        "prompts": {"root": "You are a helpful assistant."},
        "routing": {"rules": []},
        "tools": {},
    }


def _has_credentials() -> bool:
    return any(
        os.environ.get(v)
        for v in ("GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY")
    )
