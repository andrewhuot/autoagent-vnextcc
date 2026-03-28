"""Scaffold valid ADK project structures.

Generates a minimal but runnable ADK project that can be started with
``adk web`` or ``adk run``.  The generated layout follows the canonical ADK
project structure::

    <project_dir>/
        __init__.py     ← exports ``root_agent``
        agent.py        ← agent definition
        tools.py        ← tool function stubs
        config.json     ← runtime config (model, generation params)
        .env            ← environment variable template

Supported agent types: ``llm``, ``sequential``, ``parallel``, ``loop``.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent


@dataclass
class ScaffoldResult:
    """Result of a scaffold operation.

    Attributes:
        project_dir: Absolute path to the created project directory.
        files_created: List of absolute file paths that were written.
        agent_name: Name used for the root agent.
    """

    project_dir: str
    files_created: list[str] = field(default_factory=list)
    agent_name: str = ""


class AdkScaffolder:
    """Generates a runnable ADK project from a high-level specification.

    Example::

        scaffolder = AdkScaffolder()
        result = scaffolder.scaffold(
            project_dir="/tmp/my_agent",
            agent_name="my_agent",
            agent_type="llm",
            tools=["search", "summarise"],
            model="gemini-2.0-flash",
        )
        print(result.files_created)
    """

    # Valid agent type names and their corresponding ADK class.
    _AGENT_CLASS: dict[str, str] = {
        "llm": "LlmAgent",
        "sequential": "SequentialAgent",
        "parallel": "ParallelAgent",
        "loop": "LoopAgent",
    }

    # ADK import path for each agent class.
    _AGENT_IMPORT: dict[str, str] = {
        "LlmAgent": "google.adk.agents",
        "SequentialAgent": "google.adk.agents",
        "ParallelAgent": "google.adk.agents",
        "LoopAgent": "google.adk.agents",
    }

    def scaffold(
        self,
        project_dir: str,
        agent_name: str,
        agent_type: str = "llm",
        tools: list[str] | None = None,
        sub_agents: list[str] | None = None,
        model: str = "gemini-2.0-flash",
    ) -> ScaffoldResult:
        """Create the ADK project directory and write all scaffold files.

        Args:
            project_dir: Absolute or relative path to the project root.
                Created if it does not exist.
            agent_name: Python identifier used as the agent's name.
            agent_type: One of ``"llm"``, ``"sequential"``, ``"parallel"``,
                ``"loop"``.
            tools: List of tool function names to stub out.
            sub_agents: List of sub-agent names to reference.
            model: LLM model identifier (only used for ``llm`` agents).

        Returns:
            A ``ScaffoldResult`` describing what was created.

        Raises:
            ValueError: If *agent_type* is not recognised.
        """
        if agent_type not in self._AGENT_CLASS:
            raise ValueError(
                f"Unknown agent_type {agent_type!r}. "
                f"Choose from: {sorted(self._AGENT_CLASS)}"
            )

        tool_names: list[str] = list(tools or [])
        sub_agent_names: list[str] = list(sub_agents or [])
        agent_class = self._AGENT_CLASS[agent_type]

        target = Path(project_dir)
        target.mkdir(parents=True, exist_ok=True)

        files_created: list[str] = []

        def _write(filename: str, content: str) -> None:
            path = target / filename
            path.write_text(content, encoding="utf-8")
            files_created.append(str(path.resolve()))

        _write("tools.py", self._generate_tools_py(tool_names))
        _write(
            "agent.py",
            self._generate_agent_py(
                agent_name=agent_name,
                agent_class=agent_class,
                agent_type=agent_type,
                tool_names=tool_names,
                sub_agent_names=sub_agent_names,
                model=model,
            ),
        )
        _write("__init__.py", self._generate_init_py(agent_name))
        _write("config.json", self._generate_config_json(model, agent_name))
        _write(".env", self._generate_env_template())

        return ScaffoldResult(
            project_dir=str(target.resolve()),
            files_created=files_created,
            agent_name=agent_name,
        )

    # ------------------------------------------------------------------
    # File generators
    # ------------------------------------------------------------------

    def _generate_agent_py(
        self,
        agent_name: str,
        agent_class: str,
        agent_type: str,
        tool_names: list[str],
        sub_agent_names: list[str],
        model: str,
    ) -> str:
        """Return the content of ``agent.py``.

        The generated file imports the required ADK agent class, assembles
        the tools list, and defines the root_agent variable.
        """
        import_path = self._AGENT_IMPORT[agent_class]

        lines: list[str] = [
            '"""ADK agent definition."""',
            "from __future__ import annotations",
            "",
            f"from {import_path} import {agent_class}",
        ]

        # Import tools if any.
        if tool_names:
            tool_imports = ", ".join(tool_names)
            lines.append(f"from .tools import {tool_imports}")

        lines.append("")

        if agent_type == "llm":
            # LlmAgent supports model and instruction.
            tools_repr = "[" + ", ".join(tool_names) + "]" if tool_names else "[]"
            lines += [
                f"root_agent = {agent_class}(",
                f'    name="{agent_name}",',
                f'    model="{model}",',
                '    instruction="You are a helpful assistant.",',
                f"    tools={tools_repr},",
                ")",
            ]
        else:
            # Orchestrator agents take sub_agents instead of tools/model.
            if sub_agent_names:
                # Each sub-agent name is treated as an already-defined agent variable.
                sub_repr = "[" + ", ".join(sub_agent_names) + "]"
            else:
                sub_repr = "[]"
            lines += [
                f"root_agent = {agent_class}(",
                f'    name="{agent_name}",',
                f"    sub_agents={sub_repr},",
                ")",
            ]

        lines.append("")
        return "\n".join(lines)

    def _generate_tools_py(self, tool_names: list[str]) -> str:
        """Return the content of ``tools.py`` with one stub per tool name."""
        lines: list[str] = [
            '"""Tool functions for the ADK agent."""',
            "from __future__ import annotations",
            "",
        ]
        if not tool_names:
            lines.append("# No tools defined.")
            lines.append("")
            return "\n".join(lines)

        for name in tool_names:
            lines += [
                "",
                f"def {name}() -> str:",
                f'    """Stub implementation of {name}."""',
                '    return ""',
                "",
            ]

        return "\n".join(lines)

    def _generate_init_py(self, agent_name: str) -> str:
        """Return the content of ``__init__.py`` exporting ``root_agent``."""
        return dedent(
            f"""\
            \"\"\"ADK agent package — exports root_agent for ``adk run`` / ``adk web``.\"\"\"
            from .agent import root_agent  # noqa: F401

            __all__ = ["root_agent"]
            """
        )

    def _generate_config_json(self, model: str, agent_name: str) -> str:
        """Return the content of ``config.json``."""
        config = {
            "agent_name": agent_name,
            "model": model,
            "generation": {
                "temperature": 0.7,
                "max_output_tokens": 1024,
            },
        }
        return json.dumps(config, indent=2) + "\n"

    def _generate_env_template(self) -> str:
        """Return a ``.env`` template with required environment variables."""
        return dedent(
            """\
            # Environment variables for the ADK agent.
            # Copy this file to .env and fill in the values.

            # Google AI / Vertex AI credentials
            GOOGLE_API_KEY=
            GOOGLE_CLOUD_PROJECT=
            GOOGLE_CLOUD_LOCATION=us-central1

            # Optional: override the default model
            # AGENT_MODEL=gemini-2.0-flash
            """
        )
