"""Unit tests for provider key validation (R1.10)."""
from __future__ import annotations

from cli.provider_keys import KeyValidation, normalize_key, validate_provider_key


def test_empty_key_rejected():
    assert not validate_provider_key("OPENAI_API_KEY", "").ok
    assert not validate_provider_key("OPENAI_API_KEY", "   ").ok
    assert not validate_provider_key("OPENAI_API_KEY", None).ok  # type: ignore[arg-type]


def test_short_key_rejected():
    result = validate_provider_key("OPENAI_API_KEY", "sk-short")
    assert not result.ok
    assert "short" in result.message.lower()


def test_key_with_whitespace_rejected():
    result = validate_provider_key("OPENAI_API_KEY", "sk-12345678901234567890 abc")
    assert not result.ok
    assert "whitespace" in result.message.lower()


def test_valid_openai_key_accepted():
    key = "sk-" + "a" * 40
    result = validate_provider_key("OPENAI_API_KEY", key)
    assert result.ok, result.message


def test_valid_anthropic_key_accepted():
    key = "sk-ant-" + "b" * 40
    result = validate_provider_key("ANTHROPIC_API_KEY", key)
    assert result.ok, result.message


def test_valid_google_key_accepted():
    key = "AIzaSy" + "x" * 35
    result = validate_provider_key("GOOGLE_API_KEY", key)
    assert result.ok, result.message


def test_anthropic_key_in_openai_slot_rejected():
    key = "sk-ant-" + "a" * 40
    result = validate_provider_key("OPENAI_API_KEY", key)
    assert not result.ok
    assert "anthropic" in result.message.lower()


def test_openai_key_in_anthropic_slot_rejected():
    key = "sk-" + "a" * 40  # no sk-ant prefix
    result = validate_provider_key("ANTHROPIC_API_KEY", key)
    assert not result.ok
    assert "openai" in result.message.lower()


def test_openai_style_key_in_google_slot_rejected():
    key = "sk-" + "a" * 40
    result = validate_provider_key("GOOGLE_API_KEY", key)
    assert not result.ok


def test_normalize_key_strips_whitespace():
    assert normalize_key("  sk-abc  ") == "sk-abc"
    assert normalize_key("") == ""
    assert normalize_key(None) == ""  # type: ignore[arg-type]
