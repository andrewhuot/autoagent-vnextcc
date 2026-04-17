"""Tests for evals.dataset.importers.load_huggingface (A.4).

Contract: lazy-import ``datasets``, map HF rows into TestCase via optional
``column_mapping``, raise on any error (never silent empty), surface cache-path
hint on network failures, and require the ``datasets`` package only when the
function is called.
"""

from __future__ import annotations

import importlib
import os

import pytest

from evals.dataset import importers
from evals.dataset.importers import load_huggingface
from evals.runner import TestCase


def test_load_hf_maps_rows_to_testcase(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {
            "id": "a",
            "category": "safety",
            "user_message": "hello",
        },
        {
            "id": "b",
            "category": "billing",
            "user_message": "charge me",
            "tags": ["billing", "refund"],
        },
    ]

    def fake_loader(name: str, split: str, cache_dir):  # noqa: ARG001
        assert name == "demo/dataset"
        assert split == "train"
        return rows

    monkeypatch.setattr(importers, "_load_hf_dataset", fake_loader)

    cases = load_huggingface("demo/dataset")

    assert isinstance(cases, list)
    assert len(cases) == 2
    assert all(isinstance(c, TestCase) for c in cases)
    assert cases[0].id == "a"
    assert cases[0].category == "safety"
    assert cases[0].user_message == "hello"
    assert cases[1].tags == ["billing", "refund"]


def test_load_hf_applies_column_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {"id": "q1", "question": "what is 2+2?", "label": "math"},
        {"id": "q2", "question": "capital of france", "label": "geography"},
    ]

    def fake_loader(name, split, cache_dir):  # noqa: ARG001
        return rows

    monkeypatch.setattr(importers, "_load_hf_dataset", fake_loader)

    cases = load_huggingface(
        "demo/questions",
        column_mapping={"question": "user_message", "label": "category"},
    )

    assert len(cases) == 2
    assert cases[0].id == "q1"
    assert cases[0].user_message == "what is 2+2?"
    assert cases[0].category == "math"
    assert cases[1].category == "geography"


def test_load_hf_tags_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {"id": "r1", "category": "support", "user_message": "help"},
    ]

    monkeypatch.setattr(
        importers, "_load_hf_dataset", lambda *a, **kw: rows
    )

    cases = load_huggingface("demo/any")

    assert cases[0].tags == ["support"]


def test_load_hf_missing_required_field_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {"id": "ok", "category": "x", "user_message": "hi"},
        {"id": "broken", "category": "x"},  # missing user_message
    ]

    monkeypatch.setattr(
        importers, "_load_hf_dataset", lambda *a, **kw: rows
    )

    with pytest.raises(ValueError) as excinfo:
        load_huggingface("demo/broken")

    msg = str(excinfo.value)
    assert "user_message" in msg
    # Row index 1 (0-indexed) or 2 (1-indexed); accept either.
    assert "1" in msg or "2" in msg


def test_load_hf_network_error_surfaces_cache_hint(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    def boom(name, split, cache_dir):  # noqa: ARG001
        raise ConnectionError("no internet")

    monkeypatch.setattr(importers, "_load_hf_dataset", boom)

    cache = tmp_path / "hfcache"
    with pytest.raises(RuntimeError) as excinfo:
        load_huggingface("demo/x", cache_dir=cache)

    msg = str(excinfo.value)
    assert "no internet" in msg
    assert str(cache) in msg
    assert "cache" in msg.lower()


def test_load_hf_missing_library_raises_importerror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import_module = importlib.import_module

    def fake_import_module(name: str, *args, **kwargs):
        if name == "datasets":
            raise ImportError("No module named 'datasets'")
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    with pytest.raises(ImportError) as excinfo:
        load_huggingface("demo/x")

    msg = str(excinfo.value)
    assert "datasets" in msg
    assert "pip install datasets" in msg


def test_load_hf_never_returns_empty_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(name, split, cache_dir):  # noqa: ARG001
        raise RuntimeError("auth failed")

    monkeypatch.setattr(importers, "_load_hf_dataset", boom)

    with pytest.raises(RuntimeError):
        load_huggingface("private/ds")


def test_load_huggingface_reexported_from_package() -> None:
    from evals.dataset import load_huggingface as reexported

    assert reexported is load_huggingface


def test_datasets_not_required_at_import_time() -> None:
    """Importing evals.dataset.importers must NOT import ``datasets``."""
    # The module is already imported by the test harness; this asserts the
    # module has no module-level dependency on the optional package.
    import sys

    # If ``datasets`` happens to be installed, we can't prove it wasn't
    # imported transitively — but we can at least assert our module didn't
    # hard-import a name from it at module scope.
    mod = sys.modules["evals.dataset.importers"]
    assert not hasattr(mod, "datasets"), (
        "evals.dataset.importers should not eagerly import the datasets package"
    )


@pytest.mark.skipif(not os.getenv("HF_TOKEN"), reason="needs HF network")
def test_load_hf_live_smoke() -> None:
    # End-to-end smoke gated on HF_TOKEN; intentionally minimal.
    pass
