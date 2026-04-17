"""Tests for :mod:`cli.permissions.classifier`.

Every guardrail called out in the spec gets at least one dedicated test
here. Table-driven tests cover the bash allowlist exhaustively; the
URL/host tests cover the full zoo of "innocuous-looking bypass"
inputs we thought of (IP literals, homoglyphs, percent-encoding,
trailing dots, mixed case, unexpected schemes).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cli.permissions.classifier import (
    ClassifierContext,
    ClassifierDecision,
    classify_tool_call,
)


# ---------------------------------------------------------------------------
# Fixtures / factories
# ---------------------------------------------------------------------------


def _ctx(**overrides) -> ClassifierContext:
    """Build a ClassifierContext with sensible defaults."""
    defaults = dict(
        workspace_root=Path("/ws"),
        web_allowlist=frozenset(),
        persisted_allow_patterns=frozenset(),
        persisted_deny_patterns=frozenset(),
    )
    defaults.update(overrides)
    return ClassifierContext(**defaults)


# ---------------------------------------------------------------------------
# Persisted rule precedence
# ---------------------------------------------------------------------------


def test_persisted_deny_beats_heuristic_auto_approve():
    ctx = _ctx(persisted_deny_patterns=frozenset({"tool:Glob"}))
    assert classify_tool_call("Glob", {}, ctx) == ClassifierDecision.AUTO_DENY


def test_persisted_deny_beats_heuristic_prompt():
    ctx = _ctx(persisted_deny_patterns=frozenset({"tool:Write"}))
    assert classify_tool_call("Write", {"file_path": "/ws/x"}, ctx) == ClassifierDecision.AUTO_DENY


def test_persisted_allow_beats_heuristic_prompt():
    ctx = _ctx(persisted_allow_patterns=frozenset({"tool:Write"}))
    assert (
        classify_tool_call("Write", {"file_path": "/ws/x"}, ctx) == ClassifierDecision.AUTO_APPROVE
    )


def test_persisted_deny_wins_over_persisted_allow():
    ctx = _ctx(
        persisted_allow_patterns=frozenset({"tool:Glob"}),
        persisted_deny_patterns=frozenset({"tool:Glob"}),
    )
    assert classify_tool_call("Glob", {}, ctx) == ClassifierDecision.AUTO_DENY


def test_persisted_allow_supports_fnmatch_wildcard():
    ctx = _ctx(persisted_allow_patterns=frozenset({"tool:Write*"}))
    assert (
        classify_tool_call("Write", {"file_path": "/ws/x"}, ctx) == ClassifierDecision.AUTO_APPROVE
    )


def test_persisted_patterns_match_bare_tool_name_too():
    # Some operators prefer listing just the tool name.
    ctx = _ctx(persisted_deny_patterns=frozenset({"Glob"}))
    assert classify_tool_call("Glob", {}, ctx) == ClassifierDecision.AUTO_DENY


# ---------------------------------------------------------------------------
# Bash — allowlist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", ["ls", "ls -la", "pwd", "cat /ws/README.md", "which python"])
def test_bash_safe_first_token_auto_approves(command):
    assert (
        classify_tool_call("Bash", {"command": command}, _ctx()) == ClassifierDecision.AUTO_APPROVE
    )


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "python script.py",
        "curl https://example.com",
        "bash /tmp/run.sh",
        "echo hi",
        "node --version",
        "mkdir newdir",
    ],
)
def test_bash_disallowed_first_token_prompts(command):
    assert classify_tool_call("Bash", {"command": command}, _ctx()) == ClassifierDecision.PROMPT


@pytest.mark.parametrize("sub", ["status", "diff", "log", "show"])
def test_bash_git_read_only_subcommand_auto_approves(sub):
    cmd = f"git {sub}"
    assert classify_tool_call("Bash", {"command": cmd}, _ctx()) == ClassifierDecision.AUTO_APPROVE


def test_bash_git_status_with_safe_flag_auto_approves():
    assert (
        classify_tool_call("Bash", {"command": "git status --short"}, _ctx())
        == ClassifierDecision.AUTO_APPROVE
    )


def test_bash_ls_absolute_path_outside_workspace_prompts():
    assert (
        classify_tool_call("Bash", {"command": "ls /etc"}, _ctx())
        == ClassifierDecision.PROMPT
    )


def test_bash_git_dash_c_outside_workspace_prompts():
    assert (
        classify_tool_call("Bash", {"command": "git -C /tmp status"}, _ctx())
        == ClassifierDecision.PROMPT
    )


@pytest.mark.parametrize(
    "sub",
    ["commit", "push", "checkout", "reset", "clean", "rebase", "merge", "pull", "fetch", "tag"],
)
def test_bash_git_mutating_subcommand_prompts(sub):
    cmd = f"git {sub}"
    assert classify_tool_call("Bash", {"command": cmd}, _ctx()) == ClassifierDecision.PROMPT


def test_bash_bare_git_prompts():
    assert classify_tool_call("Bash", {"command": "git"}, _ctx()) == ClassifierDecision.PROMPT


# ---------------------------------------------------------------------------
# Bash — metacharacters and parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "ls | grep foo",
        "ls && rm -rf /",
        "ls ; rm -rf /",
        "ls > /tmp/out",
        "ls < /etc/passwd",
        "ls `whoami`",
        "ls $(whoami)",
        "ls ${HOME}",
        "ls \\n",
        "ls 'quoted arg'",
        'ls "quoted arg"',
    ],
)
def test_bash_metachars_prompt(command):
    assert classify_tool_call("Bash", {"command": command}, _ctx()) == ClassifierDecision.PROMPT


def test_bash_newline_injection_prompts():
    assert (
        classify_tool_call("Bash", {"command": "ls\nrm -rf /"}, _ctx())
        == ClassifierDecision.PROMPT
    )


def test_bash_carriage_return_injection_prompts():
    assert (
        classify_tool_call("Bash", {"command": "ls\rrm -rf /"}, _ctx())
        == ClassifierDecision.PROMPT
    )


def test_bash_null_byte_prompts():
    assert (
        classify_tool_call("Bash", {"command": "ls\x00rm -rf /"}, _ctx())
        == ClassifierDecision.PROMPT
    )


def test_bash_tab_prompts():
    assert classify_tool_call("Bash", {"command": "ls\t-la"}, _ctx()) == ClassifierDecision.PROMPT


def test_bash_shlex_parse_failure_prompts():
    # Unmatched quote — shlex.split raises ValueError. Must NOT retry
    # with posix=False.
    assert classify_tool_call("Bash", {"command": "ls 'unclosed"}, _ctx()) == ClassifierDecision.PROMPT


def test_bash_empty_command_prompts():
    assert classify_tool_call("Bash", {"command": ""}, _ctx()) == ClassifierDecision.PROMPT


def test_bash_missing_command_prompts():
    assert classify_tool_call("Bash", {}, _ctx()) == ClassifierDecision.PROMPT


def test_bash_none_command_prompts():
    assert classify_tool_call("Bash", {"command": None}, _ctx()) == ClassifierDecision.PROMPT


def test_bash_whitespace_only_prompts():
    assert classify_tool_call("Bash", {"command": "   "}, _ctx()) == ClassifierDecision.PROMPT


# ---------------------------------------------------------------------------
# Bash — cat scope checks
# ---------------------------------------------------------------------------


def test_cat_absolute_path_outside_workspace_prompts():
    ctx = _ctx(workspace_root=Path("/ws"))
    assert (
        classify_tool_call("Bash", {"command": "cat /etc/passwd"}, ctx)
        == ClassifierDecision.PROMPT
    )


def test_cat_absolute_path_inside_workspace_auto_approves():
    ctx = _ctx(workspace_root=Path("/ws"))
    assert (
        classify_tool_call("Bash", {"command": "cat /ws/README.md"}, ctx)
        == ClassifierDecision.AUTO_APPROVE
    )


def test_cat_relative_path_resolves_under_workspace():
    ctx = _ctx(workspace_root=Path("/ws"))
    assert (
        classify_tool_call("Bash", {"command": "cat ./README.md"}, ctx)
        == ClassifierDecision.AUTO_APPROVE
    )


def test_cat_relative_traversal_prompts():
    ctx = _ctx(workspace_root=Path("/ws"))
    assert (
        classify_tool_call("Bash", {"command": "cat ../secrets"}, ctx)
        == ClassifierDecision.PROMPT
    )


def test_cat_without_workspace_root_prompts_on_absolute_path():
    ctx = _ctx(workspace_root=None)
    assert (
        classify_tool_call("Bash", {"command": "cat /ws/README.md"}, ctx)
        == ClassifierDecision.PROMPT
    )


def test_cat_without_workspace_root_prompts_on_relative_path():
    ctx = _ctx(workspace_root=None)
    assert (
        classify_tool_call("Bash", {"command": "cat README.md"}, ctx) == ClassifierDecision.PROMPT
    )


def test_cat_no_arg_auto_approves():
    # "cat" alone is a read-from-stdin no-op; harmless.
    assert classify_tool_call("Bash", {"command": "cat"}, _ctx()) == ClassifierDecision.AUTO_APPROVE


# ---------------------------------------------------------------------------
# FileRead
# ---------------------------------------------------------------------------


def test_file_read_inside_workspace_auto_approves():
    ctx = _ctx(workspace_root=Path("/ws"))
    assert (
        classify_tool_call("Read", {"file_path": "/ws/README.md"}, ctx)
        == ClassifierDecision.AUTO_APPROVE
    )


def test_file_read_outside_workspace_prompts():
    ctx = _ctx(workspace_root=Path("/ws"))
    assert (
        classify_tool_call("Read", {"file_path": "/etc/passwd"}, ctx)
        == ClassifierDecision.PROMPT
    )


def test_file_read_traversal_prompts():
    ctx = _ctx(workspace_root=Path("/ws"))
    assert (
        classify_tool_call("Read", {"file_path": "/ws/../etc/passwd"}, ctx)
        == ClassifierDecision.PROMPT
    )


def test_file_read_prefix_attack_prompts():
    # ``/ws-evil/x`` must NOT pass as "inside /ws".
    ctx = _ctx(workspace_root=Path("/ws"))
    assert (
        classify_tool_call("Read", {"file_path": "/ws-evil/x"}, ctx)
        == ClassifierDecision.PROMPT
    )


def test_file_read_without_workspace_root_prompts():
    ctx = _ctx(workspace_root=None)
    assert (
        classify_tool_call("Read", {"file_path": "/anything"}, ctx) == ClassifierDecision.PROMPT
    )


def test_file_read_missing_path_prompts():
    ctx = _ctx(workspace_root=Path("/ws"))
    assert classify_tool_call("Read", {}, ctx) == ClassifierDecision.PROMPT


def test_file_read_none_path_prompts():
    ctx = _ctx(workspace_root=Path("/ws"))
    assert classify_tool_call("Read", {"file_path": None}, ctx) == ClassifierDecision.PROMPT


def test_file_read_empty_path_prompts():
    ctx = _ctx(workspace_root=Path("/ws"))
    assert classify_tool_call("Read", {"file_path": ""}, ctx) == ClassifierDecision.PROMPT


def test_file_read_relative_path_resolves_under_root():
    ctx = _ctx(workspace_root=Path("/ws"))
    assert (
        classify_tool_call("Read", {"file_path": "src/main.py"}, ctx)
        == ClassifierDecision.AUTO_APPROVE
    )


def test_file_read_accepts_alternate_key_path():
    ctx = _ctx(workspace_root=Path("/ws"))
    assert (
        classify_tool_call("Read", {"path": "/ws/a.txt"}, ctx)
        == ClassifierDecision.AUTO_APPROVE
    )


# ---------------------------------------------------------------------------
# FileWrite / FileEdit
# ---------------------------------------------------------------------------


def test_file_write_always_prompts_even_in_workspace():
    ctx = _ctx(workspace_root=Path("/ws"))
    assert (
        classify_tool_call("Write", {"file_path": "/ws/a.txt", "content": "hi"}, ctx)
        == ClassifierDecision.PROMPT
    )


def test_file_edit_always_prompts_even_in_workspace():
    ctx = _ctx(workspace_root=Path("/ws"))
    assert (
        classify_tool_call(
            "Edit",
            {"file_path": "/ws/a.txt", "old_string": "x", "new_string": "y"},
            ctx,
        )
        == ClassifierDecision.PROMPT
    )


def test_file_write_aliases_behave_the_same():
    ctx = _ctx(workspace_root=Path("/ws"))
    assert (
        classify_tool_call("FileWrite", {"file_path": "/ws/a.txt"}, ctx)
        == ClassifierDecision.PROMPT
    )
    assert (
        classify_tool_call("FileEdit", {"file_path": "/ws/a.txt"}, ctx)
        == ClassifierDecision.PROMPT
    )


# ---------------------------------------------------------------------------
# Glob / Grep
# ---------------------------------------------------------------------------


def test_glob_auto_approves():
    assert (
        classify_tool_call("Glob", {"pattern": "**/*.py"}, _ctx())
        == ClassifierDecision.AUTO_APPROVE
    )


def test_grep_auto_approves():
    assert (
        classify_tool_call("Grep", {"pattern": "def foo"}, _ctx())
        == ClassifierDecision.AUTO_APPROVE
    )


def test_glob_with_empty_input_still_auto_approves():
    assert classify_tool_call("Glob", {}, _ctx()) == ClassifierDecision.AUTO_APPROVE


def test_grep_with_none_input_still_auto_approves():
    # Non-dict input is normalised to an empty dict.
    assert classify_tool_call("Grep", None, _ctx()) == ClassifierDecision.AUTO_APPROVE


def test_glob_path_outside_workspace_prompts():
    assert (
        classify_tool_call("Glob", {"pattern": "*.py", "path": "/etc"}, _ctx())
        == ClassifierDecision.PROMPT
    )


def test_grep_path_outside_workspace_prompts():
    assert (
        classify_tool_call("Grep", {"pattern": "foo", "path": "/etc"}, _ctx())
        == ClassifierDecision.PROMPT
    )


# ---------------------------------------------------------------------------
# WebFetch — scheme / host
# ---------------------------------------------------------------------------


def test_web_fetch_allowlisted_host_auto_approves():
    ctx = _ctx(web_allowlist=frozenset({"example.com"}))
    assert (
        classify_tool_call("WebFetch", {"url": "https://example.com/docs"}, ctx)
        == ClassifierDecision.AUTO_APPROVE
    )


def test_web_fetch_http_allowed():
    ctx = _ctx(web_allowlist=frozenset({"example.com"}))
    assert (
        classify_tool_call("WebFetch", {"url": "http://example.com/"}, ctx)
        == ClassifierDecision.AUTO_APPROVE
    )


def test_web_fetch_mixed_case_host_normalises():
    ctx = _ctx(web_allowlist=frozenset({"example.com"}))
    assert (
        classify_tool_call("WebFetch", {"url": "https://EXAMPLE.COM/"}, ctx)
        == ClassifierDecision.AUTO_APPROVE
    )


def test_web_fetch_trailing_dot_host_normalises():
    ctx = _ctx(web_allowlist=frozenset({"example.com"}))
    assert (
        classify_tool_call("WebFetch", {"url": "https://example.com./"}, ctx)
        == ClassifierDecision.AUTO_APPROVE
    )


def test_web_fetch_unlisted_host_prompts():
    ctx = _ctx(web_allowlist=frozenset({"example.com"}))
    assert (
        classify_tool_call("WebFetch", {"url": "https://evil.com/"}, ctx)
        == ClassifierDecision.PROMPT
    )


def test_web_fetch_empty_allowlist_prompts():
    assert (
        classify_tool_call("WebFetch", {"url": "https://example.com/"}, _ctx())
        == ClassifierDecision.PROMPT
    )


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "data:text/html,evil",
        "gopher://example.com/",
    ],
)
def test_web_fetch_non_http_schemes_prompt(url):
    ctx = _ctx(web_allowlist=frozenset({"example.com"}))
    assert classify_tool_call("WebFetch", {"url": url}, ctx) == ClassifierDecision.PROMPT


def test_web_fetch_ip_host_prompts_even_when_in_allowlist():
    # IP literal in the allowlist must still prompt — an IP host is a
    # DNS bypass and almost always a smoke screen.
    ctx = _ctx(web_allowlist=frozenset({"127.0.0.1"}))
    assert (
        classify_tool_call("WebFetch", {"url": "http://127.0.0.1/"}, ctx)
        == ClassifierDecision.PROMPT
    )


def test_web_fetch_ipv6_host_prompts():
    ctx = _ctx(web_allowlist=frozenset({"::1"}))
    assert (
        classify_tool_call("WebFetch", {"url": "http://[::1]/"}, ctx) == ClassifierDecision.PROMPT
    )


def test_web_fetch_missing_host_prompts():
    ctx = _ctx(web_allowlist=frozenset({"example.com"}))
    assert classify_tool_call("WebFetch", {"url": "https://"}, ctx) == ClassifierDecision.PROMPT


def test_web_fetch_missing_url_prompts():
    ctx = _ctx(web_allowlist=frozenset({"example.com"}))
    assert classify_tool_call("WebFetch", {}, ctx) == ClassifierDecision.PROMPT


def test_web_fetch_none_url_prompts():
    ctx = _ctx(web_allowlist=frozenset({"example.com"}))
    assert classify_tool_call("WebFetch", {"url": None}, ctx) == ClassifierDecision.PROMPT


def test_web_fetch_cyrillic_homoglyph_prompts():
    # The "e" in "еxample.com" is Cyrillic U+0435. Must not match the
    # ASCII "example.com" entry.
    ctx = _ctx(web_allowlist=frozenset({"example.com"}))
    assert (
        classify_tool_call("WebFetch", {"url": "https://\u0435xample.com/"}, ctx)
        == ClassifierDecision.PROMPT
    )


def test_web_fetch_wildcard_allowlist_matches_subdomain():
    ctx = _ctx(web_allowlist=frozenset({"*.example.com"}))
    assert (
        classify_tool_call("WebFetch", {"url": "https://docs.example.com/"}, ctx)
        == ClassifierDecision.AUTO_APPROVE
    )


def test_web_fetch_wildcard_allowlist_matches_nested_subdomain():
    ctx = _ctx(web_allowlist=frozenset({"*.example.com"}))
    assert (
        classify_tool_call("WebFetch", {"url": "https://a.b.example.com/"}, ctx)
        == ClassifierDecision.AUTO_APPROVE
    )


def test_web_fetch_wildcard_does_not_match_apex():
    # ``*.example.com`` is "any subdomain" — the bare apex must be
    # listed explicitly.
    ctx = _ctx(web_allowlist=frozenset({"*.example.com"}))
    assert (
        classify_tool_call("WebFetch", {"url": "https://example.com/"}, ctx)
        == ClassifierDecision.PROMPT
    )


def test_web_fetch_wildcard_does_not_match_unrelated_suffix():
    ctx = _ctx(web_allowlist=frozenset({"*.example.com"}))
    assert (
        classify_tool_call("WebFetch", {"url": "https://evilexample.com/"}, ctx)
        == ClassifierDecision.PROMPT
    )


def test_web_fetch_percent_encoded_host_prompts():
    # Percent-encoding in the host portion is not standard; urlparse
    # will leave it literal, and the literal won't match the
    # allowlist entry.
    ctx = _ctx(web_allowlist=frozenset({"evil.com"}))
    assert (
        classify_tool_call("WebFetch", {"url": "https://%65vil.com/"}, ctx)
        == ClassifierDecision.PROMPT
    )


# ---------------------------------------------------------------------------
# WebSearch
# ---------------------------------------------------------------------------


def test_web_search_plain_query_auto_approves():
    assert (
        classify_tool_call("WebSearch", {"query": "best llm benchmarks 2026"}, _ctx())
        == ClassifierDecision.AUTO_APPROVE
    )


def test_web_search_with_url_query_applies_allowlist():
    ctx = _ctx(web_allowlist=frozenset({"example.com"}))
    assert (
        classify_tool_call("WebSearch", {"query": "https://example.com/foo"}, ctx)
        == ClassifierDecision.AUTO_APPROVE
    )


def test_web_search_with_disallowed_url_query_prompts():
    ctx = _ctx(web_allowlist=frozenset({"example.com"}))
    assert (
        classify_tool_call("WebSearch", {"query": "https://evil.com/"}, ctx)
        == ClassifierDecision.PROMPT
    )


def test_web_search_with_file_url_query_prompts():
    assert (
        classify_tool_call("WebSearch", {"query": "file:///etc/passwd"}, _ctx())
        == ClassifierDecision.PROMPT
    )


def test_web_search_missing_query_auto_approves():
    # A search with no query is a no-op — harmless.
    assert classify_tool_call("WebSearch", {}, _ctx()) == ClassifierDecision.AUTO_APPROVE


# ---------------------------------------------------------------------------
# Unknown tools and MCP
# ---------------------------------------------------------------------------


def test_unknown_tool_prompts():
    assert classify_tool_call("SomeRandomTool", {}, _ctx()) == ClassifierDecision.PROMPT


@pytest.mark.parametrize(
    "tool_name",
    [
        "mcp__github__create_issue",
        "mcp-github-create-issue",
        "tool:mcp:github:create_issue",
        "MCP__LOUD_NAME",
    ],
)
def test_mcp_tools_always_prompt(tool_name):
    assert classify_tool_call(tool_name, {}, _ctx()) == ClassifierDecision.PROMPT


def test_mcp_tool_persisted_allow_can_override():
    # Operators who explicitly allowlist an MCP tool via persisted
    # patterns opt into auto-approve — the MCP prompt-always rule only
    # applies to the heuristic layer.
    ctx = _ctx(persisted_allow_patterns=frozenset({"tool:mcp__github__create_issue"}))
    assert (
        classify_tool_call("mcp__github__create_issue", {}, ctx)
        == ClassifierDecision.AUTO_APPROVE
    )


def test_mcp_tool_persisted_deny_applies():
    ctx = _ctx(persisted_deny_patterns=frozenset({"tool:mcp__*"}))
    assert (
        classify_tool_call("mcp__github__create_issue", {}, ctx) == ClassifierDecision.AUTO_DENY
    )


# ---------------------------------------------------------------------------
# Degenerate inputs
# ---------------------------------------------------------------------------


def test_non_dict_input_is_normalised():
    # ``None`` / string tool_input should not crash — the classifier
    # treats them as an empty dict.
    assert classify_tool_call("Glob", None, _ctx()) == ClassifierDecision.AUTO_APPROVE
    assert classify_tool_call("Bash", "ls -la", _ctx()) == ClassifierDecision.PROMPT


def test_empty_string_tool_name_prompts():
    assert classify_tool_call("", {}, _ctx()) == ClassifierDecision.PROMPT
