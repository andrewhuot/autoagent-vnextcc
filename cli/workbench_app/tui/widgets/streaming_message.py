"""Progressive streaming message widget for in-progress LLM output."""

from __future__ import annotations

from typing import Callable

from textual.widget import Widget
from textual.widgets import Markdown

from cli.workbench_app.store import AppState, Store


class StreamingMessage(Widget):
    """Renders in-progress LLM output with progressive markdown.

    Subscribes to ``state.streaming_content`` and updates the Markdown
    widget as tokens arrive. Automatically removes itself when streaming
    ends (content becomes ``None``).
    """

    DEFAULT_CSS = """
    StreamingMessage {
        height: auto;
        padding: 0 1;
    }

    StreamingMessage Markdown {
        margin: 0;
        padding: 0;
    }
    """

    def __init__(self, store: Store[AppState], **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._store = store
        self._unsub: Callable[[], None] = lambda: None
        self._markdown: Markdown | None = None
        self._last_content: str | None = None

    def compose(self):
        self._markdown = Markdown("")
        yield self._markdown

    def on_mount(self) -> None:
        self._sync()
        self._unsub = self._store.subscribe(self._on_store_changed)

    def on_unmount(self) -> None:
        self._unsub()

    def _on_store_changed(self) -> None:
        try:
            self.app.call_from_thread(self._sync)
        except RuntimeError:
            try:
                self.call_later(self._sync)
            except Exception:
                pass
        except AttributeError:
            pass

    def _sync(self) -> None:
        content = self._store.get_state().streaming_content
        if content == self._last_content:
            return
        self._last_content = content

        if content and self._markdown is not None:
            self._markdown.update(content)
            self.display = True
        else:
            if self._markdown is not None:
                self._markdown.update("")
            self.display = False
