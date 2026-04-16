"""Skills browser screen for the TUI workbench.

Port of ``cli.workbench_app.screens.skills.SkillsScreen`` — displays
available skills with selection.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.widgets import OptionList, Static

from cli.workbench_app.screens.base import ACTION_EXIT, ScreenResult
from cli.workbench_app.tui.screens.base import TUIScreen


class SkillsScreen(TUIScreen):
    """Full-screen skill browser.

    Displays available agent skills as a selectable list. Press enter
    to select a skill, or ``q``/``Esc`` to close.
    """

    screen_title = "/skills — Agent Skills"

    def __init__(
        self,
        workspace: Any | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._workspace = workspace

    def screen_content(self) -> ComposeResult:
        skills = self._load_skills()
        if not skills:
            yield Static("[dim]No skills available[/]")
            yield Static("")
            yield Static("Skills extend agent capabilities with specialized behaviors.")
            yield Static("Use [bold]agentlab skills install[/] to add skills.")
            return

        yield Static(f"[bold]{len(skills)} skill(s) available:[/]")
        yield Static("")

        option_list = OptionList(id="skills-list")
        for skill in skills:
            name = skill.get("name", "?")
            description = skill.get("description", "")
            display = f"[bold]{name}[/]"
            if description:
                display += f"  [dim]{description}[/]"
            option_list.add_option(display)
        yield option_list

    def hint_text(self) -> str:
        return "Use arrows to browse, [Enter] to select, [q]/[Esc] to close"

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        skills = self._load_skills()
        if event.option_index < len(skills):
            skill = skills[event.option_index]
            self.dismiss(ScreenResult(
                action="show",
                value=skill.get("name"),
                meta_messages=(f"Selected skill: {skill.get('name')}",),
            ))

    def _load_skills(self) -> list[dict[str, Any]]:
        if self._workspace is None:
            return []
        try:
            from cli.skills import list_workspace_skills
            return list_workspace_skills(self._workspace)
        except Exception:
            return []
