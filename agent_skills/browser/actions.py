"""Browser action primitives — steps, executor, and result types."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class BrowserAction(str, Enum):
    """Atomic browser actions available to an agent."""

    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE = "type"
    SCROLL = "scroll"
    EXTRACT = "extract"
    SCREENSHOT = "screenshot"
    WAIT = "wait"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class BrowserActionStep:
    """A single step in a browser interaction sequence."""

    action: BrowserAction
    target: str = ""
    value: str = ""
    timeout_ms: int = 5000
    screenshot_before: bool = False
    screenshot_after: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "target": self.target,
            "value": self.value,
            "timeout_ms": self.timeout_ms,
            "screenshot_before": self.screenshot_before,
            "screenshot_after": self.screenshot_after,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BrowserActionStep":
        return cls(
            action=BrowserAction(data["action"]),
            target=data.get("target", ""),
            value=data.get("value", ""),
            timeout_ms=data.get("timeout_ms", 5000),
            screenshot_before=data.get("screenshot_before", False),
            screenshot_after=data.get("screenshot_after", False),
        )


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

class BrowserActionExecutor:
    """Execute BrowserActionSteps, returning structured result dicts.

    This implementation is a stub: it simulates browser interactions without
    requiring a live browser.  In production, replace ``_simulate_action``
    with calls to Playwright, Selenium, or a Cloud Computer-Use API.
    """

    def execute(self, step: BrowserActionStep) -> dict[str, Any]:
        """Execute a single *step* and return a result dict.

        Result keys: ``action``, ``target``, ``success``, ``output``,
        ``duration_ms``, ``timestamp``, ``screenshots``.
        """
        start = time.monotonic()
        screenshots: list[str] = []
        output, success = self._simulate_action(step)
        duration_ms = int((time.monotonic() - start) * 1000)

        if step.screenshot_before:
            screenshots.append(f"<screenshot_before:{step.action.value}:{step.target}>")
        if step.screenshot_after:
            screenshots.append(f"<screenshot_after:{step.action.value}:{step.target}>")

        return {
            "action": step.action.value,
            "target": step.target,
            "value": step.value,
            "success": success,
            "output": output,
            "duration_ms": duration_ms,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "screenshots": screenshots,
        }

    def execute_sequence(self, steps: list[BrowserActionStep]) -> list[dict[str, Any]]:
        """Execute *steps* sequentially, stopping on the first failure."""
        results: list[dict[str, Any]] = []
        for step in steps:
            result = self.execute(step)
            results.append(result)
            if not result["success"]:
                break
        return results

    # ------------------------------------------------------------------
    # Simulation stub
    # ------------------------------------------------------------------

    def _simulate_action(self, step: BrowserActionStep) -> tuple[str, bool]:
        """Return (output, success) for a simulated browser action."""
        action = step.action
        if action == BrowserAction.NAVIGATE:
            return f"Navigated to {step.target or step.value}", True
        if action == BrowserAction.CLICK:
            return f"Clicked element '{step.target}'", True
        if action == BrowserAction.TYPE:
            return f"Typed '{step.value}' into '{step.target}'", True
        if action == BrowserAction.SCROLL:
            return f"Scrolled '{step.target}' by {step.value or '300px'}", True
        if action == BrowserAction.EXTRACT:
            return f"<extracted_content from='{step.target}'>", True
        if action == BrowserAction.SCREENSHOT:
            return f"<screenshot path='{step.target or 'screenshot.png'}'>", True
        if action == BrowserAction.WAIT:
            wait_ms = int(step.value) if step.value.isdigit() else step.timeout_ms
            return f"Waited {wait_ms}ms", True
        return "Unknown action", False
