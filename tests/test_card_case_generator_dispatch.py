"""Tests for grow_cases_for_surface dispatcher (R3.6 helper)."""

from unittest.mock import MagicMock

from evals.card_case_generator import grow_cases_for_surface


def test_dispatch_routing_calls_routing_generator() -> None:
    gen = MagicMock()
    gen.generate_routing_cases.return_value = ["c1", "c2"]
    card = MagicMock()
    out = grow_cases_for_surface(gen, card, "routing", count=5)
    gen.generate_routing_cases.assert_called_once_with(card, count=5)
    assert out == ["c1", "c2"]


def test_dispatch_tools_calls_tool_generator() -> None:
    gen = MagicMock()
    gen.generate_tool_cases.return_value = ["t1"]
    out = grow_cases_for_surface(gen, MagicMock(), "tools")
    gen.generate_tool_cases.assert_called_once()
    assert out == ["t1"]


def test_dispatch_safety_calls_safety_generator() -> None:
    gen = MagicMock()
    gen.generate_safety_cases.return_value = ["s1"]
    out = grow_cases_for_surface(gen, MagicMock(), "safety")
    gen.generate_safety_cases.assert_called_once()
    assert out == ["s1"]


def test_dispatch_edge_cases_calls_edge_generator() -> None:
    gen = MagicMock()
    gen.generate_edge_cases.return_value = ["e1"]
    out = grow_cases_for_surface(gen, MagicMock(), "edge_cases")
    gen.generate_edge_cases.assert_called_once()
    assert out == ["e1"]


def test_dispatch_sub_agents_calls_sub_agent_generator() -> None:
    gen = MagicMock()
    gen.generate_sub_agent_cases.return_value = ["sa1"]
    out = grow_cases_for_surface(gen, MagicMock(), "sub_agents")
    gen.generate_sub_agent_cases.assert_called_once()
    assert out == ["sa1"]


def test_dispatch_unknown_surface_returns_empty() -> None:
    gen = MagicMock()
    out = grow_cases_for_surface(gen, MagicMock(), "asdfjkl")
    assert out == []
