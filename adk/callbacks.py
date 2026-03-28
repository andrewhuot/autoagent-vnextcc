"""ADK callback registry and enforcement hooks."""
from __future__ import annotations

from enum import Enum
from typing import Any, Callable


class CallbackType(str, Enum):
    """Lifecycle points at which callbacks can be registered."""

    BEFORE_AGENT = "before_agent"
    AFTER_AGENT = "after_agent"
    BEFORE_MODEL = "before_model"
    AFTER_MODEL = "after_model"
    BEFORE_TOOL = "before_tool"
    AFTER_TOOL = "after_tool"


class CallbackRegistry:
    """Registry for ADK lifecycle callbacks.

    Callbacks are keyed by (CallbackType, name) and executed in registration
    order. Each handler receives a context dict and must return a (possibly
    modified) context dict.

    Example::

        registry = CallbackRegistry()

        def log_before(ctx):
            print("before agent:", ctx)
            return ctx

        registry.register(CallbackType.BEFORE_AGENT, "logger", log_before)
        result_ctx = registry.execute_callbacks(CallbackType.BEFORE_AGENT, {})
    """

    def __init__(self) -> None:
        # Maps (CallbackType, name) -> handler
        self._handlers: dict[tuple[CallbackType, str], Callable[[dict], dict]] = {}
        # Maintain insertion order per type so execution is deterministic.
        self._order: dict[CallbackType, list[str]] = {t: [] for t in CallbackType}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        callback_type: CallbackType,
        name: str,
        handler: Callable[[dict], dict],
    ) -> None:
        """Register a callback handler.

        Re-registering the same (callback_type, name) pair replaces the
        existing handler but preserves the original registration order.

        Args:
            callback_type: Lifecycle point for the callback.
            name: Unique name for this callback within its type.
            handler: Callable that accepts a context dict and returns a context
                dict (possibly modified). Must not raise except for hard
                permission failures.
        """
        key = (callback_type, name)
        if name not in self._order[callback_type]:
            self._order[callback_type].append(name)
        self._handlers[key] = handler

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get(self, callback_type: CallbackType, name: str) -> Callable[[dict], dict] | None:
        """Return the handler for the given (callback_type, name) pair, or None.

        Args:
            callback_type: Lifecycle point.
            name: Handler name.

        Returns:
            The registered callable, or ``None`` if not found.
        """
        return self._handlers.get((callback_type, name))

    def list_callbacks(
        self,
        callback_type: CallbackType | None = None,
    ) -> list[dict]:
        """List registered callbacks, optionally filtered by type.

        Args:
            callback_type: When provided, only callbacks of this type are
                returned.  When ``None``, all callbacks are returned.

        Returns:
            List of dicts with keys ``callback_type``, ``name``.
        """
        result: list[dict] = []
        types = [callback_type] if callback_type is not None else list(CallbackType)
        for ctype in types:
            for name in self._order[ctype]:
                if (ctype, name) in self._handlers:
                    result.append({"callback_type": ctype.value, "name": name})
        return result

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute_callbacks(
        self,
        callback_type: CallbackType,
        context: dict,
    ) -> dict:
        """Execute all registered callbacks of *callback_type* in order.

        Each callback receives the context returned by the previous one, so
        handlers can modify shared state as needed.  If a handler raises an
        exception it is caught and stored in ``context["_errors"]`` before
        moving to the next handler.

        Args:
            callback_type: The lifecycle point whose callbacks should run.
            context: Initial context dict. Passed through all handlers.

        Returns:
            The final context dict after all handlers have run.
        """
        current_context = dict(context)
        for name in self._order.get(callback_type, []):
            handler = self._handlers.get((callback_type, name))
            if handler is None:
                continue
            try:
                result = handler(current_context)
                if isinstance(result, dict):
                    current_context = result
            except Exception as exc:  # noqa: BLE001
                errors = current_context.setdefault("_errors", [])
                errors.append(
                    {"callback": name, "type": callback_type.value, "error": str(exc)}
                )
        return current_context


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def make_permission_callback(permission_engine: Any) -> Callable[[dict], dict]:
    """Create a ``BEFORE_AGENT`` callback that enforces permissions.

    The returned callback calls ``permission_engine.check(context)`` before
    allowing the agent to proceed.  The permission engine must expose a
    ``check(context: dict) -> bool`` method.  When access is denied the
    callback raises a ``PermissionError`` so that the runtime can abort the
    request cleanly.

    Args:
        permission_engine: An object with a ``check(context: dict) -> bool``
            method.

    Returns:
        A callback function compatible with ``CallbackRegistry.register``.

    Example::

        class SimpleEngine:
            def check(self, ctx):
                return ctx.get("user_id") == "admin"

        cb = make_permission_callback(SimpleEngine())
        registry.register(CallbackType.BEFORE_AGENT, "permissions", cb)
    """

    def _permission_callback(context: dict) -> dict:
        allowed = permission_engine.check(context)
        if not allowed:
            raise PermissionError(
                f"Permission denied for user={context.get('user_id', '<unknown>')}"
            )
        return context

    return _permission_callback
