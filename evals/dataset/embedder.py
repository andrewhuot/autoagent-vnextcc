"""Pluggable Embedder for the eval corpus.

Slice B.1 of the R5 eval corpus plan. Three implementations:

- ``FakeEmbedder``: deterministic, zero-network, used by tests and the
  ``AGENTLAB_EMBEDDER=fake`` code path.
- ``OpenAIEmbedder``: wraps ``text-embedding-3-small`` with batched requests.
  Lazily imports the ``openai`` SDK so importing this module never touches
  the network-dep.
- ``CachedEmbedder``: SQLite-backed decorator keyed on
  ``(sha256(text), inner.model_name)`` with a default 90-day TTL.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Protocol, runtime_checkable


# ----------------------------------------------------------------------------
# Protocol
# ----------------------------------------------------------------------------


@runtime_checkable
class Embedder(Protocol):
    """Minimal embedder interface used across the eval corpus tooling."""

    model_name: str

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, preserving order."""
        ...


# ----------------------------------------------------------------------------
# FakeEmbedder
# ----------------------------------------------------------------------------


class FakeEmbedder:
    """Deterministic embedder for tests. Zero network, stable across processes.

    Uses ``sha256`` of the UTF-8 encoded text and scales the digest bytes into
    ``[-1.0, 1.0]`` floats. Two different ``FakeEmbedder()`` instances produce
    identical vectors for the same input.
    """

    model_name = "fake-v1"

    def __init__(self, dim: int = 16) -> None:
        if dim <= 0:
            raise ValueError(f"dim must be positive, got {dim}")
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        n = len(digest)
        return [(digest[i % n] / 127.5) - 1.0 for i in range(self.dim)]


# ----------------------------------------------------------------------------
# OpenAIEmbedder
# ----------------------------------------------------------------------------


class OpenAIEmbedder:
    """Wraps OpenAI ``text-embedding-3-small`` (1536 dims).

    The OpenAI SDK is imported lazily (on first network-bound call) so that
    importing this module has zero extra dependencies. For tests, pass a
    pre-built ``client`` kwarg that mimics ``openai.OpenAI`` — then no real
    SDK import ever happens.
    """

    def __init__(
        self,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
        batch_size: int = 100,
        client: object | None = None,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self.batch_size = batch_size
        self._client = client

    @property
    def model_name(self) -> str:
        return self.model

    def _ensure_client(self) -> object:
        if self._client is not None:
            return self._client
        key = self._api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "OpenAIEmbedder: no API key available — pass api_key=... or set "
                "the OPENAI_API_KEY environment variable."
            )
        # Lazy import — must never happen at module top so tests can verify
        # "openai" stays out of sys.modules after importing evals.dataset.
        import openai  # noqa: WPS433  (intentional local import)

        self._client = openai.OpenAI(api_key=key)
        return self._client

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        client = self._ensure_client()
        out: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            resp = client.embeddings.create(model=self.model, input=batch)
            # SDK returns .data as a list of objects with .embedding; preserve order.
            for item in resp.data:
                out.append(list(item.embedding))
        return out


# ----------------------------------------------------------------------------
# CachedEmbedder
# ----------------------------------------------------------------------------


_SCHEMA = """
CREATE TABLE IF NOT EXISTS embedding_cache (
    text_hash TEXT NOT NULL,
    model TEXT NOT NULL,
    vector TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (text_hash, model)
);
"""


class CachedEmbedder:
    """SQLite-backed decorator that caches ``(sha256(text), model_name) -> vector``.

    Wraps any ``Embedder``. Expired rows (older than ``ttl_seconds``) are
    treated as cache misses and overwritten on the next fetch.
    """

    # Default TTL: 90 days.
    def __init__(
        self,
        inner: Embedder,
        db_path: str | Path,
        ttl_seconds: int = 60 * 60 * 24 * 90,
    ) -> None:
        self.inner = inner
        self.db_path = Path(db_path)
        self.ttl_seconds = ttl_seconds
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @property
    def model_name(self) -> str:
        return self.inner.model_name

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        model = self.inner.model_name
        hashes = [self._hash(t) for t in texts]
        now = time.time()
        cutoff = now - self.ttl_seconds

        # Fetch cached rows in a single SELECT.
        cached: dict[str, list[float]] = {}
        with self._connect() as conn:
            # Chunk the IN clause to avoid SQLite's max-variable limit.
            chunk = 500
            for start in range(0, len(hashes), chunk):
                piece = hashes[start : start + chunk]
                placeholders = ",".join("?" * len(piece))
                rows = conn.execute(
                    f"SELECT text_hash, vector, created_at FROM embedding_cache "
                    f"WHERE model = ? AND text_hash IN ({placeholders})",
                    [model, *piece],
                ).fetchall()
                for h, vector_json, created_at in rows:
                    if created_at < cutoff:
                        continue  # treat expired rows as misses
                    cached[h] = json.loads(vector_json)

        # Dedupe missing texts while preserving first-seen order (one inner call).
        missing_texts: list[str] = []
        missing_hashes: list[str] = []
        seen: set[str] = set()
        for text, h in zip(texts, hashes):
            if h in cached or h in seen:
                continue
            seen.add(h)
            missing_texts.append(text)
            missing_hashes.append(h)

        if missing_texts:
            new_vectors = self.inner.embed(missing_texts)
            if len(new_vectors) != len(missing_texts):
                raise RuntimeError(
                    "Inner embedder returned wrong number of vectors: "
                    f"{len(new_vectors)} for {len(missing_texts)} texts"
                )
            write_now = time.time()
            with self._connect() as conn:
                conn.executemany(
                    "INSERT OR REPLACE INTO embedding_cache "
                    "(text_hash, model, vector, created_at) VALUES (?, ?, ?, ?)",
                    [
                        (h, model, json.dumps(list(v)), write_now)
                        for h, v in zip(missing_hashes, new_vectors)
                    ],
                )
            for h, v in zip(missing_hashes, new_vectors):
                cached[h] = list(v)

        # Assemble in input order.
        return [cached[h] for h in hashes]
