"""Vector-indexed skill library for semantic search over skill descriptions.

Uses a SQLite backend with bag-of-words TF-IDF embeddings as a lightweight,
dependency-free fallback.  When a proper embedding function is injected the
same store and search path is used, so the interface is forward-compatible
with dense neural embeddings.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class SkillEmbedding:
    """Persisted embedding record for a single skill version.

    Attributes:
        skill_name:  Unique name of the skill.
        version:     Version integer (latest wins on search collisions).
        embedding:   Float vector (TF-IDF or dense, depending on encoder).
        description: Text that was embedded (used for re-indexing).
        metadata:    Arbitrary extra fields (category, tags, …).
    """

    skill_name: str
    version: int
    embedding: list[float]
    description: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "version": self.version,
            "embedding": self.embedding,
            "description": self.description,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillEmbedding:
        return cls(
            skill_name=data["skill_name"],
            version=data["version"],
            embedding=data["embedding"],
            description=data["description"],
            metadata=data.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# Internal TF-IDF helpers
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "of", "to", "in", "for",
        "on", "with", "is", "it", "at", "be", "this", "that",
        "from", "by", "as", "are", "was", "not", "but",
    }
)

# Fixed vocabulary built lazily; we keep it small (max 4096 terms) so that
# dot-product and cosine similarity are fast even in pure Python.
_MAX_VOCAB = 4096


def _tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alpha, remove stopwords and short tokens."""
    tokens = re.findall(r"[a-z]{3,}", text.lower())
    return [t for t in tokens if t not in _STOPWORDS]


def _tf(tokens: list[str]) -> dict[str, float]:
    """Term frequency (raw count normalised by document length)."""
    if not tokens:
        return {}
    counts: dict[str, int] = {}
    for t in tokens:
        counts[t] = counts.get(t, 0) + 1
    n = len(tokens)
    return {t: c / n for t, c in counts.items()}


class _TFIDFIndex:
    """Incremental TF-IDF index for vocabulary management."""

    def __init__(self) -> None:
        self._doc_freq: dict[str, int] = {}   # term -> number of docs containing it
        self._n_docs: int = 0
        self._vocab: list[str] = []            # ordered vocabulary
        self._vocab_set: set[str] = set()

    def add_document(self, tokens: list[str]) -> None:
        self._n_docs += 1
        for t in set(tokens):
            self._doc_freq[t] = self._doc_freq.get(t, 0) + 1
            if t not in self._vocab_set and len(self._vocab) < _MAX_VOCAB:
                self._vocab.append(t)
                self._vocab_set.add(t)

    def idf(self, term: str) -> float:
        df = self._doc_freq.get(term, 0)
        if df == 0 or self._n_docs == 0:
            return 0.0
        return math.log((1 + self._n_docs) / (1 + df)) + 1.0

    def vectorize(self, tokens: list[str]) -> list[float]:
        """Return a TF-IDF vector aligned to the current vocabulary."""
        tf_map = _tf(tokens)
        return [
            tf_map.get(term, 0.0) * self.idf(term)
            for term in self._vocab
        ]

    @property
    def vocab(self) -> list[str]:
        return list(self._vocab)

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_freq": self._doc_freq,
            "n_docs": self._n_docs,
            "vocab": self._vocab,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> _TFIDFIndex:
        obj = cls()
        obj._doc_freq = data.get("doc_freq", {})
        obj._n_docs = data.get("n_docs", 0)
        obj._vocab = data.get("vocab", [])
        obj._vocab_set = set(obj._vocab)
        return obj


