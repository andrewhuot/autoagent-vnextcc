from __future__ import annotations

from types import SimpleNamespace

from cli.paste.image import (
    capture_clipboard_image,
    render_image_placeholder,
    resize_for_vision,
)


class _FakeImage:
    def __init__(self, width: int, height: int) -> None:
        self.size = (width, height)
        self.resized_to: tuple[int, int] | None = None

    def resize(self, size: tuple[int, int], resample: object | None = None) -> "_FakeImage":
        image = _FakeImage(*size)
        image.resized_to = size
        return image

    def save(self, buffer, format: str) -> None:  # noqa: A002
        buffer.write(f"{self.size[0]}x{self.size[1]}:{format}".encode("utf-8"))


def test_capture_clipboard_image_returns_none_when_pillow_missing(monkeypatch) -> None:
    import cli.paste.image as image_module

    monkeypatch.setattr(image_module.sys, "platform", "darwin")
    monkeypatch.setattr(
        image_module,
        "_load_imagegrab",
        lambda: (_ for _ in ()).throw(ImportError("missing pillow")),
    )

    assert capture_clipboard_image() is None


def test_resize_for_vision_clamps_longest_edge() -> None:
    image = _FakeImage(2000, 1000)

    output = resize_for_vision(image)

    assert output == b"1568x784:PNG"


def test_render_image_placeholder_uses_display_number() -> None:
    assert render_image_placeholder(3) == "[Image #3]"
