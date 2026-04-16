"""Persist Agent Cards to disk and track version history.

The Agent Card lives at `.agentlab/agent_card.md` as the canonical,
human-readable representation of the agent. Historical versions are
stored in `.agentlab/card_history/` for diffing and rollback.
"""

from __future__ import annotations

import hashlib
import shutil
import time
from pathlib import Path
from typing import Any

from .converter import from_adk_tree, from_canonical_agent, from_config_dict
from .renderer import parse_from_markdown, render_to_markdown
from .schema import AgentCardModel

# Default paths relative to workspace root
CARD_DIR = ".agentlab"
CARD_FILENAME = "agent_card.md"
HISTORY_DIR = "card_history"


def default_card_path(workspace: str | Path = ".") -> Path:
    """Return the default Agent Card path for a workspace."""
    return Path(workspace) / CARD_DIR / CARD_FILENAME


def card_exists(workspace: str | Path = ".") -> bool:
    """Check if an Agent Card exists in the workspace."""
    return default_card_path(workspace).is_file()


def save_card(
    card: AgentCardModel,
    workspace: str | Path = ".",
    *,
    save_history: bool = True,
    reason: str = "",
) -> Path:
    """Save an Agent Card to disk.

    Args:
        card: The card to save.
        workspace: Workspace root directory.
        save_history: If True, also save a timestamped copy in card_history/.
        reason: Optional reason string stored in the history filename.

    Returns:
        Path to the saved card file.
    """
    ws = Path(workspace)
    card_dir = ws / CARD_DIR
    card_dir.mkdir(parents=True, exist_ok=True)

    card_path = card_dir / CARD_FILENAME
    markdown = render_to_markdown(card)
    card_path.write_text(markdown, encoding="utf-8")

    if save_history:
        _save_history_snapshot(card_dir, markdown, reason)

    return card_path


def load_card(workspace: str | Path = ".") -> AgentCardModel:
    """Load the Agent Card from disk.

    Raises:
        FileNotFoundError: If no card exists.
    """
    path = default_card_path(workspace)
    if not path.is_file():
        raise FileNotFoundError(
            f"No Agent Card found at {path}. "
            "Run 'agentlab card generate' or 'agentlab init' to create one."
        )
    text = path.read_text(encoding="utf-8")
    return parse_from_markdown(text)


def load_card_markdown(workspace: str | Path = ".") -> str:
    """Load raw Agent Card markdown from disk.

    Raises:
        FileNotFoundError: If no card exists.
    """
    path = default_card_path(workspace)
    if not path.is_file():
        raise FileNotFoundError(f"No Agent Card found at {path}.")
    return path.read_text(encoding="utf-8")


def generate_and_save_from_config(
    config: dict[str, Any],
    name: str = "",
    workspace: str | Path = ".",
    reason: str = "generated from config",
) -> AgentCardModel:
    """Generate an Agent Card from a config dict and save it."""
    card = from_config_dict(config, name=name)
    save_card(card, workspace=workspace, reason=reason)
    return card


def generate_and_save_from_adk(
    adk_tree: Any,
    workspace: str | Path = ".",
    reason: str = "imported from ADK",
) -> AgentCardModel:
    """Generate an Agent Card from an ADK agent tree and save it."""
    card = from_adk_tree(adk_tree)
    save_card(card, workspace=workspace, reason=reason)
    return card


def list_history(workspace: str | Path = ".") -> list[dict[str, Any]]:
    """List all saved Agent Card versions.

    Returns:
        List of dicts with 'filename', 'timestamp', 'reason', 'hash' keys,
        sorted newest first.
    """
    history_dir = Path(workspace) / CARD_DIR / HISTORY_DIR
    if not history_dir.is_dir():
        return []

    entries: list[dict[str, Any]] = []
    for path in sorted(history_dir.glob("*.md"), reverse=True):
        parts = path.stem.split("_", 2)  # timestamp_hash[_reason]
        ts = float(parts[0]) if parts and parts[0].replace(".", "").isdigit() else 0
        content_hash = parts[1] if len(parts) > 1 else ""
        reason = parts[2].replace("-", " ") if len(parts) > 2 else ""
        entries.append({
            "filename": path.name,
            "path": str(path),
            "timestamp": ts,
            "hash": content_hash,
            "reason": reason,
        })

    return entries


def load_history_version(
    filename: str,
    workspace: str | Path = ".",
) -> AgentCardModel:
    """Load a specific historical version of the Agent Card."""
    path = Path(workspace) / CARD_DIR / HISTORY_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"History version not found: {path}")
    text = path.read_text(encoding="utf-8")
    return parse_from_markdown(text)


def diff_with_version(
    workspace: str | Path = ".",
    version_filename: str | None = None,
) -> str:
    """Produce a unified diff between current card and a historical version.

    If version_filename is None, diffs against the most recent history entry.
    """
    import difflib

    current_path = default_card_path(workspace)
    if not current_path.is_file():
        return "No current Agent Card found."

    current_text = current_path.read_text(encoding="utf-8")

    if version_filename is None:
        history = list_history(workspace)
        if len(history) < 2:
            return "No previous version to diff against."
        # Current is history[0], previous is history[1]
        version_filename = history[1]["filename"]

    old_path = Path(workspace) / CARD_DIR / HISTORY_DIR / version_filename
    if not old_path.is_file():
        return f"Version not found: {version_filename}"

    old_text = old_path.read_text(encoding="utf-8")

    diff_lines = difflib.unified_diff(
        old_text.splitlines(keepends=True),
        current_text.splitlines(keepends=True),
        fromfile=f"previous ({version_filename})",
        tofile="current (agent_card.md)",
        lineterm="",
    )
    result = "\n".join(diff_lines)
    return result if result else "No changes."


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _save_history_snapshot(card_dir: Path, markdown: str, reason: str) -> Path:
    """Save a timestamped snapshot to card_history/."""
    history_dir = card_dir / HISTORY_DIR
    history_dir.mkdir(parents=True, exist_ok=True)

    ts = f"{time.time():.6f}"
    content_hash = hashlib.sha256(markdown.encode()).hexdigest()[:8]
    safe_reason = reason.replace(" ", "-").replace("/", "-")[:40] if reason else ""
    parts = [ts, content_hash]
    if safe_reason:
        parts.append(safe_reason)
    filename = "_".join(parts) + ".md"

    snapshot_path = history_dir / filename
    snapshot_path.write_text(markdown, encoding="utf-8")
    return snapshot_path
