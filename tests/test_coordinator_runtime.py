"""Legacy coordinator runtime contract.

The old ``CoordinatorRuntime`` API was replaced by
``CoordinatorWorkerRuntime``. The active coverage lives in
``tests/test_builder_coordinator_runtime.py`` and
``tests/test_coordinator_worker_adapters.py``.
"""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.skip(
    reason="Superseded by CoordinatorWorkerRuntime coverage.",
)


def test_legacy_coordinator_runtime_contract_superseded() -> None:
    """Collection anchor for the superseded legacy contract."""
