"""Provider API key format validation.

Conservative validators: detect clearly-wrong pastes (too short, wrong prefix,
whitespace issues) without hardcoding strict prefix rules that providers
routinely change. Returns (ok: bool, message: str).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KeyValidation:
    ok: bool
    message: str


# Minimum sane length for any production API key; ~20 chars.
_MIN_KEY_LENGTH = 20


def validate_provider_key(env_name: str, raw: str) -> KeyValidation:
    """Validate a pasted provider key. Conservative — reject the obvious junk."""
    if raw is None:
        return KeyValidation(False, "Key is empty.")
    key = raw.strip()
    if not key:
        return KeyValidation(False, "Key is empty.")
    if key != raw:
        # Keep the trimmed version; this is just a tip.
        pass
    if len(key) < _MIN_KEY_LENGTH:
        return KeyValidation(
            False,
            f"Key too short ({len(key)} chars, need ≥{_MIN_KEY_LENGTH}). "
            "Did you paste the full value?",
        )
    if any(ch in key for ch in (" ", "\t", "\n", "\r")):
        return KeyValidation(
            False,
            "Key contains whitespace. Re-paste without copying a leading/trailing "
            "space or newline.",
        )
    # Provider-specific soft checks: warn but still accept if prefix-less;
    # reject if prefix is clearly wrong (e.g. 'sk-ant-' in OPENAI_API_KEY).
    normalized = env_name.upper()
    if normalized == "OPENAI_API_KEY" and key.startswith("sk-ant-"):
        return KeyValidation(
            False,
            "This looks like an Anthropic key (sk-ant-...). Choose Anthropic instead.",
        )
    if normalized == "ANTHROPIC_API_KEY" and key.startswith("sk-") and not key.startswith("sk-ant-"):
        # OpenAI-style; warn but don't hard-fail — user may have custom setup.
        return KeyValidation(
            False,
            "This looks like an OpenAI key (sk-...). Choose OpenAI instead.",
        )
    if normalized == "GOOGLE_API_KEY" and key.startswith("sk-"):
        return KeyValidation(
            False,
            "This looks like an OpenAI/Anthropic key, not a Google key.",
        )
    return KeyValidation(True, "OK")


def normalize_key(raw: str) -> str:
    """Strip whitespace and return the cleaned key."""
    return (raw or "").strip()
