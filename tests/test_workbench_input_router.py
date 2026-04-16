"""Tests for the Workbench input routing boundary."""

from __future__ import annotations

from cli.workbench_app.input_router import InputKind, route_user_input


def test_routes_blank_input_as_empty() -> None:
    assert route_user_input("").kind is InputKind.EMPTY
    assert route_user_input("   ").kind is InputKind.EMPTY


def test_routes_exit_tokens_before_slash_dispatch() -> None:
    for token in ("exit", "quit", "/exit", "/quit", ":q"):
        route = route_user_input(token)
        assert route.kind is InputKind.EXIT
        assert route.payload == token


def test_routes_question_mark_as_shortcuts() -> None:
    route = route_user_input("?")

    assert route.kind is InputKind.SHORTCUTS
    assert route.payload == "?"


def test_routes_bang_prefixed_input_as_shell() -> None:
    route = route_user_input("! pwd")

    assert route.kind is InputKind.SHELL
    assert route.payload == "! pwd"


def test_routes_ampersand_prefixed_input_as_background_workflow() -> None:
    route = route_user_input("& build something")

    assert route.kind is InputKind.BACKGROUND
    assert route.payload == "build something"


def test_routes_slash_input_as_slash_command() -> None:
    route = route_user_input("/build hello")

    assert route.kind is InputKind.SLASH
    assert route.command_name == "build"
    assert route.payload == "/build hello"


def test_routes_plain_text_as_chat() -> None:
    route = route_user_input("hello")

    assert route.kind is InputKind.CHAT
    assert route.payload == "hello"
    assert route.command_name is None
