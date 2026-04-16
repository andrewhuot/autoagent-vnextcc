"""Thin dataset utilities for eval corpora.

Free functions only — no Dataset class. See plan §1.2.
"""

from __future__ import annotations

import os

from .embedder import CachedEmbedder, Embedder, FakeEmbedder, OpenAIEmbedder
from .exporters import export_csv, export_jsonl
from .importers import load_csv, load_huggingface, load_jsonl


def get_default_embedder() -> Embedder:
    """Return the default embedder based on the ``AGENTLAB_EMBEDDER`` env var.

    - ``AGENTLAB_EMBEDDER=fake`` → :class:`FakeEmbedder` (tests / CI).
    - Otherwise → :class:`CachedEmbedder` wrapping :class:`OpenAIEmbedder`,
      persisting to ``.agentlab/embedding_cache.db``.

    Built per call so tests can flip the env var between invocations.
    """
    if os.getenv("AGENTLAB_EMBEDDER") == "fake":
        return FakeEmbedder()
    return CachedEmbedder(OpenAIEmbedder(), ".agentlab/embedding_cache.db")


__all__ = [
    "CachedEmbedder",
    "Embedder",
    "FakeEmbedder",
    "OpenAIEmbedder",
    "export_csv",
    "export_jsonl",
    "get_default_embedder",
    "load_csv",
    "load_huggingface",
    "load_jsonl",
]
