import pytest
from cli.workbench_app.tool_permissions import (
    DEFAULT_POLICIES,
    PermissionDenied,
    PermissionPending,
    PermissionTable,
    Policy,
)


def test_defaults_table_locks_down_mutating_tools():
    assert DEFAULT_POLICIES["deploy"] is Policy.ASK
    assert DEFAULT_POLICIES["improve_accept"] is Policy.ASK
    assert DEFAULT_POLICIES["improve_run"] is Policy.ASK


def test_defaults_table_allows_read_only_tools():
    assert DEFAULT_POLICIES["improve_list"] is Policy.ALLOW
    assert DEFAULT_POLICIES["improve_show"] is Policy.ALLOW
    assert DEFAULT_POLICIES["improve_diff"] is Policy.ALLOW


def test_eval_run_defaults_to_ask_not_allow():
    """eval_run runs an eval — it costs money and mutates eval-run store.
    'Read-only' applies only to tools without side effects."""
    assert DEFAULT_POLICIES["eval_run"] is Policy.ASK


def test_check_allow_returns_none():
    t = PermissionTable()
    assert t.check("improve_list") is None


def test_check_ask_raises_permission_pending():
    t = PermissionTable()
    with pytest.raises(PermissionPending) as exc:
        t.check("deploy")
    assert exc.value.tool_name == "deploy"


def test_check_deny_raises_permission_denied():
    t = PermissionTable(defaults={"x": Policy.DENY})
    with pytest.raises(PermissionDenied) as exc:
        t.check("x")
    assert exc.value.tool_name == "x"


def test_remember_promotes_ask_to_allow():
    t = PermissionTable()
    with pytest.raises(PermissionPending):
        t.check("deploy")
    t.remember("deploy", Policy.ALLOW)
    assert t.check("deploy") is None


def test_forget_restores_default():
    t = PermissionTable()
    t.remember("deploy", Policy.ALLOW)
    t.forget("deploy")
    with pytest.raises(PermissionPending):
        t.check("deploy")


def test_unknown_tool_defaults_to_ask():
    """Conservative default: a tool we forgot to register a policy for
    must NOT silently auto-allow."""
    with pytest.raises(PermissionPending):
        PermissionTable().check("brand_new_tool_we_forgot")
