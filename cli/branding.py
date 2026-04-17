"""Branding helpers for the AgentLab CLI."""

from __future__ import annotations

from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version as distribution_version
from pathlib import Path
import tomllib

import click


@lru_cache(maxsize=1)
def get_agentlab_version() -> str:
    """Return the source version locally and installed package metadata elsewhere."""
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    if pyproject_path.exists():
        with pyproject_path.open("rb") as handle:
            project = tomllib.load(handle)
        return str(project["project"]["version"])

    try:
        return distribution_version("agentlab")
    except PackageNotFoundError:
        return "0.0.0"


def banner_enabled(ctx: click.Context | None) -> bool:
    """Resolve banner visibility across parent commands so suppression is inherited."""
    current = ctx
    while current is not None:
        params = current.params if isinstance(current.params, dict) else {}
        if params.get("quiet") or params.get("no_banner"):
            return False
        current = current.parent
    return True


def render_startup_banner(version: str) -> str:
    """Render the compact branded banner used on key startup surfaces."""
    logo_style = {"fg": "blue", "bold": True}
    title_style = {"fg": "white", "bold": True}
    subtitle_style = {"fg": "cyan", "bold": True}

    logo_lines = [
        "  o   o   ",
        "   \\ /    ",
        "    O     ",
        "   / \\    ",
        "  o   o   ",
    ]
    title_lines = [
        "   _                _   _         _",
        "  /_\\  __ _ ___ _ _| |_| |   __ _| |__",
        " / _ \\/ _` / -_) ' \\  _| |__/ _` | '_ \\",
        "/_/ \\_\\__, \\___|_||_\\__|____\\__,_|_.__/",
        "      |___/",
    ]

    lines = [
        click.style(logo_line, **logo_style) + click.style(title_line, **title_style)
        for logo_line, title_line in zip(logo_lines, title_lines, strict=True)
    ]
    lines.append(
        " " * len(logo_lines[0])
        + click.style(f"Experiment. Evaluate. Refine.   v{version}", **subtitle_style)
    )
    # The rounded welcome card below already provides a visual seam — an extra
    # dashed rule under the logo just adds noise before the card opens.
    return "\n".join(lines)


def echo_startup_banner(ctx: click.Context | None) -> None:
    """Print the branded banner only when the active command tree allows it."""
    if banner_enabled(ctx):
        click.echo(render_startup_banner(get_agentlab_version()))
