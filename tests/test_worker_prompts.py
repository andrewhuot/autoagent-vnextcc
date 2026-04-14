"""Structural contract tests for coordinator worker prompts (S4).

:class:`builder.worker_prompts.build_worker_prompt` composes the system +
user prompt pair that backs every LLM-driven coordinator worker. These
tests lock the contract so V1-V5 verb workstreams can rely on the shape
without re-reading the prompt module.
"""

from __future__ import annotations

import json

import pytest

from builder.specialists import SPECIALISTS, get_specialist
from builder.types import SpecialistRole, WorkerExecutionState
from builder.worker_prompts import WorkerPrompt, build_worker_prompt


_ALL_ROLES = tuple(SPECIALISTS.keys())


def _make_state(role: SpecialistRole) -> WorkerExecutionState:
    return WorkerExecutionState(
        node_id=f"node-{role.value}",
        worker_role=role,
        title=f"Test {role.value}",
    )


def _make_context(role: SpecialistRole) -> dict:
    return {
        "session_id": "sess-1",
        "task_id": "task-1",
        "goal": "Build an agent that pages an on-call when metrics spike",
        "command_intent": "build",
        "expected_artifacts": [f"{role.value}_artifact"],
        "selected_tools": ["code_search"],
        "skill_candidates": [],
        "dependency_summaries": {"requirements_analyst": "ok"},
        "context_boundary": "goal+requirements",
    }


def _make_routed() -> dict:
    return {
        "recommended_tools": ["instruction_editor"],
        "permission_scope": ["read"],
        "provenance": {"routing_reason": "role_match"},
    }


@pytest.mark.parametrize("role", _ALL_ROLES)
def test_build_worker_prompt_returns_pair(role: SpecialistRole) -> None:
    prompt = build_worker_prompt(_make_state(role), _make_context(role), _make_routed())
    assert isinstance(prompt, WorkerPrompt)
    assert isinstance(prompt.system, str) and prompt.system.strip()
    assert isinstance(prompt.user, str) and prompt.user.strip()


@pytest.mark.parametrize("role", _ALL_ROLES)
def test_system_prompt_mentions_role_display_name(role: SpecialistRole) -> None:
    specialist = get_specialist(role)
    prompt = build_worker_prompt(_make_state(role), _make_context(role), _make_routed())
    assert specialist.display_name in prompt.system


@pytest.mark.parametrize("role", _ALL_ROLES)
def test_system_prompt_declares_output_envelope(role: SpecialistRole) -> None:
    prompt = build_worker_prompt(_make_state(role), _make_context(role), _make_routed())
    for anchor in ("summary", "artifacts", "output_payload", "review_required"):
        assert anchor in prompt.system, (
            f"role {role.value} missing '{anchor}' in envelope guidance"
        )


@pytest.mark.parametrize("role", _ALL_ROLES)
def test_user_prompt_is_valid_json_with_required_keys(role: SpecialistRole) -> None:
    prompt = build_worker_prompt(_make_state(role), _make_context(role), _make_routed())
    payload = json.loads(prompt.user)
    assert isinstance(payload, dict)
    for key in (
        "goal",
        "command_intent",
        "expected_artifacts",
        "recommended_tools",
        "permission_scope",
        "selected_tools",
        "skill_candidates",
        "dependency_summaries",
    ):
        assert key in payload, (
            f"role {role.value} user prompt missing key {key!r}"
        )


def test_user_prompt_preserves_routed_permission_scope() -> None:
    role = SpecialistRole.BUILD_ENGINEER
    routed = {
        "recommended_tools": ["code_edit"],
        "permission_scope": ["read", "source_write"],
        "provenance": {"routing_reason": "matched verb build"},
    }
    prompt = build_worker_prompt(_make_state(role), _make_context(role), routed)
    payload = json.loads(prompt.user)
    assert payload["permission_scope"] == ["read", "source_write"]
    assert payload["recommended_tools"] == ["code_edit"]
    assert payload["routing_reason"] == "matched verb build"


def test_user_prompt_serialises_expected_artifacts_as_list() -> None:
    role = SpecialistRole.EVAL_AUTHOR
    prompt = build_worker_prompt(_make_state(role), _make_context(role), _make_routed())
    payload = json.loads(prompt.user)
    assert isinstance(payload["expected_artifacts"], list)
    assert payload["expected_artifacts"] == ["eval_author_artifact"]
