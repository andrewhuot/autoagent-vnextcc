"""Shared CLI selector semantics for resource commands."""

from __future__ import annotations

from typing import Any


PRIMARY_SELECTORS: tuple[str, ...] = ("latest", "active", "pending")
SELECTOR_ALIASES: dict[str, str] = {"current": "active"}
ALL_SELECTORS = set(PRIMARY_SELECTORS) | set(SELECTOR_ALIASES)


def normalize_selector(value: str) -> tuple[str, str | None]:
    """Normalize selector aliases to their canonical selector names."""
    normalized = value.strip().lower()
    if normalized in SELECTOR_ALIASES:
        return SELECTOR_ALIASES[normalized], normalized
    return normalized, None


def is_selector(value: str) -> bool:
    """Return whether a token is one of the supported selector keywords."""
    normalized, _ = normalize_selector(value)
    return normalized in PRIMARY_SELECTORS


def resolve_selector(selector: str, items: list[dict[str, Any]], status_key: str = "status") -> dict[str, Any] | None:
    """Resolve a standard selector against a newest-first list of items."""
    if not items:
        return None

    normalized, _ = normalize_selector(selector)
    if normalized == "latest":
        return items[0]
    if normalized == "active":
        for item in items:
            if item.get(status_key) in ("active", "current", "applied", "promoted"):
                return item
        return items[0]
    if normalized == "pending":
        for item in items:
            if item.get(status_key) in ("pending", "candidate", "imported", "canary"):
                return item
        return None
    return None
