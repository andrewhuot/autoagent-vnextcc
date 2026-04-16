"""Post-experiment reflection engine for the optimization loop.

After each optimization experiment, analyzes the outcome, generates insights
about what worked and what didn't, persists learnings, and builds cumulative
surface-effectiveness scores to inform future optimization cycles.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass, field

from .providers import LLMRequest, LLMRouter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Reflection:
    """Post-experiment reflection on an optimization attempt."""

    attempt_id: str
    outcome: str  # "accepted", "rejected_*", etc.
    score_before: float
    score_after: float
    score_delta: float

    what_worked: list[str] = field(default_factory=list)
    what_didnt: list[str] = field(default_factory=list)
    root_cause_update: str = ""
    next_suggestions: list[str] = field(default_factory=list)
    surface_learnings: dict[str, float] = field(default_factory=dict)
    confidence: float = 0.5
    reasoning: str = ""


@dataclass
class SurfaceEffectiveness:
    """Cumulative effectiveness tracking for a mutation surface."""

    surface: str
    attempts: int = 0
    successes: int = 0
    avg_improvement: float = 0.0
    last_attempted: float = 0.0

    @property
    def success_rate(self) -> float:
        return self.successes / self.attempts if self.attempts > 0 else 0.0


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


_REFLECTION_SYSTEM_PROMPT = (
    "You are analyzing the results of an AI agent optimization experiment. "
    "Your job is to determine what worked, what didn't, and why, so that "
    "future optimization cycles are better informed.\n\n"
    "Respond with a JSON object containing these fields:\n"
    '  "what_worked": list of strings — specific things that improved\n'
    '  "what_didnt": list of strings — things that had no effect or regressed\n'
    '  "root_cause_update": string — updated understanding of the failure mode\n'
    '  "next_suggestions": list of strings — informed suggestions for the next cycle\n'
    '  "surface_learnings": object mapping surface name to effectiveness score (0-1)\n'
    '  "confidence": float 0-1 — how confident you are in this analysis\n'
    '  "reasoning": string — brief explanation of your analysis\n\n'
    "Keep each field concise — these summaries will be included in future LLM prompts."
)


class ReflectionEngine:
    """Analyzes optimization experiment outcomes and builds learning context."""

    def __init__(
        self,
        llm_router: LLMRouter | None = None,
        db_path: str = "reflections.db",
    ) -> None:
        self.llm_router = llm_router
        self.db_path = db_path
        self._ensure_db()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reflect(
        self,
        attempt: dict,
        proposal_reasoning: str = "",
        failure_context: str = "",
        agent_card_markdown: str = "",
    ) -> Reflection:
        """Generate a reflection on an optimization attempt.

        Uses LLM if available, otherwise deterministic analysis.
        """
        score_before = float(attempt.get("score_before", 0.0))
        score_after = float(attempt.get("score_after", 0.0))
        score_delta = score_after - score_before
        outcome = str(attempt.get("status", "unknown"))
        attempt_id = str(attempt.get("attempt_id", ""))

        # Try LLM-based reflection first.
        if self.llm_router is not None:
            try:
                reflection = self._llm_reflect(
                    attempt,
                    score_before=score_before,
                    score_after=score_after,
                    score_delta=score_delta,
                    outcome=outcome,
                    attempt_id=attempt_id,
                    proposal_reasoning=proposal_reasoning,
                    failure_context=failure_context,
                    agent_card_markdown=agent_card_markdown,
                )
                self._persist_reflection(reflection)
                self._update_surface_effectiveness(reflection)
                return reflection
            except Exception:
                logger.warning(
                    "LLM reflection failed for %s; falling back to deterministic",
                    attempt_id,
                    exc_info=True,
                )

        # Deterministic fallback.
        reflection = self._deterministic_reflect(
            attempt,
            score_before=score_before,
            score_after=score_after,
            score_delta=score_delta,
            outcome=outcome,
            attempt_id=attempt_id,
        )
        self._persist_reflection(reflection)
        self._update_surface_effectiveness(reflection)
        return reflection

    def get_context_for_next_cycle(self, limit: int = 5) -> dict:
        """Build context from recent reflections for the next proposer cycle.

        Returns a dict with:
        - recent_reflections: list of last *limit* reflection summaries
        - surface_effectiveness: dict of surface -> SurfaceEffectiveness as dict
        - patterns: list of observed patterns
        """
        reflections = self._load_recent_reflections(limit)
        effectiveness = self.get_surface_effectiveness()

        # Derive simple patterns from stored reflections.
        patterns: list[str] = []
        if reflections:
            accepted = [r for r in reflections if r["outcome"] == "accepted"]
            rejected = [r for r in reflections if r["outcome"] != "accepted"]
            if accepted:
                patterns.append(
                    f"{len(accepted)} of last {len(reflections)} experiments accepted"
                )
            if rejected:
                patterns.append(
                    f"{len(rejected)} of last {len(reflections)} experiments rejected"
                )
            # Surface-level pattern: find consistently effective/ineffective surfaces.
            for surface, eff in effectiveness.items():
                if eff.attempts >= 2:
                    if eff.success_rate >= 0.7:
                        patterns.append(
                            f"Surface '{surface}' is effective "
                            f"({eff.successes}/{eff.attempts} successes)"
                        )
                    elif eff.success_rate <= 0.2:
                        patterns.append(
                            f"Surface '{surface}' is ineffective "
                            f"({eff.successes}/{eff.attempts} successes)"
                        )

        return {
            "recent_reflections": reflections,
            "surface_effectiveness": {
                surface: {
                    "surface": eff.surface,
                    "attempts": eff.attempts,
                    "successes": eff.successes,
                    "avg_improvement": eff.avg_improvement,
                    "success_rate": eff.success_rate,
                    "last_attempted": eff.last_attempted,
                }
                for surface, eff in effectiveness.items()
            },
            "patterns": patterns,
        }

    def get_surface_effectiveness(self) -> dict[str, SurfaceEffectiveness]:
        """Get cumulative effectiveness scores for each mutation surface."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT surface, attempts, successes, total_improvement, last_attempted "
                "FROM surface_effectiveness ORDER BY surface"
            ).fetchall()
        result: dict[str, SurfaceEffectiveness] = {}
        for row in rows:
            surface, attempts, successes, total_improvement, last_attempted = row
            avg_improvement = total_improvement / attempts if attempts > 0 else 0.0
            result[surface] = SurfaceEffectiveness(
                surface=surface,
                attempts=attempts,
                successes=successes,
                avg_improvement=avg_improvement,
                last_attempted=last_attempted,
            )
        return result

    # ------------------------------------------------------------------
    # LLM reflection
    # ------------------------------------------------------------------

    def _llm_reflect(
        self,
        attempt: dict,
        *,
        score_before: float,
        score_after: float,
        score_delta: float,
        outcome: str,
        attempt_id: str,
        proposal_reasoning: str,
        failure_context: str,
        agent_card_markdown: str,
    ) -> Reflection:
        """Generate an LLM-powered reflection."""
        change_description = str(attempt.get("change_description", ""))
        config_section = str(attempt.get("config_section", ""))

        user_prompt_parts = [
            f"## Experiment outcome: {outcome}",
            f"Score before: {score_before:.4f}",
            f"Score after: {score_after:.4f}",
            f"Score delta: {score_delta:+.4f}",
            f"\n## Change made\n{change_description}",
            f"Config section: {config_section}",
        ]
        if proposal_reasoning:
            user_prompt_parts.append(f"\n## Proposal reasoning\n{proposal_reasoning}")
        if failure_context:
            user_prompt_parts.append(
                f"\n## Failures being addressed\n{failure_context}"
            )
        if agent_card_markdown:
            user_prompt_parts.append(f"\n## Agent card\n{agent_card_markdown}")

        request = LLMRequest(
            system=_REFLECTION_SYSTEM_PROMPT,
            prompt="\n".join(user_prompt_parts),
            temperature=0.3,
            max_tokens=1000,
            metadata={"role": "reflection", "attempt_id": attempt_id},
        )
        assert self.llm_router is not None
        response = self.llm_router.generate(request)
        parsed = self._extract_json(response.text)

        if parsed is None:
            raise ValueError(f"Could not parse JSON from LLM reflection response: {response.text[:200]}")

        return Reflection(
            attempt_id=attempt_id,
            outcome=outcome,
            score_before=score_before,
            score_after=score_after,
            score_delta=score_delta,
            what_worked=parsed.get("what_worked", []),
            what_didnt=parsed.get("what_didnt", []),
            root_cause_update=str(parsed.get("root_cause_update", "")),
            next_suggestions=parsed.get("next_suggestions", []),
            surface_learnings=parsed.get("surface_learnings", {}),
            confidence=float(parsed.get("confidence", 0.5)),
            reasoning=str(parsed.get("reasoning", "")),
        )

    # ------------------------------------------------------------------
    # Deterministic reflection
    # ------------------------------------------------------------------

    def _deterministic_reflect(
        self,
        attempt: dict,
        *,
        score_before: float,
        score_after: float,
        score_delta: float,
        outcome: str,
        attempt_id: str,
    ) -> Reflection:
        """Generate a deterministic reflection without LLM."""
        change_description = str(attempt.get("change_description", ""))
        config_section = str(attempt.get("config_section", ""))

        what_worked: list[str] = []
        what_didnt: list[str] = []
        root_cause_update = ""
        next_suggestions: list[str] = []
        surface_learnings: dict[str, float] = {}

        if outcome == "accepted" and score_delta > 0:
            # Improvement accepted.
            what_worked = [change_description] if change_description else []
            improvement_pct = (
                score_delta / score_before if score_before > 0 else score_delta
            )
            if config_section:
                surface_learnings[config_section] = min(1.0, improvement_pct)
            root_cause_update = "Change improved the target metric."
            next_suggestions = [
                f"Consider deepening changes in '{config_section}'"
                if config_section
                else "Continue exploring the same direction"
            ]
            confidence = 0.7
            reasoning = (
                f"Accepted change improved score by {score_delta:+.4f} "
                f"({improvement_pct:.1%} relative)."
            )
        elif score_delta < 0:
            # Regression.
            what_didnt = [change_description] if change_description else []
            if config_section:
                surface_learnings[config_section] = 0.0
            root_cause_update = "Change was counterproductive."
            next_suggestions = [
                f"Try a different surface instead of '{config_section}'"
                if config_section
                else "Try a different approach entirely"
            ]
            confidence = 0.6
            reasoning = f"Change regressed score by {score_delta:+.4f}."
        else:
            # No measurable change.
            what_didnt = [change_description] if change_description else []
            if config_section:
                surface_learnings[config_section] = 0.1
            root_cause_update = "Change had no measurable effect."
            next_suggestions = [
                f"Try a different surface instead of '{config_section}'"
                if config_section
                else "Try a different approach entirely"
            ]
            confidence = 0.5
            reasoning = "Score did not change; the modification may have been too subtle."

        return Reflection(
            attempt_id=attempt_id,
            outcome=outcome,
            score_before=score_before,
            score_after=score_after,
            score_delta=score_delta,
            what_worked=what_worked,
            what_didnt=what_didnt,
            root_cause_update=root_cause_update,
            next_suggestions=next_suggestions,
            surface_learnings=surface_learnings,
            confidence=confidence,
            reasoning=reasoning,
        )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _ensure_db(self) -> None:
        """Create tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS reflections (
                    attempt_id TEXT PRIMARY KEY,
                    timestamp REAL,
                    outcome TEXT,
                    score_before REAL,
                    score_after REAL,
                    score_delta REAL,
                    what_worked TEXT,
                    what_didnt TEXT,
                    root_cause_update TEXT,
                    next_suggestions TEXT,
                    surface_learnings TEXT,
                    confidence REAL,
                    reasoning TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS surface_effectiveness (
                    surface TEXT PRIMARY KEY,
                    attempts INTEGER DEFAULT 0,
                    successes INTEGER DEFAULT 0,
                    total_improvement REAL DEFAULT 0.0,
                    last_attempted REAL
                )
                """
            )
            conn.commit()

    def _persist_reflection(self, reflection: Reflection) -> None:
        """Store a reflection in SQLite."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO reflections
                    (attempt_id, timestamp, outcome, score_before, score_after,
                     score_delta, what_worked, what_didnt, root_cause_update,
                     next_suggestions, surface_learnings, confidence, reasoning)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reflection.attempt_id,
                    time.time(),
                    reflection.outcome,
                    reflection.score_before,
                    reflection.score_after,
                    reflection.score_delta,
                    json.dumps(reflection.what_worked),
                    json.dumps(reflection.what_didnt),
                    reflection.root_cause_update,
                    json.dumps(reflection.next_suggestions),
                    json.dumps(reflection.surface_learnings),
                    reflection.confidence,
                    reflection.reasoning,
                ),
            )
            conn.commit()

    def _update_surface_effectiveness(self, reflection: Reflection) -> None:
        """Update surface effectiveness scores from a reflection."""
        now = time.time()
        is_success = reflection.outcome == "accepted" and reflection.score_delta > 0
        with sqlite3.connect(self.db_path) as conn:
            for surface, score in reflection.surface_learnings.items():
                # Upsert: try update first, insert if no row was affected.
                cursor = conn.execute(
                    """
                    UPDATE surface_effectiveness
                    SET attempts = attempts + 1,
                        successes = successes + ?,
                        total_improvement = total_improvement + ?,
                        last_attempted = ?
                    WHERE surface = ?
                    """,
                    (
                        1 if is_success else 0,
                        reflection.score_delta if is_success else 0.0,
                        now,
                        surface,
                    ),
                )
                if cursor.rowcount == 0:
                    conn.execute(
                        """
                        INSERT INTO surface_effectiveness
                            (surface, attempts, successes, total_improvement, last_attempted)
                        VALUES (?, 1, ?, ?, ?)
                        """,
                        (
                            surface,
                            1 if is_success else 0,
                            reflection.score_delta if is_success else 0.0,
                            now,
                        ),
                    )
            conn.commit()

    def _load_recent_reflections(self, limit: int) -> list[dict]:
        """Load recent reflections as summary dicts."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT attempt_id, outcome, score_before, score_after, score_delta,
                       what_worked, what_didnt, root_cause_update,
                       next_suggestions, confidence, reasoning
                FROM reflections
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        results: list[dict] = []
        for row in rows:
            results.append(
                {
                    "attempt_id": row[0],
                    "outcome": row[1],
                    "score_before": row[2],
                    "score_after": row[3],
                    "score_delta": row[4],
                    "what_worked": json.loads(row[5]) if row[5] else [],
                    "what_didnt": json.loads(row[6]) if row[6] else [],
                    "root_cause_update": row[7],
                    "next_suggestions": json.loads(row[8]) if row[8] else [],
                    "confidence": row[9],
                    "reasoning": row[10],
                }
            )
        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_json(text: str) -> dict | None:
        """Parse a JSON object from possibly noisy LLM output."""
        raw = text.strip()
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
            if not match:
                return None
            try:
                parsed = json.loads(match.group(0))
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                return None
