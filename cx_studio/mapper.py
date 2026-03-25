"""Bidirectional mapping between CX Agent Studio and AutoAgent config schemas.

The mapper is the translation layer between Google's CX resource model and
AutoAgent's ``AgentConfig``-compatible dict.  It is intentionally stateless —
all state lives in the snapshot and config objects passed as arguments.

Layer: Layer 1 (Advanced).  May import from Layer 0 / stdlib / PyPI only.
Never import from api/, web/, or other Layer 2 modules.
"""
from __future__ import annotations

import copy
from typing import Any

from .errors import CxMappingError
from .types import (
    CxAgentSnapshot,
    CxFlow,
    CxIntent,
    CxPlaybook,
    CxTool,
)


# ---------------------------------------------------------------------------
# Prompt key mapping — CX playbook display_name → AutoAgent prompts key
# ---------------------------------------------------------------------------

# The first playbook always maps to the root prompt.  Subsequent well-known
# playbook names map to specialist prompts.  Unknown playbooks are stored
# in _cx_metadata for round-trip fidelity.
_SPECIALIST_PLAYBOOK_MAP: dict[str, str] = {
    "support": "support",
    "orders": "orders",
    "recommendations": "recommendations",
}

_DEFAULT_TOOL_TIMEOUT_MS = 5000


