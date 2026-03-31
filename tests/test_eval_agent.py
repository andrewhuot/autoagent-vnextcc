"""Tests for live eval-agent fallback behavior."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

import agent
from agent.eval_agent import ConfiguredEvalAgent, _load_default_config
from evals.fixtures.mock_data import mock_agent_response
from runner import cli


class FailingRouter:
    """Router stub that simulates a live-provider failure."""

    mock_mode = False
    mock_reason = ""

    def generate(self, request):  # noqa: ANN001
        del request
        raise RuntimeError("provider unavailable")


class RecordingRouter:
    """Router stub that records the latest request and returns a canned response."""

    mock_mode = False
    mock_reason = ""

    def __init__(self) -> None:
        self.requests = []

    def generate(self, request):  # noqa: ANN001
        self.requests.append(request)

        class Response:
            text = "I can help with that."
            latency_ms = 12.0
            total_tokens = 34

        return Response()


def _read_json(path: Path) -> dict:
    """Load a JSON file used by CLI assertions."""
    return json.loads(path.read_text(encoding="utf-8"))


def test_configured_eval_agent_falls_back_to_mock_on_provider_error() -> None:
    """Provider failures should degrade to deterministic mock responses instead of crashing evals."""
    default_config = _load_default_config()
    eval_agent = ConfiguredEvalAgent(
        llm_router=FailingRouter(),
        default_config=default_config,
    )

    result = eval_agent.run("How do I reset my password?")

    assert result == mock_agent_response("How do I reset my password?", default_config)
    assert eval_agent.mock_mode is True
    assert any("falling back to deterministic mock responses" in message.lower() for message in eval_agent.mock_mode_messages)


def test_configured_eval_agent_merges_root_xml_with_specialist_xml() -> None:
    """XML prompts should merge into one valid instruction before the provider call."""
    router = RecordingRouter()
    default_config = _load_default_config()
    default_config["prompts"]["root"] = """
<role>Routing coordinator.</role>
<persona>
  <primary_goal>Route requests safely.</primary_goal>
  Stay concise.
</persona>
<constraints>
  1. Ask a clarifying question when the request is ambiguous.
</constraints>
<taskflow>
  <subtask name="Routing">
    <step name="Assess Request">
      <trigger>User sends a request.</trigger>
      <action>Choose the best specialist.</action>
    </step>
  </subtask>
</taskflow>
<examples>
</examples>
""".strip()
    default_config["prompts"]["support"] = """
<role>Customer support specialist.</role>
<persona>
  <primary_goal>Resolve support issues empathetically.</primary_goal>
  Be warm and practical.
</persona>
<constraints>
  1. Confirm the order number before changing account state.
</constraints>
<taskflow>
  <subtask name="Support">
    <step name="Resolve Issue">
      <trigger>User reports a support issue.</trigger>
      <action>Explain the next best step clearly.</action>
    </step>
  </subtask>
</taskflow>
<examples>
</examples>
""".strip()

    eval_agent = ConfiguredEvalAgent(
        llm_router=router,
        default_config=default_config,
    )

    result = eval_agent.run("My order arrived damaged and I need help.")

    assert result["response"] == "I can help with that."
    assert router.requests
    assert "<role>Customer support specialist.</role>" in router.requests[-1].system
    assert "Confirm the order number before changing account state." in router.requests[-1].system
    assert "Ask a clarifying question when the request is ambiguous." in router.requests[-1].system
    assert router.requests[-1].system.count("<role>") == 1


def test_configured_eval_agent_applies_xml_section_overrides_per_run() -> None:
    """Per-run XML section overrides should replace the targeted sections before sending the request."""
    router = RecordingRouter()
    default_config = _load_default_config()
    default_config["prompts"]["root"] = """
<role>Customer support specialist.</role>
<persona>
  <primary_goal>Resolve support issues.</primary_goal>
  Be concise.
</persona>
<constraints>
  1. Verify the order number before account changes.
</constraints>
<taskflow>
  <subtask name="Support">
    <step name="Resolve">
      <trigger>User asks for help.</trigger>
      <action>Answer directly.</action>
    </step>
  </subtask>
</taskflow>
<examples>
</examples>
""".strip()

    eval_agent = ConfiguredEvalAgent(
        llm_router=router,
        default_config=default_config,
    )

    eval_agent.run(
        "Help me cancel my order.",
        {
            **default_config,
            "_instruction_overrides": {
                "constraints": ["Always confirm the cancellation reason before taking action."],
            },
        },
    )

    assert router.requests
    assert "Always confirm the cancellation reason before taking action." in router.requests[-1].system
    assert "Verify the order number before account changes." not in router.requests[-1].system


def test_configured_eval_agent_rejects_invalid_xml_before_provider_call() -> None:
    """Invalid XML instructions should fail validation before a model request is sent."""
    router = RecordingRouter()
    default_config = _load_default_config()
    default_config["prompts"]["root"] = "<role>Broken root</role><persona>"
    eval_agent = ConfiguredEvalAgent(
        llm_router=router,
        default_config=default_config,
    )

    try:
        eval_agent.run("Can you help me?")
    except ValueError as exc:
        assert "xml" in str(exc).lower()
    else:  # pragma: no cover - defensive
        raise AssertionError("Expected invalid XML to raise ValueError")

    assert router.requests == []


def test_eval_run_real_agent_survives_provider_errors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """`autoagent eval run --real-agent` should finish even when the live router fails."""
    runner = CliRunner()
    workspace = tmp_path / "fallback-agent"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace), "--no-synthetic-data"])
    assert init_result.exit_code == 0, init_result.output

    monkeypatch.chdir(workspace)
    failing_agent = ConfiguredEvalAgent(
        llm_router=FailingRouter(),
        default_config=_load_default_config(),
    )
    monkeypatch.setattr(
        agent,
        "create_eval_agent",
        lambda runtime, force_real_agent=False, default_config=None: failing_agent,
    )

    result = runner.invoke(cli, ["eval", "run", "--real-agent"])

    assert result.exit_code == 0, result.output
    assert "mixed mode" in result.output.lower()
    assert "Warning:" in result.output
    assert "falling back to deterministic mock responses" in result.output.lower()
    latest = _read_json(workspace / ".autoagent" / "eval_results_latest.json")
    assert latest["mode"] == "mixed"
    assert latest["total"] == 3
    assert latest["passed"] >= 2
    assert any(
        "falling back to deterministic mock responses" in warning.lower()
        for warning in latest["scores"]["warnings"]
    )
    assert failing_agent.mock_mode is True


def test_eval_run_require_live_fails_when_provider_falls_back(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """`autoagent eval run --require-live` should fail instead of silently persisting mock results."""
    runner = CliRunner()
    workspace = tmp_path / "require-live-agent"
    init_result = runner.invoke(cli, ["init", "--dir", str(workspace), "--no-synthetic-data"])
    assert init_result.exit_code == 0, init_result.output

    monkeypatch.chdir(workspace)
    failing_agent = ConfiguredEvalAgent(
        llm_router=FailingRouter(),
        default_config=_load_default_config(),
    )
    monkeypatch.setattr(
        agent,
        "create_eval_agent",
        lambda runtime, force_real_agent=False, default_config=None: failing_agent,
    )

    result = runner.invoke(cli, ["eval", "run", "--require-live"])

    assert result.exit_code != 0
    assert "require live" in result.output.lower() or "live eval required" in result.output.lower()
    assert not (workspace / ".autoagent" / "eval_results_latest.json").exists()
