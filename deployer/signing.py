"""Cryptographic signing and verification for release objects.

Uses HMAC-SHA256 over a canonical JSON serialisation of the release's
mutable-free content so that signatures survive round-trips through JSON
storage and are stable regardless of dict insertion order.
"""

from __future__ import annotations

import hashlib
import hmac
import json

from deployer.release_objects import ReleaseObject


class ReleaseSigner:
    """HMAC-SHA256 signer for :class:`~deployer.release_objects.ReleaseObject`.

    The signature covers every field that constitutes the *content* of the
    release — ``signature`` and ``signed_at`` are intentionally excluded so
    that the same object can be re-verified after being stored and loaded.

    Args:
        secret_key: Shared secret used to derive the HMAC.  In production
            this should come from a secrets manager, not source code.
    """

    # Fields excluded from the content hash:
    #   ``signature``, ``signed_at`` — set *by* the signing process itself.
    #   ``status``   — lifecycle field that changes legitimately after signing
    #                  (DRAFT -> SIGNED -> DEPLOYED etc.).
    #   ``metadata`` — operational annotations (e.g. ``deployed_at``) added
    #                  post-signing that must not invalidate the signature.
    _EXCLUDED_FIELDS = frozenset({"signature", "signed_at", "status", "metadata"})

    def __init__(self, secret_key: str = "autoagent-default-key") -> None:
        self._secret = secret_key.encode("utf-8")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sign(self, release: ReleaseObject) -> str:
        """Compute a signature for *release* and return the hex digest.

        The caller is responsible for storing the returned value in
        ``release.signature`` and recording the timestamp in
        ``release.signed_at``.

        Args:
            release: The release object to sign.

        Returns:
            A lowercase hex HMAC-SHA256 digest string.
        """
        content_hash = self._compute_content_hash(release)
        return hmac.new(self._secret, content_hash.encode("utf-8"), hashlib.sha256).hexdigest()

    def verify(self, release: ReleaseObject, signature: str) -> bool:
        """Return True if *signature* matches the recomputed HMAC for *release*.

        Uses :func:`hmac.compare_digest` to prevent timing attacks.

        Args:
            release: The release object whose content is to be verified.
            signature: The previously stored hex-encoded HMAC-SHA256 digest.

        Returns:
            True when the signature is authentic and the release has not
            been tampered with.
        """
        expected = self.sign(release)
        return hmac.compare_digest(expected, signature)

    def _compute_content_hash(self, release: ReleaseObject) -> str:
        """Return a stable SHA-256 hex digest of the release's signable content.

        All fields except ``signature`` and ``signed_at`` are included.
        Keys are sorted so the hash is deterministic regardless of
        insertion order.

        Args:
            release: Source release object.

        Returns:
            Lowercase hex SHA-256 digest string.
        """
        raw = release.to_dict()
        signable = {k: v for k, v in raw.items() if k not in self._EXCLUDED_FIELDS}
        canonical = json.dumps(signable, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()