class CxMapper:
    """Bidirectional mapper between CX Agent Studio and AutoAgent configs.

    All methods are pure functions over their arguments — no I/O, no state.
    """

    # ------------------------------------------------------------------
    # CX → AutoAgent
    # ------------------------------------------------------------------

    def to_autoagent(self, snapshot: CxAgentSnapshot) -> dict[str, Any]:
        """Convert a ``CxAgentSnapshot`` to an ``AgentConfig``-compatible dict.

        Mapping rules:
        - First playbook → ``prompts.root``
        - Subsequent playbooks with known names → ``prompts.<name>``
        - ``CxTool`` list → ``tools`` (each tool becomes a key)
        - Flow ``transitionRoutes`` + intent ``trainingPhrases`` → ``routing.rules``
        - ``agent.generativeSettings.llm.model`` → ``model`` (if present)
        - Full snapshot is stored under ``_cx_metadata`` for round-trip safety

        Args:
            snapshot: A complete ``CxAgentSnapshot`` as returned by
                ``CxClient.fetch_snapshot``.

        Returns:
            A dict that can be loaded by ``AgentConfig.model_validate``.

        Raises:
            CxMappingError: if the snapshot is structurally invalid.
        """
        try:
            config: dict[str, Any] = {
                "prompts": self._map_playbooks_to_prompts(snapshot.playbooks),
                "tools": self._map_tools(snapshot.tools),
                "routing": self._map_routing(snapshot.flows, snapshot.intents),
                "_cx_metadata": {
                    "agent_name": snapshot.agent.name,
                    "display_name": snapshot.agent.display_name,
                    "fetched_at": snapshot.fetched_at,
                    # Store full serialised snapshot for lossless round-trip
                    "snapshot": snapshot.model_dump(),
                },
            }

            # Map generative model if advertised in agent settings
            model = self._extract_model(snapshot.agent.generative_settings)
            if model:
                config["model"] = model

        except Exception as exc:
            raise CxMappingError(f"Failed to map CX snapshot to AutoAgent config: {exc}") from exc

        return config

    # ------------------------------------------------------------------
    # AutoAgent → CX
    # ------------------------------------------------------------------

    def to_cx(
        self,
        config: dict[str, Any],
        base_snapshot: CxAgentSnapshot,
    ) -> CxAgentSnapshot:
        """Overlay an optimized AutoAgent config onto a base CX snapshot.

        The returned snapshot can be pushed back to the CX API via
        ``CxClient.update_playbook`` / ``CxClient.update_agent``.

        Mapping rules (reverse of ``to_autoagent``):
        - ``prompts.root`` → first playbook instructions
        - ``prompts.<specialist>`` → matching playbook instructions
        - ``tools`` → ``CxTool.spec`` timeout fields
        - ``routing.rules`` → flow ``transitionRoutes`` patterns

        Args:
            config: AutoAgent config dict (may be a partial optimized patch).
            base_snapshot: Original snapshot used as the base for unchanged fields.

        Returns:
            A new ``CxAgentSnapshot`` with config changes applied.

        Raises:
            CxMappingError: if the config cannot be applied to the snapshot.
        """
        try:
            result = CxAgentSnapshot(
                agent=copy.deepcopy(base_snapshot.agent),
                playbooks=copy.deepcopy(base_snapshot.playbooks),
                tools=copy.deepcopy(base_snapshot.tools),
                flows=copy.deepcopy(base_snapshot.flows),
                intents=copy.deepcopy(base_snapshot.intents),
                test_cases=copy.deepcopy(base_snapshot.test_cases),
                environments=copy.deepcopy(base_snapshot.environments),
                fetched_at=base_snapshot.fetched_at,
            )

            prompts = config.get("prompts", {})
            self._apply_prompts_to_playbooks(result, prompts)

            tools_config = config.get("tools", {})
            self._apply_tools_config(result, tools_config)

            routing = config.get("routing", {})
            self._apply_routing(result, routing)

            # Propagate model override into generative settings
            if "model" in config:
                result.agent.generative_settings = dict(
                    result.agent.generative_settings
                )
                llm = result.agent.generative_settings.setdefault("llm", {})
                llm["model"] = config["model"]

        except Exception as exc:
            raise CxMappingError(f"Failed to map AutoAgent config to CX snapshot: {exc}") from exc

        return result

    # ------------------------------------------------------------------
    # Test case extraction
    # ------------------------------------------------------------------

    def extract_test_cases(self, snapshot: CxAgentSnapshot) -> list[dict[str, Any]]:
        """Convert ``CxTestCase`` objects to AutoAgent eval format.

        Each CX test case becomes a dict with the shape expected by AutoAgent's
        eval runner::

            {
                "input": "<user message>",
                "expected_output": {<expected result dict>},
                "tags": ["tag1", "tag2"],
            }

        Multi-turn test cases use the last user turn as ``input``.

        Args:
            snapshot: A ``CxAgentSnapshot`` containing test cases.

        Returns:
            List of eval-format dicts ready for ``evals/runner.py``.
        """
        results: list[dict[str, Any]] = []
        for tc in snapshot.test_cases:
            user_message = self._extract_user_message(tc.conversation_turns)
            results.append({
                "input": user_message,
                "expected_output": tc.expected_output,
                "tags": list(tc.tags),
                # Preserve original CX name for traceability
                "_cx_test_case_name": tc.name,
                "_cx_display_name": tc.display_name,
            })
        return results

    # ------------------------------------------------------------------
    # Private helpers — CX → AutoAgent direction
    # ------------------------------------------------------------------

    def _map_playbooks_to_prompts(
        self, playbooks: list[CxPlaybook]
    ) -> dict[str, str]:
        """Map ordered playbook list to prompts dict.

        The first playbook becomes ``root``; subsequent ones use their
        display_name to look up a specialist key or are stored verbatim.
        """
        prompts: dict[str, str] = {}
        for idx, pb in enumerate(playbooks):
            instructions_text = "\n".join(pb.instructions)
            if idx == 0:
                prompts["root"] = instructions_text
            else:
                key = _SPECIALIST_PLAYBOOK_MAP.get(
                    pb.display_name.lower(), pb.display_name.lower()
                )
                prompts[key] = instructions_text
        return prompts

    def _map_tools(self, tools: list[CxTool]) -> dict[str, Any]:
        """Map CX tool list to AutoAgent tools config dict."""
        tools_config: dict[str, Any] = {}
        for tool in tools:
            # Use display_name lowercased and de-spaced as the config key
            key = tool.display_name.lower().replace(" ", "_") or tool.name.split("/")[-1]
            timeout_ms = tool.spec.get("timeout_ms", _DEFAULT_TOOL_TIMEOUT_MS)
            tools_config[key] = {
                "enabled": True,
                "timeout_ms": timeout_ms,
                "_cx_tool_name": tool.name,
                "_cx_tool_type": tool.tool_type,
            }
        return tools_config

    def _map_routing(
        self,
        flows: list[CxFlow],
        intents: list[CxIntent],
    ) -> dict[str, Any]:
        """Derive AutoAgent routing rules from CX flows and intents.

        Strategy:
        - Build a map from intent name → training phrase parts
        - Walk flow transition routes that reference intents
        - Emit a routing rule per unique target page/flow
        """
        # Build intent lookup: name → list of keyword strings
        intent_keywords: dict[str, list[str]] = {}
        for intent in intents:
            kws: list[str] = []
            for phrase in intent.training_phrases:
                for part in phrase.get("parts", []):
                    text = part.get("text", "").strip()
                    if text:
                        kws.append(text)
            intent_keywords[intent.name] = kws

        rules: list[dict[str, Any]] = []
        seen_targets: set[str] = set()

        for flow in flows:
            for route in flow.transition_routes:
                intent_name = route.get("intent", "")
                target = route.get("targetPage", route.get("targetFlow", ""))
                if not target or target in seen_targets:
                    continue
                seen_targets.add(target)

                # Derive a human-readable specialist name from the target path
                specialist = target.split("/")[-1].lower().replace("-", "_")
                keywords = intent_keywords.get(intent_name, [])

                rules.append({
                    "specialist": specialist,
                    "keywords": keywords[:10],  # cap at 10 to avoid bloat
                    "patterns": [],
                    "_cx_intent": intent_name,
                    "_cx_target": target,
                })

        return {"rules": rules}

    @staticmethod
    def _extract_model(generative_settings: dict[str, Any]) -> str:
        """Pull the LLM model name from CX generativeSettings if present."""
        llm = generative_settings.get("llm", {})
        return llm.get("model", "")

    # ------------------------------------------------------------------
    # Private helpers — AutoAgent → CX direction
    # ------------------------------------------------------------------

    def _apply_prompts_to_playbooks(
        self,
        snapshot: CxAgentSnapshot,
        prompts: dict[str, Any],
    ) -> None:
        """Write AutoAgent prompts back into snapshot playbooks in-place."""
        if not prompts or not snapshot.playbooks:
            return

        # Build a mapping: playbook index → prompt key
        for idx, pb in enumerate(snapshot.playbooks):
            if idx == 0:
                prompt_key = "root"
            else:
                prompt_key = _SPECIALIST_PLAYBOOK_MAP.get(
                    pb.display_name.lower(), pb.display_name.lower()
                )

            new_text = prompts.get(prompt_key)
            if new_text is not None:
                pb.instructions = [
                    line for line in new_text.splitlines() if line.strip()
                ]

    def _apply_tools_config(
        self,
        snapshot: CxAgentSnapshot,
        tools_config: dict[str, Any],
    ) -> None:
        """Write timeout/enabled settings back into snapshot tools in-place."""
        if not tools_config:
            return

        for tool in snapshot.tools:
            key = tool.display_name.lower().replace(" ", "_") or tool.name.split("/")[-1]
            if key in tools_config:
                cfg = tools_config[key]
                timeout_ms = cfg.get("timeout_ms", _DEFAULT_TOOL_TIMEOUT_MS)
                tool.spec = dict(tool.spec)
                tool.spec["timeout_ms"] = timeout_ms

    def _apply_routing(
        self,
        snapshot: CxAgentSnapshot,
        routing: dict[str, Any],
    ) -> None:
        """Write AutoAgent routing rules back into snapshot flows in-place.

        Updates the ``transitionRoutes`` patterns list on the first flow that
        matches each rule's ``_cx_target`` annotation (if present).  New rules
        without a ``_cx_target`` are appended as synthetic routes on the
        default flow.
        """
        rules = routing.get("rules", [])
        if not rules or not snapshot.flows:
            return

        default_flow = snapshot.flows[0]

        for rule in rules:
            cx_target = rule.get("_cx_target", "")
            cx_intent = rule.get("_cx_intent", "")
            keywords = rule.get("keywords", [])

            # Find existing route to update
            updated = False
            for flow in snapshot.flows:
                for route in flow.transition_routes:
                    if cx_target and route.get("targetPage") == cx_target:
                        # Overwrite condition with new keywords
                        if keywords:
                            route["condition"] = " OR ".join(
                                f'$sys.func.CONTAIN_TEXT(session.params.last_user_text, "{kw}")'
                                for kw in keywords[:5]
                            )
                        updated = True
                        break
                if updated:
                    break

            if not updated and cx_target:
                # Append a new synthetic route
                new_route: dict[str, Any] = {
                    "intent": cx_intent,
                    "targetPage": cx_target,
                }
                if keywords:
                    new_route["condition"] = " OR ".join(
                        f'$sys.func.CONTAIN_TEXT(session.params.last_user_text, "{kw}")'
                        for kw in keywords[:5]
                    )
                default_flow.transition_routes.append(new_route)

    @staticmethod
    def _extract_user_message(conversation_turns: list[dict[str, Any]]) -> str:
        """Extract the last user utterance from a list of conversation turns.

        CX test case turns have the shape::

            {"userInput": {"input": {"text": {"text": "…"}}}, "virtualAgentOutput": {…}}

        Returns an empty string if no user input can be found.
        """
        last_user_text = ""
        for turn in conversation_turns:
            user_input = turn.get("userInput", {})
            input_block = user_input.get("input", {})
            text_block = input_block.get("text", {})
            text = text_block.get("text", "")
            if text:
                last_user_text = text
        return last_user_text
