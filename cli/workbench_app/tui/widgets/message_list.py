"""Scrollable message list for the TUI transcript."""

from __future__ import annotations

from typing import Callable

from textual.containers import VerticalScroll
from textual.widgets import Static

from cli.workbench_app.store import AppState, Store, select_messages
from cli.workbench_app.transcript import TranscriptEntry
from cli.workbench_app.tui.widgets.message_widget import MessageWidget


class StreamingIndicator(Static):
    """Displays in-progress streaming content below the message list."""

    DEFAULT_CSS = """
    StreamingIndicator {
        height: auto;
        padding: 0 1;
        color: $text-muted;
    }
    """


class MessageList(VerticalScroll):
    """Scrollable container of :class:`MessageWidget` instances.

    Subscribes to the store's message list. When messages change,
    new ``MessageWidget`` children are appended and the view
    auto-scrolls to the bottom.
    """

    def __init__(
        self,
        store: Store[AppState],
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._store = store
        self._rendered_count = 0
        self._unsub: Callable[[], None] = lambda: None
        self._streaming_widget: StreamingIndicator | None = None

    def on_mount(self) -> None:
        # Render any messages already in state.
        self._sync_messages()
        # Subscribe for future updates.
        self._unsub = self._store.subscribe(self._on_store_changed)

    def on_unmount(self) -> None:
        self._unsub()

    def _on_store_changed(self) -> None:
        """Called by the store on every state change.

        Schedules ``_sync_messages`` on the Textual event loop. Uses
        ``call_from_thread`` for thread safety when called from background
        threads (Phase 3 EventBroker), falling back to ``call_later``
        when called from the same thread (pilot tests, same-thread updates).
        """
        try:
            self.app.call_from_thread(self._sync_messages)
        except RuntimeError:
            # Same-thread call (pilot tests) — fall back to call_later.
            try:
                self.call_later(self._sync_messages)
            except Exception:
                pass
        except AttributeError:
            # Widget not yet mounted or app not available.
            pass

    def _sync_messages(self) -> None:
        state = self._store.get_state()
        messages = select_messages(state)

        # Append only new messages (append-only model).
        new_count = len(messages)
        if new_count > self._rendered_count:
            for entry in messages[self._rendered_count:]:
                widget = MessageWidget(entry)
                self.mount(widget, before=self._streaming_widget)
            self._rendered_count = new_count

        # Update streaming indicator.
        streaming = state.streaming_content
        if streaming:
            if self._streaming_widget is None:
                self._streaming_widget = StreamingIndicator(streaming)
                self.mount(self._streaming_widget)
            else:
                self._streaming_widget.update(streaming)
        elif self._streaming_widget is not None:
            self._streaming_widget.remove()
            self._streaming_widget = None

        # Auto-scroll to bottom.
        self.scroll_end(animate=False)
