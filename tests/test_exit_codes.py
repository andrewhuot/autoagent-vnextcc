from cli.exit_codes import (
    EXIT_OK,
    EXIT_MOCK_FALLBACK,
    EXIT_DEGRADED_DEPLOY,
    EXIT_MISSING_PROVIDER,
)


def test_exit_codes_are_distinct_and_nonzero_for_failure():
    assert EXIT_OK == 0
    assert EXIT_MOCK_FALLBACK == 12
    assert EXIT_DEGRADED_DEPLOY == 13
    assert EXIT_MISSING_PROVIDER == 14
    codes = {EXIT_OK, EXIT_MOCK_FALLBACK, EXIT_DEGRADED_DEPLOY, EXIT_MISSING_PROVIDER}
    assert len(codes) == 4
