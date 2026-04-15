"""Path-safety helper shared by workspace-scoped tools.

All tools that touch the filesystem must route their target paths through
:func:`resolve_within_workspace` so the LLM cannot reach outside the
workspace root via ``..`` segments, symlinks, or absolute paths.

Rejecting unsafe paths at the tool boundary — rather than relying on the
permission prompt — is intentional: a user who auto-approves
``tool:FileRead`` should still not leak ``/etc/passwd``.
"""

from __future__ import annotations

from pathlib import Path


class PathOutsideWorkspace(ValueError):
    """Raised when a requested path resolves outside the workspace root."""


def resolve_within_workspace(raw_path: str, workspace_root: Path) -> Path:
    """Resolve ``raw_path`` against ``workspace_root`` and reject escapes.

    ``raw_path`` may be absolute (must already be inside the root), relative
    (resolved against the root), or use ``~`` (expanded first). Symlinks are
    followed via ``Path.resolve`` so a symlink pointing outside the root is
    rejected too.
    """
    root = workspace_root.resolve()
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PathOutsideWorkspace(
            f"Path '{raw_path}' resolves outside the workspace root '{root}'."
        ) from exc
    return resolved
