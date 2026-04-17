from __future__ import annotations

import pytest

from cli.workbench_app import output_style


@pytest.fixture(autouse=True)
def _reset_output_style() -> None:
    output_style.reset_style()
    yield
    output_style.reset_style()


def test_parse_style_directive_strips_valid_leading_tag() -> None:
    text, style = output_style.parse_style_directive(
        '<agentlab output-style="table">| a |\\n| --- |'
    )
    assert text == "| a |\\n| --- |"
    assert style == "table"


def test_parse_style_directive_rejects_invalid_tag_shapes() -> None:
    invalid_text = '<agentlab output-style="rainbow">hello'
    text, style = output_style.parse_style_directive(invalid_text)
    assert text == invalid_text
    assert style is None

    misplaced = 'prefix <agentlab output-style="table">hello'
    text, style = output_style.parse_style_directive(misplaced)
    assert text == misplaced
    assert style is None


def test_parse_style_directive_requires_double_quoted_style_value() -> None:
    invalid_text = "<agentlab output-style=table>hello"
    text, style = output_style.parse_style_directive(invalid_text)
    assert text == invalid_text
    assert style is None


def test_parse_style_directive_returns_original_text_when_no_tag_exists() -> None:
    text, style = output_style.parse_style_directive("plain response")
    assert text == "plain response"
    assert style is None


def test_apply_style_terse_compacts_whitespace() -> None:
    styled = output_style.apply_style("alpha   beta\n\n\n gamma", "terse")
    assert styled == "alpha beta\n\ngamma"


def test_apply_style_table_passes_through_valid_markdown_table() -> None:
    table = "| name | value |\n| --- | --- |\n| a | 1 |"
    assert output_style.apply_style(table, "table") == table


def test_apply_style_table_falls_back_for_non_table_text() -> None:
    text = "not actually a markdown table"
    assert output_style.apply_style(text, "table") == text


def test_markdown_table_validator_accepts_real_table() -> None:
    table = "| name | value |\n| --- | --- |\n| a | 1 |"
    assert output_style._looks_like_markdown_table(table) is True


def test_markdown_table_validator_rejects_non_table_text() -> None:
    assert output_style._looks_like_markdown_table("just a paragraph") is False


def test_markdown_table_validator_rejects_column_mismatch() -> None:
    text = "| name | value |\n| --- |\n| a | 1 |"
    assert output_style._looks_like_markdown_table(text) is False


def test_apply_style_json_wraps_valid_json_in_fence() -> None:
    text = '{"ok": true}'
    assert output_style.apply_style(text, "json") == '```json\n{"ok": true}\n```'


def test_apply_style_json_falls_back_for_invalid_payload() -> None:
    text = "{not-json}"
    assert output_style.apply_style(text, "json") == text


@pytest.mark.parametrize("style_name", ["markdown", "default", "unknown"])
def test_apply_style_passthrough_styles_return_original_text(style_name: str) -> None:
    text = "leave me alone"
    assert output_style.apply_style(text, style_name) == text
