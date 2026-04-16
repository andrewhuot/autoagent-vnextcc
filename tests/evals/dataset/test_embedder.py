"""Tests for evals.dataset.embedder — FakeEmbedder, OpenAIEmbedder, CachedEmbedder.

Slice B.1 of the R5 eval corpus plan.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest


# ----------------------------------------------------------------------------
# FakeEmbedder
# ----------------------------------------------------------------------------


class TestFakeEmbedder:
    def test_fake_embedder_deterministic_same_process(self):
        from evals.dataset.embedder import FakeEmbedder

        emb = FakeEmbedder()
        v1 = emb.embed(["hello world"])
        v2 = emb.embed(["hello world"])
        assert v1 == v2

    def test_fake_embedder_deterministic_across_instances(self):
        from evals.dataset.embedder import FakeEmbedder

        a = FakeEmbedder()
        b = FakeEmbedder()
        assert a.embed(["abc"]) == b.embed(["abc"])

    def test_fake_embedder_vector_dim(self):
        from evals.dataset.embedder import FakeEmbedder

        default = FakeEmbedder()
        [v] = default.embed(["x"])
        assert len(v) == 16

        custom = FakeEmbedder(dim=32)
        [v2] = custom.embed(["x"])
        assert len(v2) == 32

    def test_fake_embedder_vector_range(self):
        from evals.dataset.embedder import FakeEmbedder

        emb = FakeEmbedder(dim=64)
        [v] = emb.embed(["some text here"])
        assert all(-1.0 <= x <= 1.0 for x in v)

    def test_fake_embedder_distinct_inputs_distinct_outputs(self):
        from evals.dataset.embedder import FakeEmbedder

        emb = FakeEmbedder()
        a, b = emb.embed(["alpha", "bravo"])
        assert a != b

    def test_fake_embedder_preserves_order(self):
        from evals.dataset.embedder import FakeEmbedder

        emb = FakeEmbedder()
        texts = ["a", "b", "c", "d"]
        vecs = emb.embed(texts)
        # Each individual call should match the batch call at same index.
        for i, t in enumerate(texts):
            [single] = emb.embed([t])
            assert vecs[i] == single

    def test_fake_embedder_model_name_is_fake_v1(self):
        from evals.dataset.embedder import FakeEmbedder

        assert FakeEmbedder().model_name == "fake-v1"


# ----------------------------------------------------------------------------
# OpenAIEmbedder
# ----------------------------------------------------------------------------


class _FakeEmbeddingResponse:
    def __init__(self, vectors: list[list[float]]):
        # Mimic the OpenAI SDK shape: response.data is a list of objects with .embedding
        self.data = [type("E", (), {"embedding": v})() for v in vectors]


class _FakeOpenAIClient:
    """Records calls to embeddings.create and returns deterministic vectors."""

    def __init__(self, dim: int = 8):
        self.calls: list[dict] = []
        self._dim = dim

        class _Embeddings:
            def __init__(self, outer):
                self._outer = outer

            def create(self, model: str, input: list[str]):
                self._outer.calls.append({"model": model, "input": list(input)})
                # Encode input index (0..n-1) within this batch into vec[0] for order-check tests.
                vectors = []
                for i, text in enumerate(input):
                    v = [float(i)] + [0.0] * (self._outer._dim - 1)
                    vectors.append(v)
                return _FakeEmbeddingResponse(vectors)

        self.embeddings = _Embeddings(self)


class TestOpenAIEmbedder:
    def test_openai_embedder_lazy_import(self):
        # Use a subprocess so we get a pristine interpreter and the assertion
        # isn't affected by other tests or conftest imports. This also avoids
        # polluting sys.modules for the rest of the suite (evicting the
        # embedder module mid-run breaks class identity in later tests).
        import subprocess

        script = (
            "import sys, evals.dataset; "
            "assert 'openai' not in sys.modules, sorted(k for k in sys.modules if 'openai' in k)"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    def test_openai_embedder_missing_key_raises(self, monkeypatch):
        from evals.dataset.embedder import OpenAIEmbedder

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        emb = OpenAIEmbedder()
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            emb.embed(["anything"])

    def test_openai_embedder_batches_100(self):
        from evals.dataset.embedder import OpenAIEmbedder

        client = _FakeOpenAIClient()
        emb = OpenAIEmbedder(client=client, batch_size=100)

        texts = [f"text-{i}" for i in range(250)]
        vecs = emb.embed(texts)

        assert len(vecs) == 250
        assert len(client.calls) == 3
        assert [len(c["input"]) for c in client.calls] == [100, 100, 50]

    def test_openai_embedder_preserves_order_across_batches(self):
        from evals.dataset.embedder import OpenAIEmbedder

        client = _FakeOpenAIClient()
        emb = OpenAIEmbedder(client=client, batch_size=50)

        texts = [f"t-{i}" for i in range(150)]
        vecs = emb.embed(texts)

        # The fake client encodes the within-batch index into vec[0].
        # After reassembly, output order should match input order:
        # batch 0: vec[0]=0..49, batch 1: vec[0]=0..49, batch 2: vec[0]=0..49
        expected_first_components = list(range(50)) + list(range(50)) + list(range(50))
        assert [v[0] for v in vecs] == [float(x) for x in expected_first_components]
        # And length matches.
        assert len(vecs) == 150

    def test_openai_embedder_model_name_property(self):
        from evals.dataset.embedder import OpenAIEmbedder

        emb = OpenAIEmbedder(model="text-embedding-3-small", client=_FakeOpenAIClient())
        assert emb.model_name == "text-embedding-3-small"

        emb2 = OpenAIEmbedder(model="text-embedding-3-large", client=_FakeOpenAIClient())
        assert emb2.model_name == "text-embedding-3-large"


# ----------------------------------------------------------------------------
# CachedEmbedder
# ----------------------------------------------------------------------------


class _SpyEmbedder:
    """Inner embedder that records every call for cache-hit assertions."""

    def __init__(self, model_name: str = "spy-v1", dim: int = 4):
        self.calls: list[list[str]] = []
        self._model_name = model_name
        self._dim = dim

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        # Deterministic vector: first dim is hash-ish of text length; stable across calls.
        vecs = []
        for t in texts:
            base = float(sum(ord(c) for c in t) % 997) / 1000.0
            vecs.append([base] + [0.0] * (self._dim - 1))
        return vecs


class TestCachedEmbedder:
    def test_cached_embedder_miss_then_hit_same_instance(self, tmp_path):
        from evals.dataset.embedder import CachedEmbedder

        spy = _SpyEmbedder()
        cached = CachedEmbedder(spy, db_path=tmp_path / "cache.db")

        v1 = cached.embed(["hello"])
        v2 = cached.embed(["hello"])

        assert v1 == v2
        assert len(spy.calls) == 1  # second call was a hit
        assert spy.calls[0] == ["hello"]

    def test_cached_embedder_hit_across_instances_same_db(self, tmp_path):
        from evals.dataset.embedder import CachedEmbedder

        spy = _SpyEmbedder()
        db = tmp_path / "cache.db"

        a = CachedEmbedder(spy, db_path=db)
        v1 = a.embed(["persistent"])

        b = CachedEmbedder(spy, db_path=db)
        v2 = b.embed(["persistent"])

        assert v1 == v2
        assert len(spy.calls) == 1  # second instance read from disk cache

    def test_cached_embedder_respects_ttl(self, tmp_path):
        from evals.dataset.embedder import CachedEmbedder

        spy = _SpyEmbedder()
        cached = CachedEmbedder(spy, db_path=tmp_path / "cache.db", ttl_seconds=0)

        cached.embed(["x"])
        # Ensure clock ticks past the "created_at" for strict comparison.
        time.sleep(0.01)
        cached.embed(["x"])

        assert len(spy.calls) == 2  # ttl=0 means every lookup is expired

    def test_cached_embedder_partial_hit(self, tmp_path):
        from evals.dataset.embedder import CachedEmbedder

        spy = _SpyEmbedder()
        cached = CachedEmbedder(spy, db_path=tmp_path / "cache.db")

        first = cached.embed(["a", "b"])
        second = cached.embed(["b", "c"])

        # First call: miss on both -> one inner call with ["a", "b"].
        # Second call: hit on "b", miss on "c" -> one inner call with ["c"].
        assert spy.calls == [["a", "b"], ["c"]]
        # Order preserved: second[0] == first[1] (both are "b"); second[1] is "c".
        assert second[0] == first[1]
        assert second[1] != first[0]

    def test_cached_embedder_model_name_delegates(self, tmp_path):
        from evals.dataset.embedder import CachedEmbedder, FakeEmbedder

        cached = CachedEmbedder(FakeEmbedder(), db_path=tmp_path / "cache.db")
        assert cached.model_name == "fake-v1"

    def test_cached_embedder_different_models_are_different_keys(self, tmp_path):
        from evals.dataset.embedder import CachedEmbedder

        db = tmp_path / "cache.db"
        a_inner = _SpyEmbedder(model_name="model-a")
        b_inner = _SpyEmbedder(model_name="model-b")

        a = CachedEmbedder(a_inner, db_path=db)
        b = CachedEmbedder(b_inner, db_path=db)

        a.embed(["same-text"])
        b.embed(["same-text"])

        # Both should have been called — no collision on just text_hash.
        assert len(a_inner.calls) == 1
        assert len(b_inner.calls) == 1

    def test_cached_embedder_schema_migrate_safe(self, tmp_path):
        from evals.dataset.embedder import CachedEmbedder

        db = tmp_path / "cache.db"
        CachedEmbedder(_SpyEmbedder(), db_path=db)
        # Re-open the same DB — must not error on CREATE TABLE IF NOT EXISTS.
        CachedEmbedder(_SpyEmbedder(), db_path=db)


# ----------------------------------------------------------------------------
# get_default_embedder env helper
# ----------------------------------------------------------------------------


class TestGetDefaultEmbedder:
    def test_get_default_embedder_fake_via_env(self, monkeypatch):
        from evals.dataset import get_default_embedder
        from evals.dataset.embedder import FakeEmbedder

        monkeypatch.setenv("AGENTLAB_EMBEDDER", "fake")
        emb = get_default_embedder()
        assert isinstance(emb, FakeEmbedder)
        assert emb.model_name == "fake-v1"

    def test_get_default_embedder_default_is_cached_openai(self, monkeypatch):
        from evals.dataset import get_default_embedder
        from evals.dataset.embedder import CachedEmbedder, OpenAIEmbedder

        monkeypatch.delenv("AGENTLAB_EMBEDDER", raising=False)
        emb = get_default_embedder()
        assert isinstance(emb, CachedEmbedder)
        assert isinstance(emb.inner, OpenAIEmbedder)
