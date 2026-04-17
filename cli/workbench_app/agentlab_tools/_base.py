"""Base class for AgentLab in-process command tools.

This module defines :class:`AgentLabTool`, an abstract :class:`cli.tools.base.Tool`
subclass that wraps any ``run_*_in_process`` callable (eval, deploy, improve_*)
with the boilerplate the LLM tool-use loop needs:

* Auto-injection of ``on_event`` and ``text_writer`` keyword arguments — the
  model never sees these plumbing parameters; the base layer supplies a no-op
  callback and ``None`` writer.
* Silent stripping of unknown keys before invoking the wrapped function so a
  schema/signature drift surfaces as a tool failure (or a missing required
  arg) rather than a ``TypeError``.
* Translation of any raised exception into ``ToolResult.failure(...)``.
  The orchestrator does not crash on a domain failure (e.g. ``MockFallbackError``);
  the model receives the failure as content and can react.
* Default :meth:`Tool.permission_action` of ``f"tool:{name}"`` so
  ``settings.json`` rules can target each AgentLab tool individually.
* A default :meth:`_shape_result` that turns frozen dataclasses into JSON-safe
  ``dict``\\ s via :func:`dataclasses.asdict` and recursively coerces tuples,
  lists, sets and frozensets to ``list``.

Subclasses must declare ``name``, ``description``, ``input_schema`` (as
class attributes) and implement :meth:`_in_process_fn` returning the wrapped
callable. They may override :meth:`_shape_result` for custom shaping.
"""

from __future__ import annotations

import dataclasses
import inspect
from abc import abstractmethod
from typing import Any, Callable, Mapping

from cli.tools.base import Tool, ToolContext, ToolResult


def _to_jsonsafe(value: Any) -> Any:
    """Recursively coerce ``value`` into a JSON-safe shape.

    * ``dict`` — recurse into values, preserve keys.
    * ``list`` / ``tuple`` / ``set`` / ``frozenset`` — coerce to ``list``
      and recurse into elements.
    * Any other scalar (``int``, ``float``, ``str``, ``bool``, ``None``,
      arbitrary objects) — pass through unchanged. Callers that need
      stricter coercion should override :meth:`AgentLabTool._shape_result`.
    """

    if isinstance(value, dict):
        return {k: _to_jsonsafe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_to_jsonsafe(v) for v in value]
    return value


class AgentLabTool(Tool):
    """Wraps one ``run_*_in_process`` function as an LLM-callable tool.

    Subclasses must set ``name`` / ``description`` / ``input_schema`` and
    implement :meth:`_in_process_fn` (returning the function). They may
    override :meth:`_shape_result` to customise how the typed dataclass
    return is rendered for the model.
    """

    # Subclasses opt in to ``read_only=True`` for pure-inspection tools
    # (improve_list / improve_show / improve_diff). The default is ``False``
    # because eval / deploy / improve_run / improve_accept all mutate state
    # or cost tokens.
    read_only: bool = False

    @abstractmethod
    def _in_process_fn(self) -> Callable[..., Any]:
        """Return the ``run_*_in_process`` callable to dispatch."""

    def _shape_result(self, result: Any) -> Any:
        """Translate the wrapped function's return value into JSON-safe content.

        Default behaviour:

        * If ``result`` is a dataclass instance, convert via
          :func:`dataclasses.asdict` and run through :func:`_to_jsonsafe`.
        * Otherwise, run through :func:`_to_jsonsafe` directly so plain
          ``dict``\\ s pass through and tuples / sets become lists.

        Subclasses override for richer shaping (e.g. summarising a long
        ``warnings`` tuple or surfacing only the top-level fields).
        """

        if dataclasses.is_dataclass(result) and not isinstance(result, type):
            return _to_jsonsafe(dataclasses.asdict(result))
        return _to_jsonsafe(result)

    def run(self, tool_input: Mapping[str, Any], context: ToolContext) -> ToolResult:
        """Invoke the wrapped function and translate the result for the LLM.

        ``context`` is unused at the base layer — subclasses that need the
        workspace root or cancellation token should override this method.
        """

        fn = self._in_process_fn()
        sig = inspect.signature(fn)
        params = sig.parameters

        # Strip unknown args silently. Schema drift surfaces either as a
        # missing-required-arg ``TypeError`` (caught below) or as the model
        # noticing the response doesn't reflect its requested arg.
        accepted: dict[str, Any] = {k: v for k, v in tool_input.items() if k in params}

        # Auto-inject the plumbing kwargs the model never sees. Only inject
        # when the wrapped fn actually accepts them AND the caller didn't
        # already supply a value (defensive: realistic callers are LLMs
        # which won't send these, but tests and future internal callers
        # might).
        if "on_event" in params and "on_event" not in accepted:
            accepted["on_event"] = lambda _event: None
        if "text_writer" in params and "text_writer" not in accepted:
            accepted["text_writer"] = None

        try:
            raw = fn(**accepted)
        except Exception as exc:  # noqa: BLE001 — domain failures must surface
            # Domain failures (MockFallbackError, ImproveCommandError, etc.)
            # become ToolResult.failure so the orchestrator stays interactive
            # and the model can react. Programmer errors (AttributeError on
            # internal misuse) also surface this way; the alternative —
            # propagating — would crash the REPL mid-conversation.
            message = f"{type(exc).__name__}: {exc}"
            return ToolResult.failure(message, error_type=type(exc).__name__)

        shaped = self._shape_result(raw)
        return ToolResult.success(shaped, raw_type=type(raw).__name__)
