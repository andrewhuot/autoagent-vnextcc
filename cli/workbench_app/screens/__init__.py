"""Full-screen takeovers for the workbench app (T08b).

Mirrors Claude Code's screen/dialog pattern from ``src/screens/`` in the
reference repo. A :class:`Screen` pauses the transcript, owns its own key
bindings until the user exits, and returns a :class:`ScreenResult` that the
caller surfaces back through the ``onDone`` protocol.

This module only ships the base class plus three scaffolds
(:class:`DoctorScreen`, :class:`ResumeScreen`, :class:`SkillsScreen`). The
full interactive behavior lands in T13 (skills) and T17 (resume); the doctor
screen is a thin invocation wrapper that already works end-to-end.
"""

from __future__ import annotations

from cli.workbench_app.screens.base import (
    ACTION_CANCEL,
    ACTION_EXIT,
    KeyProvider,
    Screen,
    ScreenResult,
    iter_keys,
)
from cli.workbench_app.screens.doctor import DoctorScreen
from cli.workbench_app.screens.resume import ResumeScreen
from cli.workbench_app.screens.skills import (
    SKILLS_ACTIONS,
    SkillItem,
    SkillsScreen,
)


__all__ = [
    "ACTION_CANCEL",
    "ACTION_EXIT",
    "DoctorScreen",
    "KeyProvider",
    "ResumeScreen",
    "SKILLS_ACTIONS",
    "Screen",
    "ScreenResult",
    "SkillItem",
    "SkillsScreen",
    "iter_keys",
]