# ---------------------------------------------------------------------------
# SkillVectorStore
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS skill_embeddings (
    skill_name  TEXT    NOT NULL,
    version     INTEGER NOT NULL DEFAULT 1,
    description TEXT    NOT NULL DEFAULT '',
    embedding   TEXT    NOT NULL,          -- JSON array of floats
    metadata    TEXT    NOT NULL DEFAULT '{}',
    indexed_at  REAL    NOT NULL,
    PRIMARY KEY (skill_name, version)
);
CREATE TABLE IF NOT EXISTS tfidf_index (
    id   INTEGER PRIMARY KEY CHECK (id = 1),
    data TEXT    NOT NULL DEFAULT '{}'
);
"""


class SkillVectorStore:
    """SQLite-backed semantic skill store with cosine-similarity search.

    Embedding strategy
    ------------------
    By default ``_compute_embedding`` uses an incremental TF-IDF model that
    is persisted alongside the embeddings in the same SQLite database, so no
    external service is required.

    If you want to plug in a dense encoder (e.g. ``sentence-transformers``),
    override ``_compute_embedding`` in a subclass or pass ``embedding_fn`` at
    construction time::

        store = SkillVectorStore(embedding_fn=my_encoder)

    The rest of the class is identical in both cases.
    """

    def __init__(
        self,
        db_path: str = ".autoagent/skill_vectors.db",
        embedding_fn: Any = None,
    ) -> None:
        """
        Args:
            db_path:      Path to the SQLite database file.
            embedding_fn: Optional callable ``(text: str) -> list[float]``.
                          If provided, ``_compute_embedding`` delegates to it.
        """
        self._db_path = db_path
        self._embedding_fn = embedding_fn
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.executescript(_DDL)
        self._conn.commit()
        self._tfidf = self._load_tfidf_index()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def index_skill(
        self,
        skill_name: str,
        description: str,
        embedding: list[float] | None = None,
        version: int = 1,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add or replace the embedding for *skill_name*.

        Args:
            skill_name:  Unique skill identifier.
            description: Text to embed (used when *embedding* is None).
            embedding:   Pre-computed float vector.  If omitted, computed from
                         *description* via ``_compute_embedding``.
            version:     Skill version integer (default 1).
            metadata:    Optional dict stored alongside the embedding.
        """
        if embedding is None:
            embedding = self._compute_embedding(description)

        meta = metadata or {}
        self._conn.execute(
            """
            INSERT INTO skill_embeddings (skill_name, version, description, embedding, metadata, indexed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(skill_name, version) DO UPDATE SET
                description = excluded.description,
                embedding   = excluded.embedding,
                metadata    = excluded.metadata,
                indexed_at  = excluded.indexed_at
            """,
            (
                skill_name,
                version,
                description,
                json.dumps(embedding),
                json.dumps(meta),
                time.time(),
            ),
        )
        self._conn.commit()
        # Keep TF-IDF index fresh for future queries
        self._tfidf.add_document(_tokenize(description))
        self._save_tfidf_index()

    def search(
        self,
        query: str,
        top_k: int = 5,
    ) -> list[tuple[str, float]]:
        """Return the top-*k* skills most similar to *query*.

        Args:
            query: Free-text search query.
            top_k: Maximum number of results to return.

        Returns:
            List of ``(skill_name, cosine_similarity)`` tuples, sorted
            descending by similarity.  Only the latest version of each skill
            is considered.
        """
        query_emb = self._compute_embedding(query)
        if not query_emb or all(v == 0.0 for v in query_emb):
            # Fall back to simple LIKE search
            return self._fallback_search(query, top_k)

        rows = self._conn.execute(
            "SELECT skill_name, version, embedding FROM skill_embeddings"
        ).fetchall()

        # Keep only the highest version per skill name
        latest: dict[str, tuple[int, list[float]]] = {}
        for skill_name, version, emb_json in rows:
            emb = json.loads(emb_json)
            if skill_name not in latest or version > latest[skill_name][0]:
                latest[skill_name] = (version, emb)

        scored: list[tuple[str, float]] = []
        for skill_name, (_ver, emb) in latest.items():
            sim = self._cosine_similarity(query_emb, emb)
            scored.append((skill_name, round(sim, 6)))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def remove_skill(self, skill_name: str) -> None:
        """Remove all versions of *skill_name* from the index."""
        self._conn.execute(
            "DELETE FROM skill_embeddings WHERE skill_name = ?", (skill_name,)
        )
        self._conn.commit()

    def list_indexed(self) -> list[str]:
        """Return names of all indexed skills (deduplicated, sorted)."""
        rows = self._conn.execute(
            "SELECT DISTINCT skill_name FROM skill_embeddings ORDER BY skill_name"
        ).fetchall()
        return [r[0] for r in rows]

    def close(self) -> None:
        """Flush and close the underlying SQLite connection."""
        self._save_tfidf_index()
        self._conn.close()

    # ------------------------------------------------------------------
    # Embedding helpers
    # ------------------------------------------------------------------

    def _compute_embedding(self, text: str) -> list[float]:
        """Compute a float embedding vector for *text*.

        If an ``embedding_fn`` was provided at construction, it is used.
        Otherwise falls back to TF-IDF over the vocabulary accumulated from
        all previously indexed descriptions.
        """
        if self._embedding_fn is not None:
            return list(self._embedding_fn(text))

        tokens = _tokenize(text)
        if not tokens:
            return []

        # Add the query tokens to the index so IDF scores are meaningful even
        # for first-time queries (won't be persisted unless index_skill is called).
        self._tfidf.add_document(tokens)
        vec = self._tfidf.vectorize(tokens)
        return vec

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Cosine similarity between two equal-length float vectors.

        Handles mismatched lengths by zero-padding the shorter vector.
        Returns 0.0 when either vector is the zero vector.
        """
        if not a or not b:
            return 0.0

        # Align lengths
        len_a, len_b = len(a), len(b)
        if len_a < len_b:
            a = a + [0.0] * (len_b - len_a)
        elif len_b < len_a:
            b = b + [0.0] * (len_a - len_b)

        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)

    # ------------------------------------------------------------------
    # TF-IDF persistence
    # ------------------------------------------------------------------

    def _load_tfidf_index(self) -> _TFIDFIndex:
        row = self._conn.execute(
            "SELECT data FROM tfidf_index WHERE id = 1"
        ).fetchone()
        if row is None:
            return _TFIDFIndex()
        try:
            data = json.loads(row[0])
            return _TFIDFIndex.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            return _TFIDFIndex()

    def _save_tfidf_index(self) -> None:
        data = json.dumps(self._tfidf.to_dict())
        self._conn.execute(
            """
            INSERT INTO tfidf_index (id, data) VALUES (1, ?)
            ON CONFLICT(id) DO UPDATE SET data = excluded.data
            """,
            (data,),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Fallback search (no embeddings available)
    # ------------------------------------------------------------------

    def _fallback_search(
        self, query: str, top_k: int
    ) -> list[tuple[str, float]]:
        """Simple LIKE-based search when embeddings yield zero vectors."""
        like_pattern = f"%{query.lower()}%"
        rows = self._conn.execute(
            """
            SELECT skill_name, description
            FROM skill_embeddings
            WHERE lower(description) LIKE ? OR lower(skill_name) LIKE ?
            ORDER BY indexed_at DESC
            """,
            (like_pattern, like_pattern),
        ).fetchall()

        seen: dict[str, float] = {}
        for skill_name, description in rows:
            if skill_name not in seen:
                # Score by token overlap
                q_tokens = set(_tokenize(query))
                d_tokens = set(_tokenize(description))
                overlap = len(q_tokens & d_tokens)
                denom = len(q_tokens | d_tokens)
                score = overlap / denom if denom > 0 else 0.0
                seen[skill_name] = round(score, 6)

        ranked = sorted(seen.items(), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]
