"""Bootstrap a diverse subset of eval cases from an Agent Card.

Slice B.6 of the R5 eval corpus plan (§1.7).

The bootstrap flow:
1. Oversample via :class:`CardCaseGenerator` (deterministic templates;
   optionally LLM-enhanced when a router is attached).
2. Embed **every** candidate in a single :meth:`Embedder.embed` call
   (strict cost bound — the R5 plan invariant).
3. Greedy farthest-point sampling on unit-normalized vectors: start with
   ``candidates[0]`` as the seed; repeatedly pick the candidate whose
   minimum cosine distance to the already-selected set is maximal.  Ties
   are broken by earliest index in ``candidates``.
4. Return a :class:`BootstrapReport` with the selection (``cases``), the
   actual candidate pool size (``selected_from_candidate_count``), and the
   effective target (clamped when candidates < target).

Strict-live contract: when ``strict_live=True`` and the generator carries an
``llm_router`` but no ``OPENAI_API_KEY`` is present in the environment, raise
``RuntimeError`` — mirrors the R1 "no silent fallback" semantics.  With the
default template-only generator, strict-live is a no-op.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field

from agent_card.schema import AgentCardModel
from evals.card_case_generator import CardCaseGenerator, GeneratedCase
from evals.dataset.embedder import Embedder
from evals.runner import TestCase

logger = logging.getLogger(__name__)

_ZERO_EPSILON = 1e-12


@dataclass
class BootstrapReport:
    """Result of a :func:`bootstrap` invocation."""

    cases: list[TestCase] = field(default_factory=list)
    selected_from_candidate_count: int = 0
    target: int = 0


def _to_test_case(gc: GeneratedCase) -> TestCase:
    """Convert a ``GeneratedCase`` to the canonical ``TestCase`` schema.

    Tags default to ``[gc.category]`` because the generator doesn't populate
    ``tags`` and downstream balancers often key on it.
    """
    return TestCase(
        id=gc.id,
        category=gc.category,
        user_message=gc.user_message,
        expected_specialist=gc.expected_specialist,
        expected_behavior=gc.expected_behavior,
        safety_probe=gc.safety_probe,
        expected_keywords=list(gc.expected_keywords),
        expected_tool=gc.expected_tool,
        split=None,
        reference_answer="",
        tags=[gc.category],
    )


def _normalize(vec: list[float]) -> list[float]:
    norm_sq = 0.0
    for x in vec:
        norm_sq += x * x
    norm = math.sqrt(norm_sq)
    if norm < _ZERO_EPSILON:
        return [0.0 for _ in vec]
    return [x / norm for x in vec]


def _dot(a: list[float], b: list[float]) -> float:
    s = 0.0
    for x, y in zip(a, b):
        s += x * y
    return s


def _farthest_point_sampling(
    vectors: list[list[float]], target: int
) -> list[int]:
    """Greedy FPS on pre-normalized cosine vectors.

    Returns selected indices in pick order, starting with 0 (deterministic seed).
    Ties broken by smallest index in ``vectors``.
    """
    n = len(vectors)
    if n == 0 or target <= 0:
        return []

    selected: list[int] = [0]
    # min_dist[j] = min over s in selected of (1 - cos_sim(v_j, v_s))
    # Initialize against seed (index 0).
    min_dist: list[float] = [1.0 - _dot(vectors[j], vectors[0]) for j in range(n)]
    min_dist[0] = -math.inf  # never re-pick

    while len(selected) < target and len(selected) < n:
        # Pick the candidate with the maximum min_dist. Tie-break: earliest index.
        best_idx = -1
        best_val = -math.inf
        for j in range(n):
            if j in () or min_dist[j] == -math.inf:
                continue
            d = min_dist[j]
            if d > best_val:
                best_val = d
                best_idx = j
            # On strict ties we keep the earlier index (j iterates ascending).
        if best_idx < 0:
            break
        selected.append(best_idx)
        # Update min_dist against the newly selected vector.
        new_vec = vectors[best_idx]
        min_dist[best_idx] = -math.inf
        for j in range(n):
            if min_dist[j] == -math.inf:
                continue
            d = 1.0 - _dot(vectors[j], new_vec)
            if d < min_dist[j]:
                min_dist[j] = d

    return selected


def bootstrap(
    card: AgentCardModel,
    target: int,
    embedder: Embedder,
    *,
    generator: CardCaseGenerator | None = None,
    oversample_factor: int = 3,
    strict_live: bool = False,
) -> BootstrapReport:
    """Generate a diverse subset of ``target`` cases from an Agent Card.

    Uses farthest-point sampling on embeddings to maximize minimum pairwise
    distance within the selection.

    Parameters
    ----------
    card:
        The Agent Card to seed generation from.
    target:
        Desired number of returned cases.  Clamped to ``len(candidates)`` when
        the generator emits fewer than ``target`` cases.
    embedder:
        Any :class:`~evals.dataset.embedder.Embedder`.  ``embed`` is called
        exactly once per invocation (cost bound).
    generator:
        Optional :class:`CardCaseGenerator` override.  Defaults to a fresh
        template-only generator (no LLM calls).
    oversample_factor:
        Multiplier used to pick ``count_per_category`` when auto-driving the
        generator.  Bigger = more candidates but more template dupes.
    strict_live:
        If ``True`` and the generator carries an ``llm_router`` but no
        ``OPENAI_API_KEY`` is in ``os.environ``, raise ``RuntimeError``.

    Returns
    -------
    BootstrapReport
        ``cases`` holds the selection, in FPS-pick order.  The first entry is
        always ``candidates[0]`` (the seed).
    """
    gen = generator or CardCaseGenerator()

    # Strict-live contract — mirrors R1 semantics (no silent fallback).
    if strict_live and getattr(gen, "llm_router", None) is not None:
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError(
                "bootstrap: strict_live=True but OPENAI_API_KEY is not set "
                "and the generator is configured with an llm_router.  "
                "Set the key or drop strict_live."
            )

    # Oversample.  The per-category count aims for target*oversample_factor
    # across ~5 categories; bound below by 5 to keep small targets diverse.
    count_per_category = max(5, target)
    candidates: list[GeneratedCase] = gen.generate_all(
        card, count_per_category=count_per_category
    )

    if not candidates:
        logger.warning("bootstrap: generator produced zero candidates")
        return BootstrapReport(cases=[], selected_from_candidate_count=0, target=0)

    if len(candidates) < target:
        logger.warning(
            "bootstrap: only %d candidates available (target=%d) — returning all",
            len(candidates),
            target,
        )
        effective_target = len(candidates)
    else:
        effective_target = target

    # Exactly one embed() call.
    texts = [c.user_message for c in candidates]
    vectors = embedder.embed(texts)
    if len(vectors) != len(candidates):
        raise RuntimeError(
            f"Embedder returned {len(vectors)} vectors for {len(candidates)} "
            "candidates — expected 1:1 alignment."
        )

    normalized = [_normalize(list(v)) for v in vectors]
    picked = _farthest_point_sampling(normalized, effective_target)

    selected_cases = [_to_test_case(candidates[i]) for i in picked]

    return BootstrapReport(
        cases=selected_cases,
        selected_from_candidate_count=len(candidates),
        target=effective_target,
    )
