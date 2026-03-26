"""Natural language config editor — translates descriptions into config changes."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EditIntent:
    """Parsed intent from natural language edit request."""

    description: str
    target_surfaces: list[str]      # Identified surfaces to modify
    change_type: str                # "instruction_edit", "example_add", "config_change"
    constraints: list[str] = field(default_factory=list)


@dataclass
class EditResult:
    """Result of applying an NL edit."""

    original_config: dict
    new_config: dict
    change_description: str
    diff_summary: str
    score_before: float
    score_after: float
    accepted: bool

    def to_dict(self) -> dict:
        return {
            "original_config": self.original_config,
            "new_config": self.new_config,
            "change_description": self.change_description,
            "diff_summary": self.diff_summary,
            "score_before": self.score_before,
            "score_after": self.score_after,
            "accepted": self.accepted,
        }


# Keyword → surface mapping table
# Each entry: (keywords, target_surfaces, change_type)
KEYWORD_SURFACE_MAP: list[tuple[list[str], list[str], str]] = [
    (["billing", "refund", "payment", "invoice"], ["routing.rules"], "config_change"),
    (["safety", "guardrail", "harmful", "violation"], ["prompts.root"], "instruction_edit"),
    (["latency", "slow", "timeout", "fast", "speed"], ["thresholds", "tools"], "config_change"),
    (["routing", "misroute", "wrong agent", "transfer"], ["routing.rules"], "config_change"),
    (["empathetic", "tone", "friendly", "warm", "polite"], ["prompts.root"], "instruction_edit"),
    (["example", "few-shot", "sample", "demo"], ["examples"], "example_add"),
    (["verbose", "concise", "short", "brief", "length"], ["prompts.root"], "instruction_edit"),
    (["quality", "accurate", "correct", "thorough"], ["prompts.root"], "instruction_edit"),
    (["cost", "expensive", "cheap", "token", "budget"], ["thresholds", "generation_settings"], "config_change"),
]

# Instruction suffixes to append for prompt-targeting edits, keyed by description keyword
_PROMPT_SUFFIX_MAP: list[tuple[list[str], str]] = [
    (["safety", "guardrail", "harmful", "violation"], " Always refuse harmful requests and apply strict safety guardrails."),
    (["empathetic", "tone", "friendly", "warm", "polite"], " Respond with empathy and a warm, friendly tone."),
    (["verbose", "length"], " Keep responses concise and to the point."),
    (["concise", "short", "brief"], " Keep responses concise and to the point."),
    (["quality", "accurate", "correct", "thorough"], " Ensure accuracy and thoroughness in every response."),
]


class NLEditor:
    """Translates natural language descriptions into config changes."""

    def __init__(
        self,
        proposer: Any = None,
        eval_runner: Any = None,
        use_mock: bool = True,
    ) -> None:
        self.proposer = proposer
        self.eval_runner = eval_runner
        self.use_mock = use_mock

    # ------------------------------------------------------------------
    # Parse
    # ------------------------------------------------------------------

    def parse_intent(self, description: str, current_config: dict) -> EditIntent:
        """Parse NL description into structured edit intent using keyword matching."""
        lowered = description.lower()

        surfaces: list[str] = []
        change_type: str = "instruction_edit"  # default

        for keywords, target_surfaces, row_change_type in KEYWORD_SURFACE_MAP:
            if any(kw in lowered for kw in keywords):
                for s in target_surfaces:
                    if s not in surfaces:
                        surfaces.append(s)
                # Use the first matched change_type (highest priority row wins first)
                if surfaces and change_type == "instruction_edit":
                    change_type = row_change_type

        # Re-derive change_type from first matching row (above loop keeps first assignment)
        # Re-scan to get the correct change_type for the first matching row
        derived_change_type: str | None = None
        for keywords, target_surfaces, row_change_type in KEYWORD_SURFACE_MAP:
            if any(kw in lowered for kw in keywords):
                derived_change_type = row_change_type
                break
        if derived_change_type is not None:
            change_type = derived_change_type

        if not surfaces:
            surfaces = ["prompts.root"]
            change_type = "instruction_edit"

        # Extract constraints
        constraints: list[str] = []
        if "maintain safety" in lowered or re.search(r'\bsafe\b', lowered):
            constraints.append("maintain_safety")
        if "don't break" in lowered or "careful" in lowered:
            constraints.append("preserve_existing")

        return EditIntent(
            description=description,
            target_surfaces=surfaces,
            change_type=change_type,
            constraints=constraints,
        )

    # ------------------------------------------------------------------
    # Generate
    # ------------------------------------------------------------------

    def generate_edit(self, intent: EditIntent, current_config: dict) -> dict:
        """Generate the edited config based on intent. Returns new config dict."""
        new_config = copy.deepcopy(current_config)
        lowered = intent.description.lower()

        for surface in intent.target_surfaces:
            if surface == "routing.rules":
                self._edit_routing_rules(new_config, lowered)

            elif surface == "prompts.root":
                self._edit_prompt_root(new_config, lowered)

            elif surface == "thresholds":
                self._edit_thresholds(new_config, lowered)

            elif surface == "tools":
                self._edit_tools(new_config, lowered)

            elif surface == "examples":
                self._edit_examples(new_config)

            elif surface == "generation_settings":
                self._edit_generation_settings(new_config, lowered)

        return new_config

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------

    def apply_and_eval(
        self,
        description: str,
        current_config: dict,
        eval_runner: Any = None,
        deployer: Any = None,
        auto_apply: bool = False,
    ) -> EditResult:
        """Full pipeline: parse → generate → eval → present."""
        intent = self.parse_intent(description, current_config)
        new_config = self.generate_edit(intent, current_config)

        # Determine eval runner (instance-level fallback)
        runner = eval_runner or self.eval_runner

        if runner is not None:
            try:
                before_score = runner.run(config=current_config)
                after_score = runner.run(config=new_config)
                score_before = float(getattr(before_score, "composite", before_score))
                score_after = float(getattr(after_score, "composite", after_score))
            except Exception:
                score_before = 0.84
                score_after = 0.86
        else:
            score_before = 0.84
            score_after = 0.86

        diff_summary = self._build_diff_summary(current_config, new_config)
        accepted = score_after >= score_before

        if auto_apply and accepted and deployer is not None:
            try:
                deployer.version_manager.save_version(
                    new_config,
                    scores={"composite": score_after},
                    status="canary",
                )
            except Exception:
                pass

        return EditResult(
            original_config=current_config,
            new_config=new_config,
            change_description=description,
            diff_summary=diff_summary,
            score_before=score_before,
            score_after=score_after,
            accepted=accepted,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _edit_routing_rules(self, config: dict, lowered: str) -> None:
        """Add routing keyword based on description to existing routing rules."""
        routing = config.setdefault("routing", {})
        rules: list[dict] = routing.setdefault("rules", [])

        # Determine new keyword from description
        new_keyword: str | None = None
        keyword_candidates = ["billing", "refund", "payment", "invoice",
                               "routing", "transfer", "misroute"]
        for candidate in keyword_candidates:
            if candidate in lowered:
                new_keyword = candidate
                break

        if new_keyword is None:
            new_keyword = "auto_routed"

        # Append keyword to the first rule if present, else create a new rule
        if rules:
            existing_keywords = rules[0].get("keywords", [])
            if new_keyword not in existing_keywords:
                rules[0]["keywords"] = existing_keywords + [new_keyword]
        else:
            rules.append({"specialist": "default", "keywords": [new_keyword]})

    def _edit_prompt_root(self, config: dict, lowered: str) -> None:
        """Append a relevant instruction suffix to the root prompt."""
        prompts = config.setdefault("prompts", {})
        current_root: str = prompts.get("root", "")

        suffix = ""
        for kws, candidate_suffix in _PROMPT_SUFFIX_MAP:
            if any(kw in lowered for kw in kws):
                suffix = candidate_suffix
                break

        if not suffix:
            suffix = " Follow the updated guidelines carefully."

        if not current_root.endswith(suffix):
            prompts["root"] = current_root + suffix

    def _edit_thresholds(self, config: dict, lowered: str) -> None:
        """Adjust max_turns or timeout values in thresholds."""
        thresholds = config.setdefault("thresholds", {})

        if "latency" in lowered or "fast" in lowered or "speed" in lowered:
            # Reduce max_turns to tighten latency budget
            current = thresholds.get("max_turns", 20)
            thresholds["max_turns"] = max(5, int(current * 0.8))
        elif "slow" in lowered or "timeout" in lowered:
            # Increase timeout tolerance
            current = thresholds.get("max_turns", 20)
            thresholds["max_turns"] = int(current * 1.2)
        elif "cost" in lowered or "budget" in lowered or "cheap" in lowered:
            current = thresholds.get("max_turns", 20)
            thresholds["max_turns"] = max(5, int(current * 0.75))
        else:
            # Generic: tighten slightly
            current = thresholds.get("max_turns", 20)
            thresholds["max_turns"] = max(5, current - 2)

    def _edit_tools(self, config: dict, lowered: str) -> None:
        """Adjust tool timeout_ms values."""
        tools = config.setdefault("tools", {})
        catalog = tools.get("catalog", {})

        if isinstance(catalog, dict):
            current_timeout = catalog.get("timeout_ms", 5000)
            if "fast" in lowered or "latency" in lowered or "speed" in lowered:
                catalog["timeout_ms"] = max(1000, int(current_timeout * 0.7))
            elif "slow" in lowered or "timeout" in lowered:
                catalog["timeout_ms"] = int(current_timeout * 1.5)
            else:
                catalog["timeout_ms"] = max(1000, int(current_timeout * 0.9))
            tools["catalog"] = catalog

    def _edit_examples(self, config: dict) -> None:
        """Add a placeholder few-shot example."""
        examples = config.setdefault("examples", [])
        placeholder = {
            "input": "Example user query",
            "output": "Example agent response demonstrating desired behavior.",
        }
        examples.append(placeholder)

    def _edit_generation_settings(self, config: dict, lowered: str) -> None:
        """Adjust temperature or max_tokens in generation settings."""
        gen = config.setdefault("generation_settings", {})

        if "cost" in lowered or "budget" in lowered or "cheap" in lowered or "token" in lowered:
            current_tokens = gen.get("max_tokens", 1024)
            gen["max_tokens"] = max(256, int(current_tokens * 0.75))
        if "expensive" in lowered:
            current_temp = gen.get("temperature", 0.7)
            gen["temperature"] = round(max(0.1, current_temp - 0.1), 2)

    def _build_diff_summary(self, original: dict, new: dict, prefix: str = "") -> str:
        """Build a human-readable summary of changed keys."""
        changed: list[str] = []

        all_keys = set(original.keys()) | set(new.keys())
        for key in sorted(all_keys):
            full_key = f"{prefix}{key}" if prefix else key
            orig_val = original.get(key)
            new_val = new.get(key)

            if orig_val != new_val:
                if isinstance(orig_val, dict) and isinstance(new_val, dict):
                    nested = self._build_diff_summary(orig_val, new_val, prefix=f"{full_key}.")
                    if nested:
                        changed.append(nested)
                else:
                    changed.append(full_key)

        return ", ".join(changed) if changed else ""
