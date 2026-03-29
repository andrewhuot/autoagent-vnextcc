"""Regression tests for default SQLite path collisions in audit stores."""

from __future__ import annotations

import inspect

from api.audit import AuditStore
from control.audit import AuditLog


def test_api_and_control_audit_stores_do_not_share_default_db_path() -> None:
    """The two incompatible audit schemas must not point at the same default SQLite file."""
    api_default = inspect.signature(AuditStore).parameters["db_path"].default
    control_default = inspect.signature(AuditLog).parameters["db_path"].default

    assert api_default != control_default
