"""Clipboard image capture and resize helpers."""

from __future__ import annotations

import io
import logging
import os
import shutil
import subprocess
import sys
from typing import Any


logger = logging.getLogger(__name__)
_VISION_EDGE_LIMIT = 1568


def _load_imagegrab() -> Any:
    from PIL import ImageGrab

    return ImageGrab


def _load_image_module() -> Any:
    from PIL import Image

    return Image


def _resample_lanczos() -> Any | None:
    try:
        image_module = _load_image_module()
    except ImportError:
        return None
    resampling = getattr(image_module, "Resampling", None)
    if resampling is not None:
        return resampling.LANCZOS
    return getattr(image_module, "LANCZOS", None)


def render_image_placeholder(display_number: int) -> str:
    """Render the compact placeholder shown for a pasted image."""
    return f"[Image #{display_number}]"


def capture_clipboard_image() -> Any | None:
    """Best-effort clipboard image capture across supported platforms."""
    if sys.platform in {"darwin", "win32"}:
        try:
            image_grab = _load_imagegrab()
        except ImportError:
            logger.info("Pillow not installed; clipboard image capture disabled")
            return None
        return image_grab.grabclipboard()

    if sys.platform.startswith("linux"):
        try:
            image_module = _load_image_module()
        except ImportError:
            logger.info("Pillow not installed; clipboard image capture disabled")
            return None

        session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
        if session_type == "wayland":
            command = ["wl-paste", "--type", "image/png"]
        else:
            command = ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"]

        if shutil.which(command[0]) is None:
            logger.info("Clipboard image helper %s is unavailable", command[0])
            return None

        try:
            result = subprocess.run(
                command,
                check=True,
                capture_output=True,
            )
        except (OSError, subprocess.CalledProcessError):
            logger.info("Clipboard image capture failed", exc_info=True)
            return None

        return image_module.open(io.BytesIO(result.stdout))

    return None


def resize_for_vision(image: Any) -> bytes:
    """Resize an image so its longest edge fits the shared vision budget."""
    width, height = image.size
    longest_edge = max(width, height)
    if longest_edge > _VISION_EDGE_LIMIT:
        scale = _VISION_EDGE_LIMIT / float(longest_edge)
        resized = image.resize(
            (max(1, round(width * scale)), max(1, round(height * scale))),
            _resample_lanczos(),
        )
    else:
        resized = image

    buffer = io.BytesIO()
    resized.save(buffer, format="PNG")
    return buffer.getvalue()


__all__ = [
    "capture_clipboard_image",
    "render_image_placeholder",
    "resize_for_vision",
]
