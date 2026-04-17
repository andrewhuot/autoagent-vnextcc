"""Tests for the ``audit_log`` kwarg on :func:`execute_tool_call`.

The audit log is opt-in: callers pass a :class:`ClassifierAuditLog`
(or any object with the same ``record`` signature) and the executor
records one line per classifier decision (auto-approve / auto-deny /
prompt). ``None`` means no recording — existing callers see no change.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from cli.permissions import PermissionManager
from cli.permissions.classifier import ClassifierContext, ClassifierDecision
from cli.tools import ToolRegistry
from cli.tools.base import ToolContext
from cli.tools.bash_tool import BashTool
from cli.tools.executor import execute_tool_call
from cli.workbench_app.permission_dialog import DialogChoice, DialogOutcome


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    (tmp_path / ".agentlab").mkdir()
    return tmp_path


@pytest.fixture
def context(workspace: Path) -> ToolContext:
    return ToolContext(workspace_root=workspace)


def _ctx(workspace: Path) -> ClassifierContext:
    return ClassifierContext(workspace_root=workspace)


def test_audit_log_records_auto_approve(
    workspace: Path, context: ToolContext
) -> None:
    """AUTO_APPROVE for a whitelisted bash command must emit one entry
    with ``decision="auto_approve"``."""
    registry = ToolRegistry()
    registry.register(BashTool())
    manager = PermissionManager(root=workspace)
    audit = MagicMock()

    execute_tool_call(
        "Bash",
        {"command": "ls"},
        registry=registry,
        permissions=manager,
        context=context,
        classifier_context=_ctx(workspace),
        audit_log=audit,
    )

    assert audit.record.call_count == 1
    kwargs = audit.record.call_args.kwargs
    assert kwargs["tool_name"] == "Bash"
    assert kwargs["decision"] == ClassifierDecision.AUTO_APPROVE
    # input_digest must be set and look like a sha256:<hex> token
    assert kwargs["tool_input_digest"].startswith("sha256:")


def test_audit_log_records_auto_deny(
    workspace: Path, context: ToolContext
) -> None:
    """AUTO_DENY from a persisted deny pattern must emit one entry with
    ``decision="auto_deny"``."""
    registry = ToolRegistry()
    registry.register(BashTool())
    manager = PermissionManager(root=workspace)
    audit = MagicMock()

    ctx = ClassifierContext(
        workspace_root=workspace,
        persisted_deny_patterns=frozenset({"Bash"}),
    )

    execute_tool_call(
        "Bash",
        {"command": "ls"},
        registry=registry,
        permissions=manager,
        context=context,
        classifier_context=ctx,
        audit_log=audit,
    )

    assert audit.record.call_count == 1
    kwargs = audit.record.call_args.kwargs
    assert kwargs["tool_name"] == "Bash"
    assert kwargs["decision"] == ClassifierDecision.AUTO_DENY


def test_audit_log_records_prompt_fallthrough(
    workspace: Path, context: ToolContext
) -> None:
    """PROMPT (classifier returns PROMPT, user approves) must still emit
    one entry with ``decision="prompt"`` so operators can see which
    tools fell through to the dialog."""
    registry = ToolRegistry()
    registry.register(BashTool())
    manager = PermissionManager(root=workspace)
    audit = MagicMock()

    def dialog(
        tool: Any, tool_input: Any, *, include_persist_option: bool
    ) -> DialogOutcome:
        return DialogOutcome(
            choice=DialogChoice.APPROVE,
            allow=True,
            persist_rule=None,
            persist_scope=None,
        )

    execute_tool_call(
        "Bash",
        # Unknown first token → classifier PROMPT
        {"command": "banana-custom-script"},
        registry=registry,
        permissions=manager,
        context=context,
        dialog_runner=dialog,
        classifier_context=_ctx(workspace),
        audit_log=audit,
    )

    assert audit.record.call_count == 1
    kwargs = audit.record.call_args.kwargs
    assert kwargs["decision"] == ClassifierDecision.PROMPT


def test_audit_log_none_is_noop(
    workspace: Path, context: ToolContext
) -> None:
    """``audit_log=None`` must neither crash nor attempt to call
    ``record``. This is the existing-caller back-compat contract."""
    registry = ToolRegistry()
    registry.register(BashTool())
    manager = PermissionManager(root=workspace)

    # No audit_log kwarg at all — existing callers.
    execution = execute_tool_call(
        "Bash",
        {"command": "ls"},
        registry=registry,
        permissions=manager,
        context=context,
        classifier_context=_ctx(workspace),
    )

    assert execution.decision.value == "allow"

    # Explicit None — same path, must not crash.
    execution2 = execute_tool_call(
        "Bash",
        {"command": "ls"},
        registry=registry,
        permissions=manager,
        context=context,
        classifier_context=_ctx(workspace),
        audit_log=None,
    )

    assert execution2.decision.value == "allow"
