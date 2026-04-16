"""Shared helpers for in-process command execution (R4).

:func:`make_event_writer` re-parses a stream-json line back into a dict
so :class:`cli.progress.ProgressRenderer` can emit events to an
``on_event`` callback without any modification to the renderer itself.

Originally introduced as ``_make_event_writer`` in ``cli/commands/eval.py``
during R4.2 (commit 702da83). Duplicated in ``cli/commands/optimize.py``
during R4.4. Consolidated here in R4.5 so improve + future extractions
share a single copy.
"""
from __future__ import annotations

import json
from typing import Any, Callable


def make_event_writer(
    on_event: Callable[[dict[str, Any]], None],
) -> Callable[[str], None]:
    """Return a ``writer`` callable suitable for :class:`ProgressRenderer`.

    ``ProgressRenderer(output_format="stream-json", writer=...)`` serialises
    each event to JSON and hands the resulting line to ``writer``. We parse
    it back into a dict so in-process callers receive structured events
    without having to re-parse. Non-JSON lines are silently dropped to match
    the pre-R4.5 behaviour of the per-command ``_make_event_writer`` copies.
    """

    def _writer(line: str) -> None:
        try:
            event = json.loads(line)
        except (TypeError, ValueError):
            return
        if isinstance(event, dict):
            on_event(event)

    return _writer


__all__ = ["make_event_writer"]
