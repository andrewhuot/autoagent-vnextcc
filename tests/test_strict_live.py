import pytest
from cli.strict_live import StrictLivePolicy, MockFallbackError


def test_policy_disabled_allows_mock_warnings():
    policy = StrictLivePolicy(enabled=False)
    policy.record_mock_warning("provider returned 403, used mock fallback")
    # Should not raise.
    assert policy.has_fallback() is True
    assert policy.warnings == ["provider returned 403, used mock fallback"]


def test_policy_enabled_raises_on_first_warning():
    policy = StrictLivePolicy(enabled=True)
    with pytest.raises(MockFallbackError) as exc:
        policy.record_mock_warning("provider returned 403, used mock fallback")
    assert "strict-live" in str(exc.value).lower()
    assert "provider returned 403" in str(exc.value)


def test_policy_enabled_check_after_run_raises_when_warnings_present():
    """Some warnings are appended post-hoc to the score object; policy must
    expose a final check() method that raises if any accumulated."""
    policy = StrictLivePolicy(enabled=True)
    # Simulate post-hoc warning ingestion (not via record_mock_warning).
    policy.ingest_existing_warnings(["eval_run.live_fallback_to_mock: gemini 429"])
    with pytest.raises(MockFallbackError):
        policy.check()


def test_policy_enabled_check_passes_when_no_warnings():
    policy = StrictLivePolicy(enabled=True)
    policy.check()  # no raise
