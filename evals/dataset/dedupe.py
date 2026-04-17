"""Cosine-similarity near-duplicate removal for eval cases.

Slice B.2 of the R5 eval corpus plan. Free function returning a
:class:`DedupeReport`. The algorithm:

1. Embed all texts in a **single** call (cost bound).
2. L2-normalize (guard zero norm with epsilon).
3. Compute the full NxN cosine-similarity matrix via matmul (numpy when
   available, pure-Python fallback otherwise — numpy is not yet a
   transitive dep in this repo).
4. Build a duplicate graph from pairs with ``sim >= threshold``.
5. For each connected component pick a **keeper** — longest
   ``reference_answer`` with lexicographic ``id`` tiebreaker. Drop the rest.
6. Preserve input order in ``report.kept``.

Caps the input at 2000 cases; LSH bucketing for larger corpora is a
follow-up (§1.5 of the plan).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

from evals.dataset.embedder import Embedder
from evals.runner import TestCase

try:  # pragma: no cover — tested implicitly in both branches
    import numpy as _np  # type: ignore

    _HAS_NUMPY = True
except ImportError:  # pragma: no cover
    _np = None
    _HAS_NUMPY = False


_MAX_SIMPLE_N = 2000
_ZERO_EPSILON = 1e-12


@dataclass
class DedupeReport:
    """Result of a :func:`dedupe` invocation."""

    kept: list[TestCase] = field(default_factory=list)
    dropped_ids: list[str] = field(default_factory=list)
    # (kept_id, dropped_id, similarity) — sim is the max similarity between
    # the keeper and any other member of the component.
    dropped_pairs: list[tuple[str, str, float]] = field(default_factory=list)


def _default_text_fn(case: TestCase) -> str:
    return case.user_message


def _normalize(vec: list[float]) -> list[float]:
    norm_sq = 0.0
    for x in vec:
        norm_sq += x * x
    norm = math.sqrt(norm_sq)
    if norm < _ZERO_EPSILON:
        return [0.0 for _ in vec]
    return [x / norm for x in vec]


def _pairwise_cosine(normalized: list[list[float]]) -> list[list[float]]:
    """Return the full NxN cosine matrix. Vectors are assumed pre-normalized."""
    n = len(normalized)
    if _HAS_NUMPY:
        mat = _np.asarray(normalized, dtype=_np.float64)
        sim = mat @ mat.T
        # Convert to plain Python lists for downstream simplicity.
        return [list(map(float, row)) for row in sim]
    # Pure-Python fallback — O(N^2 * D) dot products. N capped at 2000.
    sim = [[0.0] * n for _ in range(n)]
    for i in range(n):
        row_i = normalized[i]
        sim[i][i] = sum(x * x for x in row_i)
        for j in range(i + 1, n):
            row_j = normalized[j]
            s = 0.0
            for a, b in zip(row_i, row_j):
                s += a * b
            sim[i][j] = s
            sim[j][i] = s
    return sim


def _connected_components(edges: dict[int, set[int]], n: int) -> list[list[int]]:
    """Return connected components as lists of node indices, in ascending order."""
    seen: set[int] = set()
    components: list[list[int]] = []
    for start in range(n):
        if start in seen:
            continue
        stack = [start]
        comp: list[int] = []
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            comp.append(node)
            for nbr in edges.get(node, ()):
                if nbr not in seen:
                    stack.append(nbr)
        components.append(sorted(comp))
    return components


def dedupe(
    cases: list[TestCase],
    embedder: Embedder,
    threshold: float = 0.95,
    *,
    text_fn: Callable[[TestCase], str] | None = None,
) -> DedupeReport:
    """Remove near-duplicate cases by cosine similarity on embeddings.

    For ``N > 2000`` raises :class:`ValueError` — the simple matmul path
    becomes too memory-hungry; use LSH bucketing (deferred) or split the input.

    Parameters
    ----------
    cases:
        Input test cases. Order is preserved in ``report.kept``.
    embedder:
        Any :class:`~evals.dataset.embedder.Embedder`. ``embed`` is called
        exactly once per invocation (cost bound).
    threshold:
        Cosine-similarity threshold. Pairs ``>= threshold`` are considered
        duplicates.
    text_fn:
        Callable extracting the text to embed from a ``TestCase``. Defaults
        to ``lambda c: c.user_message``.
    """
    if not cases:
        return DedupeReport()

    n = len(cases)
    if n > _MAX_SIMPLE_N:
        raise ValueError(
            f"dedupe simple path caps at 2000 cases (got N={n}); "
            "LSH bucketing deferred — split the input or wait for the follow-up."
        )

    text_of = text_fn or _default_text_fn
    texts = [text_of(c) for c in cases]

    # Exactly one embed call.
    vectors = embedder.embed(texts)
    if len(vectors) != n:
        raise RuntimeError(
            f"Embedder returned {len(vectors)} vectors for {n} texts"
        )

    normalized = [_normalize(list(v)) for v in vectors]
    sim = _pairwise_cosine(normalized)

    # Build duplicate edges and per-pair similarities.
    edges: dict[int, set[int]] = {i: set() for i in range(n)}
    pair_sim: dict[tuple[int, int], float] = {}
    for i in range(n):
        row = sim[i]
        for j in range(i + 1, n):
            s = row[j]
            if s >= threshold:
                edges[i].add(j)
                edges[j].add(i)
                pair_sim[(i, j)] = s

    components = _connected_components(edges, n)

    dropped_mask = [False] * n
    dropped_pairs: list[tuple[str, str, float]] = []

    for comp in components:
        if len(comp) == 1:
            continue
        # Pick keeper: longest reference_answer, ties broken by lex id.
        keeper_idx = min(
            comp,
            key=lambda idx: (-len(cases[idx].reference_answer), cases[idx].id),
        )
        keeper_case = cases[keeper_idx]
        for idx in comp:
            if idx == keeper_idx:
                continue
            dropped_mask[idx] = True
            # Similarity used = max similarity between keeper and any member
            # of the component (other than itself). Useful for debugging —
            # a transitive component may show sim < threshold against the
            # specific keeper.
            max_sim_to_member = 0.0
            for other in comp:
                if other == idx:
                    continue
                a, b = (idx, other) if idx < other else (other, idx)
                s = pair_sim.get((a, b))
                if s is None:
                    s = sim[idx][other]
                if s > max_sim_to_member:
                    max_sim_to_member = s
            dropped_pairs.append(
                (keeper_case.id, cases[idx].id, float(max_sim_to_member))
            )

    kept = [cases[i] for i in range(n) if not dropped_mask[i]]
    dropped_ids = [cases[i].id for i in range(n) if dropped_mask[i]]

    return DedupeReport(
        kept=kept,
        dropped_ids=dropped_ids,
        dropped_pairs=dropped_pairs,
    )
