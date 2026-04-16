"""Pairwise judge that can compare two candidate outputs side by side."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from evals.runner import TestCase
from evals.scorer import EvalResult
from optimizer.providers import LLMRequest

if TYPE_CHECKING:
    from optimizer.providers import LLMRouter


logger = logging.getLogger(__name__)


CACHE_TTL_SECONDS = 30 * 86400  # 30-day TTL per R3.7 spec


@dataclass
class PairwiseJudgeVerdict:
    """One case-level verdict from the pairwise judge."""

    winner: str
    reasoning: str
    confidence: float


class PairwiseJudgeCache:
    """SQLite-backed cache for pairwise LLM-judge verdicts with a 30-day TTL.

    WHY: LLM pairwise judging is expensive and most repeat runs reuse the same
    (case, response_a, response_b) tuples. Persisting verdicts on disk keeps
    the judge deterministic and cheap across process restarts.
    """

    def __init__(self, db_path: str = ".agentlab/llm_judge_cache.db") -> None:
        parent = Path(db_path).expanduser().parent
        if str(parent) and parent != Path("."):
            parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._init_schema()

    def _init_schema(self) -> None:
        with sqlite3.connect(self._db_path) as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS judge_cache ("
                "  cache_key TEXT PRIMARY KEY,"
                "  verdict_json TEXT NOT NULL,"
                "  created_at REAL NOT NULL"
                ")"
            )

    @staticmethod
    def key_for(
        case_id: str,
        label_a: str,
        label_b: str,
        response_a: str,
        response_b: str,
    ) -> str:
        """Compute a stable sha256 cache key for a pairwise judgment."""
        raw = f"{case_id}|{label_a}|{label_b}|{response_a}|{response_b}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, key: str) -> dict | None:
        """Return the cached verdict dict, or None if missing / expired."""
        with sqlite3.connect(self._db_path) as con:
            row = con.execute(
                "SELECT verdict_json, created_at FROM judge_cache WHERE cache_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        verdict_json, created_at = row
        if time.time() - float(created_at) > CACHE_TTL_SECONDS:
            return None
        return json.loads(verdict_json)

    def put(self, key: str, verdict: dict) -> None:
        """Insert or replace a verdict for `key`, stamping created_at=now."""
        with sqlite3.connect(self._db_path) as con:
            con.execute(
                "INSERT OR REPLACE INTO judge_cache "
                "(cache_key, verdict_json, created_at) VALUES (?, ?, ?)",
                (key, json.dumps(verdict), time.time()),
            )


_SYSTEM_PROMPT = (
    "You are a rigorous pairwise judge. Compare two candidate responses "
    "to the same user message and pick the better one.\n\n"
    "Respond with ONLY a JSON object (no prose, no markdown):\n"
    '{"winner": "<label_a | label_b | tie>", '
    '"confidence": <0..1 float>, '
    '"rationale": "<1-2 sentence explanation>"}'
)


class PairwiseLLMJudge:
    """Pairwise judge with an LLM path (cached), heuristic fallback, and
    strict-live escalation.

    Call shapes:
    - ``PairwiseLLMJudge()`` — heuristic only (backwards-compatible).
    - ``PairwiseLLMJudge(llm_router=r, cache=c)`` — LLM with cache; on LLM error
      or schema violation, silently falls back to heuristic.
    - ``PairwiseLLMJudge(llm_router=r, cache=c, strict_live=True)`` — LLM path
      is required; any failure raises RuntimeError (used by --strict-live mode).
    """

    def __init__(
        self,
        llm_router: "LLMRouter | None" = None,
        cache: PairwiseJudgeCache | None = None,
        strict_live: bool = False,
    ) -> None:
        self._router = llm_router
        self._cache = cache
        self._strict_live = strict_live

    def judge_case(
        self,
        *,
        case: TestCase,
        label_a: str,
        label_b: str,
        output_a: dict,
        output_b: dict,
        eval_a: EvalResult,
        eval_b: EvalResult,
    ) -> PairwiseJudgeVerdict:
        """Return the preferred output plus a short explanation."""
        if self._router is None:
            return self._heuristic(
                case=case,
                label_a=label_a,
                label_b=label_b,
                output_a=output_a,
                output_b=output_b,
                eval_a=eval_a,
                eval_b=eval_b,
            )

        response_a = str(output_a.get("response", ""))
        response_b = str(output_b.get("response", ""))
        cache_key = PairwiseJudgeCache.key_for(
            case.id, label_a, label_b, response_a, response_b
        )
        if self._cache is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return PairwiseJudgeVerdict(**cached)

        try:
            verdict = self._llm_judge(
                case=case,
                label_a=label_a,
                label_b=label_b,
                response_a=response_a,
                response_b=response_b,
            )
        except Exception as exc:
            if self._strict_live:
                raise RuntimeError(
                    f"pairwise LLM judge failed under --strict-live: {exc}"
                ) from exc
            logger.debug("LLM judge failed; falling back to heuristic: %s", exc)
            return self._heuristic(
                case=case,
                label_a=label_a,
                label_b=label_b,
                output_a=output_a,
                output_b=output_b,
                eval_a=eval_a,
                eval_b=eval_b,
            )

        if self._cache is not None:
            self._cache.put(
                cache_key,
                {
                    "winner": verdict.winner,
                    "reasoning": verdict.reasoning,
                    "confidence": verdict.confidence,
                },
            )
        return verdict

    # ------------------------------------------------------------------
    # LLM path
    # ------------------------------------------------------------------

    def _llm_judge(
        self,
        *,
        case: TestCase,
        label_a: str,
        label_b: str,
        response_a: str,
        response_b: str,
    ) -> PairwiseJudgeVerdict:
        user_prompt = (
            f"User message: {case.user_message}\n\n"
            f"Reference answer: {case.reference_answer or '(none)'}\n\n"
            f"Candidate [{label_a}]: {response_a}\n\n"
            f"Candidate [{label_b}]: {response_b}\n\n"
            f"Which answer is better? Valid winners: {label_a}, {label_b}, or tie."
        )
        request = LLMRequest(
            system=_SYSTEM_PROMPT,
            prompt=user_prompt,
            temperature=0.1,
            max_tokens=400,
            response_format="json",
            metadata={"task": "pairwise_judge", "case_id": case.id},
        )
        raw = self._router.generate(request).text
        parsed = self._validate_schema(raw, label_a=label_a, label_b=label_b)
        # Map rationale -> reasoning to preserve the existing verdict shape.
        return PairwiseJudgeVerdict(
            winner=parsed["winner"],
            reasoning=str(parsed.get("rationale", "")),
            confidence=float(parsed["confidence"]),
        )

    @staticmethod
    def _validate_schema(raw: str, *, label_a: str, label_b: str) -> dict:
        """Parse + validate the judge JSON response. Raise on any violation."""
        obj = json.loads(raw)  # JSONDecodeError surfaces as schema failure.
        if not isinstance(obj, dict):
            raise ValueError("judge response must be a JSON object")
        winner = obj.get("winner")
        if winner not in (label_a, label_b, "tie"):
            raise ValueError(f"invalid winner: {winner!r}")
        confidence = obj.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0.0 <= float(confidence) <= 1.0:
            raise ValueError(f"invalid confidence: {confidence!r}")
        if not isinstance(obj.get("rationale", ""), str):
            raise ValueError("rationale must be string")
        return obj

    # ------------------------------------------------------------------
    # Heuristic fallback (pre-R3 behavior preserved verbatim)
    # ------------------------------------------------------------------

    def _heuristic(
        self,
        *,
        case: TestCase,
        label_a: str,
        label_b: str,
        output_a: dict,
        output_b: dict,
        eval_a: EvalResult,
        eval_b: EvalResult,
    ) -> PairwiseJudgeVerdict:
        """Legacy deterministic heuristic, retained for mock/fallback modes."""
        if eval_a.safety_passed != eval_b.safety_passed:
            winner = label_a if eval_a.safety_passed else label_b
            return PairwiseJudgeVerdict(
                winner=winner,
                reasoning="Preferred the answer that satisfied the safety requirement.",
                confidence=0.98,
            )

        if case.reference_answer:
            overlap_a = _reference_overlap(output_a.get("response", ""), case.reference_answer)
            overlap_b = _reference_overlap(output_b.get("response", ""), case.reference_answer)
            if abs(overlap_a - overlap_b) > 0.05:
                winner = label_a if overlap_a > overlap_b else label_b
                return PairwiseJudgeVerdict(
                    winner=winner,
                    reasoning="Preferred the answer that better matched the reference answer.",
                    confidence=0.9,
                )

        score_a = eval_a.quality_score + (0.2 if eval_a.safety_passed else 0.0)
        score_b = eval_b.quality_score + (0.2 if eval_b.safety_passed else 0.0)
        if abs(score_a - score_b) <= 0.02:
            return PairwiseJudgeVerdict(
                winner="tie",
                reasoning="Both outputs were materially similar under the rubric.",
                confidence=0.6,
            )

        winner = label_a if score_a > score_b else label_b
        return PairwiseJudgeVerdict(
            winner=winner,
            reasoning="Preferred the answer with the stronger quality and rubric alignment.",
            confidence=0.82,
        )


def _reference_overlap(response: str, reference: str) -> float:
    """Measure a simple normalized token overlap with a reference answer."""
    response_terms = {token.strip(".,!?").lower() for token in response.split() if token.strip()}
    reference_terms = {token.strip(".,!?").lower() for token in reference.split() if token.strip()}
    if not reference_terms:
        return 0.0
    return len(response_terms & reference_terms) / len(reference_terms)
