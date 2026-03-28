"""Skill package signing and verification using HMAC-SHA256."""

from __future__ import annotations

import hashlib
import hmac


class SkillSigner:
    """Signs and verifies skill content using HMAC-SHA256."""

    @staticmethod
    def sign(skill_content: str, author_key: str) -> str:
        """Return a hex HMAC-SHA256 signature of skill_content using author_key."""
        key_bytes = author_key.encode("utf-8")
        content_bytes = skill_content.encode("utf-8")
        return hmac.new(key_bytes, content_bytes, hashlib.sha256).hexdigest()

    @staticmethod
    def verify(skill_content: str, signature: str, author_key: str) -> bool:
        """Return True if signature matches the expected HMAC for skill_content."""
        expected = SkillSigner.sign(skill_content, author_key)
        return hmac.compare_digest(expected, signature)
