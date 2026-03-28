"""Composable guardrail primitives for AutoAgent VNextCC (P1-3).

Guardrails are first-class objects: they can be registered, chained, and
inherited.  Every guardrail produces a structured GuardrailResult so the
pipeline can decide how to handle violations (block, warn, or log).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class GuardrailType(str, Enum):
    """Which direction(s) a guardrail inspects."""
    INPUT_VALIDATION = "input_validation"
    OUTPUT_VALIDATION = "output_validation"
    BOTH = "both"


class GuardrailSeverity(str, Enum):
    """What to do when a guardrail fires."""
    BLOCK = "block"   # Hard stop — refuse to proceed
    WARN  = "warn"    # Allow but surface a warning
    LOG   = "log"     # Silently record the event


# ---------------------------------------------------------------------------
# GuardrailResult
# ---------------------------------------------------------------------------

@dataclass
class GuardrailResult:
    """Structured result from a single guardrail check."""
    passed: bool
    severity: GuardrailSeverity
    message: str
    guardrail_name: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "severity": self.severity.value,
            "message": self.message,
            "guardrail_name": self.guardrail_name,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "GuardrailResult":
        return cls(
            passed=d["passed"],
            severity=GuardrailSeverity(d["severity"]),
            message=d["message"],
            guardrail_name=d["guardrail_name"],
            metadata=d.get("metadata", {}),
        )

    @property
    def should_block(self) -> bool:
        return not self.passed and self.severity == GuardrailSeverity.BLOCK


# ---------------------------------------------------------------------------
# Guardrail base class
# ---------------------------------------------------------------------------

class Guardrail:
    """Abstract base class for all guardrails.

    Subclasses override ``validate_input`` and/or ``validate_output``.
    The default implementations return a passing result so subclasses only
    need to override the direction(s) they care about.
    """

    def __init__(
        self,
        name: str,
        description: str,
        guardrail_type: GuardrailType = GuardrailType.BOTH,
        severity: GuardrailSeverity = GuardrailSeverity.BLOCK,
        enabled: bool = True,
    ) -> None:
        self.name = name
        self.description = description
        self.guardrail_type = guardrail_type
        self.severity = severity
        self.enabled = enabled

    # ------------------------------------------------------------------
    # Validation methods — override in subclasses
    # ------------------------------------------------------------------

    def validate_input(
        self,
        input_text: str,
        context: dict[str, Any] | None = None,
    ) -> GuardrailResult:
        """Validate an input string.  Returns a passing result by default."""
        return GuardrailResult(
            passed=True,
            severity=self.severity,
            message="Input validation passed.",
            guardrail_name=self.name,
        )

    def validate_output(
        self,
        output_text: str,
        context: dict[str, Any] | None = None,
    ) -> GuardrailResult:
        """Validate an output string.  Returns a passing result by default."""
        return GuardrailResult(
            passed=True,
            severity=self.severity,
            message="Output validation passed.",
            guardrail_name=self.name,
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "guardrail_type": self.guardrail_type.value,
            "severity": self.severity.value,
            "enabled": self.enabled,
            "class": type(self).__name__,
        }


# ---------------------------------------------------------------------------
# GuardrailRegistry
# ---------------------------------------------------------------------------

class GuardrailRegistry:
    """Central registry of all available guardrails.

    Supports parallel execution via asyncio and short-circuit on BLOCK.
    """

    def __init__(self) -> None:
        self._guardrails: dict[str, Guardrail] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, guardrail: Guardrail) -> None:
        """Register a guardrail under its name."""
        self._guardrails[guardrail.name] = guardrail

    def get(self, name: str) -> Guardrail | None:
        """Return the guardrail with *name*, or None."""
        return self._guardrails.get(name)

    def list_guardrails(self) -> list[Guardrail]:
        """Return all registered guardrails."""
        return list(self._guardrails.values())

    # ------------------------------------------------------------------
    # Execution helpers
    # ------------------------------------------------------------------

    def _select(self, guardrail_names: list[str] | None) -> list[Guardrail]:
        """Return enabled guardrails, filtered by name list if provided."""
        if guardrail_names is not None:
            return [
                g for name in guardrail_names
                if (g := self._guardrails.get(name)) and g.enabled
            ]
        return [g for g in self._guardrails.values() if g.enabled]

    def run_input_guardrails(
        self,
        input_text: str,
        context: dict[str, Any] | None = None,
        guardrail_names: list[str] | None = None,
    ) -> list[GuardrailResult]:
        """Run all applicable input guardrails sequentially, short-circuiting on BLOCK."""
        results: list[GuardrailResult] = []
        for g in self._select(guardrail_names):
            if g.guardrail_type not in (GuardrailType.INPUT_VALIDATION, GuardrailType.BOTH):
                continue
            result = g.validate_input(input_text, context)
            results.append(result)
            if result.should_block:
                break  # short-circuit
        return results

    def run_output_guardrails(
        self,
        output_text: str,
        context: dict[str, Any] | None = None,
        guardrail_names: list[str] | None = None,
    ) -> list[GuardrailResult]:
        """Run all applicable output guardrails sequentially, short-circuiting on BLOCK."""
        results: list[GuardrailResult] = []
        for g in self._select(guardrail_names):
            if g.guardrail_type not in (GuardrailType.OUTPUT_VALIDATION, GuardrailType.BOTH):
                continue
            result = g.validate_output(output_text, context)
            results.append(result)
            if result.should_block:
                break
        return results

    def run_all(
        self,
        input_text: str,
        output_text: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run all enabled guardrails on both input and output.

        Attempts parallel execution via asyncio.  Falls back to sequential
        if no event loop is available.
        """
        try:
            return asyncio.get_event_loop().run_until_complete(
                self._run_all_async(input_text, output_text, context)
            )
        except RuntimeError:
            # No event loop — run sequentially
            return self._run_all_sync(input_text, output_text, context)

    async def _run_all_async(
        self,
        input_text: str,
        output_text: str,
        context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Async parallel execution of all guardrails."""
        loop = asyncio.get_event_loop()

        async def _run_input(g: Guardrail) -> GuardrailResult:
            return await loop.run_in_executor(None, g.validate_input, input_text, context)

        async def _run_output(g: Guardrail) -> GuardrailResult:
            return await loop.run_in_executor(None, g.validate_output, output_text, context)

        input_guardrails = [
            g for g in self._guardrails.values()
            if g.enabled and g.guardrail_type in (GuardrailType.INPUT_VALIDATION, GuardrailType.BOTH)
        ]
        output_guardrails = [
            g for g in self._guardrails.values()
            if g.enabled and g.guardrail_type in (GuardrailType.OUTPUT_VALIDATION, GuardrailType.BOTH)
        ]

        input_results = await asyncio.gather(*[_run_input(g) for g in input_guardrails])
        output_results = await asyncio.gather(*[_run_output(g) for g in output_guardrails])

        return _aggregate_results(list(input_results), list(output_results))

    def _run_all_sync(
        self,
        input_text: str,
        output_text: str,
        context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Sequential fallback for run_all."""
        input_results = self.run_input_guardrails(input_text, context)
        output_results = self.run_output_guardrails(output_text, context)
        return _aggregate_results(input_results, output_results)


def _aggregate_results(
    input_results: list[GuardrailResult],
    output_results: list[GuardrailResult],
) -> dict[str, Any]:
    all_results = input_results + output_results
    blocked = [r for r in all_results if r.should_block]
    warnings = [r for r in all_results if not r.passed and r.severity == GuardrailSeverity.WARN]
    return {
        "passed": len(blocked) == 0,
        "blocked_by": [r.guardrail_name for r in blocked],
        "warnings": [r.guardrail_name for r in warnings],
        "input_results": [r.to_dict() for r in input_results],
        "output_results": [r.to_dict() for r in output_results],
        "total_checked": len(all_results),
    }


# ---------------------------------------------------------------------------
# GuardrailChain
# ---------------------------------------------------------------------------

class GuardrailChain:
    """An ordered chain of guardrails that supports inheritance.

    If *inherit_from* is provided, the parent chain's guardrails run first
    before the local chain's guardrails — mirroring policy inheritance in
    multi-tenant / multi-agent setups.
    """

    def __init__(
        self,
        guardrails: list[Guardrail],
        inherit_from: "GuardrailChain | None" = None,
    ) -> None:
        self._local: list[Guardrail] = guardrails
        self._parent: GuardrailChain | None = inherit_from

    @property
    def all_guardrails(self) -> list[Guardrail]:
        """Return parent guardrails followed by local guardrails."""
        parent_gs = self._parent.all_guardrails if self._parent else []
        return parent_gs + self._local

    def validate(
        self,
        input_text: str,
        output_text: str,
        context: dict[str, Any] | None = None,
    ) -> list[GuardrailResult]:
        """Run the full chain (parent first, then local) and return all results.

        Short-circuits on the first BLOCK result.
        """
        results: list[GuardrailResult] = []
        for g in self.all_guardrails:
            if not g.enabled:
                continue
            # Input check
            if g.guardrail_type in (GuardrailType.INPUT_VALIDATION, GuardrailType.BOTH):
                r = g.validate_input(input_text, context)
                results.append(r)
                if r.should_block:
                    return results
            # Output check
            if g.guardrail_type in (GuardrailType.OUTPUT_VALIDATION, GuardrailType.BOTH):
                r = g.validate_output(output_text, context)
                results.append(r)
                if r.should_block:
                    return results
        return results
