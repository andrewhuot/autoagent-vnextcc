"""Tests for coverage signal injection into the LLM proposer prompt (R3.2)."""

from unittest.mock import MagicMock

from optimizer.llm_proposer import LLMProposer, _build_user_prompt

_BASE_KWARGS = dict(
    agent_card_markdown="# Agent",
    failure_analysis=None,
    past_attempts=None,
    objective="improve quality",
    constraints=None,
    available_mutations=[
        {"type": "instruction", "description": "Rewrite system prompts"},
    ],
)


def test_prompt_includes_coverage_section_when_signal_present() -> None:
    prompt = _build_user_prompt(
        **_BASE_KWARGS,
        coverage_signal=[("api", "high", 8), ("cli", "low", 2)],
    )
    assert "Eval Coverage Gaps" in prompt
    assert "api" in prompt
    # Delta 8 and severity HIGH must both appear.
    assert "8" in prompt
    assert "HIGH" in prompt.upper()
    assert "cli" in prompt
    assert "2" in prompt


def test_prompt_omits_coverage_section_when_signal_none() -> None:
    prompt = _build_user_prompt(**_BASE_KWARGS, coverage_signal=None)
    assert "Eval Coverage Gaps" not in prompt


def test_prompt_omits_coverage_section_when_signal_empty() -> None:
    prompt = _build_user_prompt(**_BASE_KWARGS, coverage_signal=[])
    assert "Eval Coverage Gaps" not in prompt


def test_coverage_section_renders_after_failure_analysis() -> None:
    """Coverage section should appear after Failure Analysis, before Past Attempts."""
    prompt = _build_user_prompt(
        **_BASE_KWARGS,
        coverage_signal=[("api", "critical", 10)],
    )
    fa_idx = prompt.index("Failure Analysis")
    cov_idx = prompt.index("Eval Coverage Gaps")
    past_idx = prompt.index("Past Optimization Attempts")
    assert fa_idx < cov_idx < past_idx


def test_coverage_severities_ordered_critical_first() -> None:
    """Render order mirrors the input signal order (already sorted by gap_signal())."""
    prompt = _build_user_prompt(
        **_BASE_KWARGS,
        coverage_signal=[
            ("auth", "critical", 4),
            ("api", "high", 8),
            ("cli", "low", 2),
        ],
    )
    auth_idx = prompt.index("auth")
    api_idx = prompt.index("api")
    cli_idx = prompt.index("cli")
    assert auth_idx < api_idx < cli_idx


def test_llmproposer_propose_passes_coverage_signal_to_prompt() -> None:
    """LLMProposer.propose forwards coverage_signal into the prompt."""
    router = MagicMock()
    router.generate.return_value = MagicMock(
        text='{"proposal": {"mutation_type": "instruction", "target_agent": "root", '
             '"target_surface": "instruction", "change_description": "x", '
             '"reasoning": "y", "config_patch": {"prompts": {"root": "new"}}, '
             '"expected_impact": "low", "risk_assessment": "low"}, '
             '"analysis_summary": "s", "confidence": 0.5}',
        model="mock",
    )
    proposer = LLMProposer(llm_router=router)
    proposer.propose(
        current_config={"name": "root", "prompts": {"root": "old"}},
        agent_card_markdown="# Agent",
        coverage_signal=[("api", "high", 8)],
    )
    # Inspect the prompt sent to the router.
    call_args = router.generate.call_args
    llm_request = call_args[0][0] if call_args[0] else call_args[1]["request"]
    assert "Eval Coverage Gaps" in llm_request.prompt
    assert "api" in llm_request.prompt
