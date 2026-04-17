"""B.6 — Opt-in pairwise aggregator hook in CanaryManager.

Tests the override rule: pairwise can downgrade a legacy "promote" to
"rollback" iff it prefers baseline; it never overrides a legacy
"rollback" or "pending"/"no_canary"; aggregator failures never break
the deploy path.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import pytest

from deployer.canary import CanaryManager, CanaryStatus


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeAggregator:
    """Captures kwargs and returns a canned verdict (or raises)."""

    def __init__(self, verdict, *, raises: BaseException | None = None) -> None:
        self._verdict = verdict
        self._raises = raises
        self.calls: list[dict[str, Any]] = []

    def score_recent(self, **kw):
        self.calls.append(kw)
        if self._raises is not None:
            raise self._raises
        return self._verdict


@dataclass
class _FakeConvo:
    outcome: str


class FakeStore:
    """Returns canned conversation lists keyed by config_version label."""

    def __init__(self, by_label: dict[str, list[_FakeConvo]]) -> None:
        self._by_label = by_label

    def get_by_config_version(self, label: str, *, limit: int | None = None):
        convos = list(self._by_label.get(label, []))
        if limit is not None:
            convos = convos[:limit]
        return convos


class FakeVersionManager:
    """Minimal stand-in exposing only `manifest`."""

    def __init__(self, *, canary_version: int | None, active_version: int | None) -> None:
        versions = []
        if active_version is not None:
            versions.append({"version": active_version, "timestamp": time.time(), "status": "active"})
        if canary_version is not None:
            versions.append({"version": canary_version, "timestamp": time.time(), "status": "canary"})
        self.manifest = {
            "canary_version": canary_version,
            "active_version": active_version,
            "versions": versions,
        }


def _make_verdict(preferred: str, candidate_wins: int = 5, baseline_wins: int = 2, ties: int = 0):
    from optimizer.canary_scoring import CanaryVerdict

    n = candidate_wins + baseline_wins + ties
    denom = candidate_wins + baseline_wins
    return CanaryVerdict(
        baseline_label="v001",
        candidate_label="v002",
        baseline_wins=baseline_wins,
        candidate_wins=candidate_wins,
        ties=ties,
        n_pairs=n,
        win_rate_candidate=(candidate_wins / denom) if denom else float("nan"),
        preferred=preferred,
        ci95_candidate_winrate=(0.3, 0.8),
        judged_at=0.0,
    )


def _store_for_promote() -> FakeStore:
    """Canary 9/1, baseline 4/6 → legacy verdict 'promote'."""
    return FakeStore(
        {
            "v002": [_FakeConvo("success")] * 9 + [_FakeConvo("fail")] * 1,
            "v001": [_FakeConvo("success")] * 4 + [_FakeConvo("fail")] * 6,
        }
    )


def _store_for_rollback() -> FakeStore:
    """Canary 3/7, baseline 9/1 → legacy verdict 'rollback'."""
    return FakeStore(
        {
            "v002": [_FakeConvo("success")] * 3 + [_FakeConvo("fail")] * 7,
            "v001": [_FakeConvo("success")] * 9 + [_FakeConvo("fail")] * 1,
        }
    )


def _make_manager(*, store: FakeStore, aggregator=None) -> CanaryManager:
    vm = FakeVersionManager(canary_version=2, active_version=1)
    kwargs: dict[str, Any] = dict(
        version_manager=vm,
        store=store,
        min_canary_conversations=5,
        max_canary_duration_s=9999,
    )
    if aggregator is not None:
        kwargs["pairwise_aggregator"] = aggregator
    return CanaryManager(**kwargs)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_canary_manager_ignores_aggregator_when_none() -> None:
    """No pairwise_aggregator → legacy path, both new fields are None."""
    mgr = _make_manager(store=_store_for_promote())
    status = mgr.check_canary()
    assert status.verdict == "promote"
    assert status.pairwise_verdict is None
    assert status.pairwise_preferred is None


def test_canary_manager_legacy_rollback_unchanged_by_pairwise_candidate() -> None:
    """Pairwise prefers candidate but legacy says rollback → still rollback."""
    agg = FakeAggregator(_make_verdict("candidate"))
    mgr = _make_manager(store=_store_for_rollback(), aggregator=agg)
    status = mgr.check_canary()
    assert status.verdict == "rollback"
    assert status.pairwise_preferred == "candidate"


def test_canary_manager_promote_downgrades_to_rollback_when_pairwise_prefers_baseline() -> None:
    """Legacy promote + pairwise prefers baseline → rollback."""
    agg = FakeAggregator(_make_verdict("baseline", candidate_wins=2, baseline_wins=5))
    mgr = _make_manager(store=_store_for_promote(), aggregator=agg)
    status = mgr.check_canary()
    assert status.verdict == "rollback"
    assert status.pairwise_preferred == "baseline"
    assert status.pairwise_verdict is not None
    assert status.pairwise_verdict.preferred == "baseline"


def test_canary_manager_promote_unchanged_when_pairwise_prefers_candidate() -> None:
    """Legacy promote + pairwise prefers candidate → promote stays."""
    agg = FakeAggregator(_make_verdict("candidate"))
    mgr = _make_manager(store=_store_for_promote(), aggregator=agg)
    status = mgr.check_canary()
    assert status.verdict == "promote"
    assert status.pairwise_preferred == "candidate"


def test_canary_manager_promote_unchanged_when_pairwise_ties() -> None:
    """Legacy promote + pairwise tie → promote stays."""
    agg = FakeAggregator(_make_verdict("tie", candidate_wins=3, baseline_wins=3, ties=4))
    mgr = _make_manager(store=_store_for_promote(), aggregator=agg)
    status = mgr.check_canary()
    assert status.verdict == "promote"
    assert status.pairwise_preferred == "tie"


def test_canary_manager_aggregator_returns_none_leaves_legacy_unchanged() -> None:
    """Aggregator returns None (too few pairs) → legacy verdict, fields None."""
    agg = FakeAggregator(None)
    mgr = _make_manager(store=_store_for_promote(), aggregator=agg)
    status = mgr.check_canary()
    assert status.verdict == "promote"
    assert status.pairwise_verdict is None
    assert status.pairwise_preferred is None


def test_canary_manager_aggregator_raises_does_not_break_check_canary() -> None:
    """Aggregator exception is swallowed; legacy verdict returned."""
    agg = FakeAggregator(None, raises=RuntimeError("scoring boom"))
    mgr = _make_manager(store=_store_for_promote(), aggregator=agg)
    status = mgr.check_canary()
    assert status.verdict == "promote"
    assert status.pairwise_verdict is None
    assert status.pairwise_preferred is None


def test_canary_manager_passes_correct_labels_to_aggregator() -> None:
    """Aggregator receives baseline_label='v001', candidate_label='v002'."""
    agg = FakeAggregator(_make_verdict("candidate"))
    mgr = _make_manager(store=_store_for_promote(), aggregator=agg)
    mgr.check_canary()
    assert len(agg.calls) == 1
    call = agg.calls[0]
    assert call["baseline_label"] == "v001"
    assert call["candidate_label"] == "v002"


def test_canary_manager_no_canary_skips_aggregator() -> None:
    """canary_version is None → aggregator not called, verdict 'no_canary'."""
    vm = FakeVersionManager(canary_version=None, active_version=1)
    agg = FakeAggregator(_make_verdict("baseline"))
    mgr = CanaryManager(
        version_manager=vm,
        store=FakeStore({}),
        pairwise_aggregator=agg,
    )
    status = mgr.check_canary()
    assert status.verdict == "no_canary"
    assert status.pairwise_verdict is None
    assert status.pairwise_preferred is None
    assert agg.calls == []


def test_canary_status_new_fields_default_to_none() -> None:
    """Pre-R6 callers can construct CanaryStatus without the new fields."""
    status = CanaryStatus(
        is_active=False,
        canary_version=None,
        baseline_version=1,
        canary_conversations=0,
        canary_success_rate=0.0,
        baseline_success_rate=0.0,
        started_at=0.0,
        verdict="no_canary",
    )
    assert status.pairwise_verdict is None
    assert status.pairwise_preferred is None


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
