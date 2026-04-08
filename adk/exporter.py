"""Export optimized AgentLab configs back to ADK source.

This module patches the original ADK Python source files to reflect changes made
through AgentLab optimization. It preserves formatting, comments, and code style
by using AST parsing and targeted patching rather than full rewrites.
"""
from __future__ import annotations

import ast
import json
import shutil
from pathlib import Path

from adk.errors import AdkExportError
from adk.mapper import AdkMapper
from adk.parser import parse_agent_directory
from adk.portability import build_adk_export_matrix
from adk.types import AdkAgentTree, ExportResult


class AdkExporter:
    """Exports optimized AgentLab configs back to ADK Python source."""

    def __init__(self):
        self.mapper = AdkMapper()

    def export_agent(
        self,
        config: dict,
        snapshot_path: str,
        output_dir: str | None = None,
        dry_run: bool = False,
    ) -> ExportResult:
        """Export optimized config back to ADK source files.

        Pipeline:
        1. Load base snapshot (parse original source)
        2. Compute diff between config and base
        3. Generate patches for changed values
        4. Apply patches preserving formatting
        5. Write patched files to output_dir

        Args:
            config: Optimized AgentLab config
            snapshot_path: Path to original ADK snapshot directory
            output_dir: Directory to write modified source files (defaults to snapshot_path)
            dry_run: If True, preview changes without writing files

        Returns:
            ExportResult with changes and output path

        Raises:
            AdkExportError: If export fails
        """
        try:
            snapshot = Path(snapshot_path)
            if not snapshot.exists():
                raise AdkExportError(f"Snapshot directory not found: {snapshot_path}")

            # 1. Load base snapshot by parsing original source
            base_tree = parse_agent_directory(snapshot)

            # 2. Compute diff
            changes = self._compute_changes(base_tree, config)
            export_matrix = build_adk_export_matrix(base_tree)

            if dry_run or not changes:
                return ExportResult(
                    output_path=str(output_dir or snapshot_path),
                    changes=changes,
                    files_modified=0,
                    export_matrix=export_matrix,
                )

            # 3. Apply patches
            output_path = Path(output_dir) if output_dir else snapshot
            files_modified = self._apply_changes(
                snapshot, output_path, changes, base_tree, config
            )

            return ExportResult(
                output_path=str(output_path),
                changes=changes,
                files_modified=files_modified,
                export_matrix=export_matrix,
            )

        except AdkExportError:
            raise
        except Exception as exc:
            raise AdkExportError(f"Export failed: {exc}") from exc

    def preview_changes(self, config: dict, snapshot_path: str) -> list[dict]:
        """Preview what changes export would make without writing files.

        Args:
            config: Optimized AgentLab config
            snapshot_path: Path to original ADK snapshot

        Returns:
            List of change records
        """
        result = self.export_agent(config, snapshot_path, dry_run=True)
        return result.changes

    def _compute_changes(self, base_tree: AdkAgentTree, config: dict) -> list[dict]:
        """Compute diff between base tree and optimized config.

        Args:
            base_tree: Parsed original agent structure
            config: Optimized AgentLab config

        Returns:
            List of change descriptors
        """
        changes = []

        # Check instruction changes
        prompts = config.get("prompts", {})
        if not prompts and "instructions" in config:
            prompts = config["instructions"]
        if prompts:
            for agent_name, new_instruction in prompts.items():
                if agent_name == base_tree.agent.name or agent_name == "root":
                    if base_tree.agent.instruction != new_instruction:
                        changes.append({
                            "resource": "agent",
                            "field": "instruction",
                            "action": "update",
                            "agent_name": base_tree.agent.name,
                            "old": base_tree.agent.instruction,
                            "new": new_instruction,
                        })

        # Check model changes
        model_override = config.get("model")
        legacy_generation_settings = config.get("generation_settings", {})
        if not model_override and isinstance(legacy_generation_settings, dict):
            model_override = legacy_generation_settings.get("model")
        if model_override and base_tree.agent.model != model_override:
            changes.append({
                "resource": "agent",
                "field": "model",
                "action": "update",
                "old": base_tree.agent.model,
                "new": model_override,
            })

        gen_settings = config.get("generation", {})
        if not gen_settings:
            gen_settings = config.get("generation_settings", {})

        for external_key, config_key in {
            "temperature": "temperature",
            "max_tokens": "max_output_tokens",
            "max_output_tokens": "max_output_tokens",
            "top_p": "top_p",
            "top_k": "top_k",
        }.items():
            if external_key in gen_settings:
                old_val = base_tree.agent.generate_config.get(config_key, base_tree.config.get(config_key))
                new_val = gen_settings[external_key]
                if old_val != new_val:
                    changes.append({
                        "resource": "config",
                        "field": config_key,
                        "action": "update",
                        "old": old_val,
                        "new": new_val,
                    })

        # Check tool description changes
        base_tools = {t.name: t for t in base_tree.tools}
        tool_descriptions = config.get("tool_descriptions", {})
        tools_config = config.get("tools", {})
        for tool_name, tool_cfg in tools_config.items():
            if isinstance(tool_cfg, dict) and "description" in tool_cfg:
                tool_descriptions[tool_name] = tool_cfg["description"]
        for tool_name, new_desc in tool_descriptions.items():
            if tool_name in base_tools:
                old_desc = base_tools[tool_name].description
                if old_desc != new_desc:
                    changes.append({
                        "resource": "tool",
                        "field": "description",
                        "action": "update",
                        "tool_name": tool_name,
                        "old": old_desc,
                        "new": new_desc,
                    })

        return changes

    def _apply_changes(
        self,
        snapshot_dir: Path,
        output_dir: Path,
        changes: list[dict],
        base_tree: AdkAgentTree,
        config: dict,
    ) -> int:
        """Apply changes to source files.

        Args:
            snapshot_dir: Original source directory
            output_dir: Output directory for patched files
            changes: List of changes to apply
            base_tree: Parsed base agent tree
            config: Optimized config

        Returns:
            Number of files modified
        """
        # Create output directory if it doesn't exist
        output_dir.mkdir(parents=True, exist_ok=True)

        # Copy all files from snapshot to output first
        if snapshot_dir != output_dir:
            for item in snapshot_dir.iterdir():
                if item.is_file():
                    shutil.copy2(item, output_dir / item.name)
                elif item.is_dir() and item.name != "__pycache__":
                    shutil.copytree(item, output_dir / item.name, dirs_exist_ok=True)

        files_modified = set()

        for change in changes:
            resource = change["resource"]

            if resource == "agent":
                field = change["field"]
                if field == "instruction":
                    self._patch_instruction(
                        output_dir / "agent.py",
                        change["old"],
                        change["new"],
                    )
                    files_modified.add("agent.py")
                elif field == "model":
                    self._patch_model(
                        output_dir / "agent.py",
                        change["old"],
                        change["new"],
                    )
                    files_modified.add("agent.py")

            elif resource == "config":
                self._patch_config_json(
                    output_dir / "config.json",
                    change["field"],
                    change["new"],
                )
                files_modified.add("config.json")

            elif resource == "tool":
                if change["field"] == "description":
                    self._patch_tool_docstring(
                        output_dir / "tools.py",
                        change["tool_name"],
                        change["old"],
                        change["new"],
                    )
                    files_modified.add("tools.py")

        return len(files_modified)

    def _patch_instruction(
        self, agent_file: Path, old_instruction: str, new_instruction: str
    ) -> None:
        """Patch instruction field in agent.py.

        Args:
            agent_file: Path to agent.py
            old_instruction: Old instruction text
            new_instruction: New instruction text
        """
        if not agent_file.exists():
            return

        source = agent_file.read_text(encoding="utf-8")

        try:
            tree = ast.parse(source)
        except SyntaxError:
            return

        lines = source.splitlines(keepends=True)

        # Find Agent() call and instruction field using AST
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if (isinstance(func, ast.Name) and func.id == "Agent") or (
                    isinstance(func, ast.Attribute) and func.attr == "Agent"
                ):
                    # Found Agent() call, now find instruction keyword
                    for keyword in node.keywords:
                        if keyword.arg == "instruction":
                            # Get the line number and indentation
                            line_num = keyword.value.lineno - 1
                            indent = len(lines[line_num]) - len(lines[line_num].lstrip())

                            # Handle multi-line strings by finding the end
                            # Look for closing """ or '''
                            end_line = line_num
                            for j in range(line_num, len(lines)):
                                if '"""' in lines[j] or "'''" in lines[j]:
                                    # Check if this is the closing quote
                                    count = lines[j].count('"""') + lines[j].count("'''")
                                    if j == line_num and count == 2:
                                        # Single line string
                                        end_line = line_num
                                        break
                                    elif j > line_num and count >= 1:
                                        # Multi-line string end
                                        end_line = j
                                        break

                            # Replace all lines from line_num to end_line
                            new_line = " " * indent + f'instruction="""{new_instruction}""",\n'
                            lines[line_num] = new_line

                            # Remove any extra lines if it was multi-line
                            if end_line > line_num:
                                for j in range(line_num + 1, end_line + 1):
                                    lines[j] = ""

                            agent_file.write_text("".join(lines), encoding="utf-8")
                            return

    def _patch_model(self, agent_file: Path, old_model: str, new_model: str) -> None:
        """Patch model field in agent.py.

        Args:
            agent_file: Path to agent.py
            old_model: Old model name
            new_model: New model name
        """
        if not agent_file.exists():
            return

        source = agent_file.read_text(encoding="utf-8")

        # Simple string replacement for model field
        # Look for model="..." pattern
        source = source.replace(f'model="{old_model}"', f'model="{new_model}"')

        agent_file.write_text(source, encoding="utf-8")

    def _patch_config_json(
        self, config_file: Path, field: str, new_value: any
    ) -> None:
        """Patch a field in config.json.

        Args:
            config_file: Path to config.json
            field: Field name to update
            new_value: New value for the field
        """
        if not config_file.exists():
            # Create new config.json
            config = {field: new_value}
        else:
            try:
                config = json.loads(config_file.read_text(encoding="utf-8"))
                config[field] = new_value
            except json.JSONDecodeError:
                config = {field: new_value}

        config_file.write_text(
            json.dumps(config, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _patch_tool_docstring(
        self, tools_file: Path, tool_name: str, old_docstring: str, new_docstring: str
    ) -> None:
        """Patch a tool function's docstring in tools.py.

        Args:
            tools_file: Path to tools.py
            tool_name: Name of tool function
            old_docstring: Old docstring text
            new_docstring: New docstring text
        """
        if not tools_file.exists():
            return

        source = tools_file.read_text(encoding="utf-8")

        try:
            tree = ast.parse(source)
        except SyntaxError:
            return

        lines = source.splitlines(keepends=True)

        # Find the function definition and its docstring
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == tool_name:
                if (
                    node.body
                    and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                ):
                    docstring_node = node.body[0].value
                    line_num = docstring_node.lineno - 1

                    # Get indentation
                    indent_line = lines[line_num]
                    indent = len(indent_line) - len(indent_line.lstrip())

                    # Replace docstring
                    new_line = " " * indent + f'"""{new_docstring}"""\n'
                    lines[line_num] = new_line

                    tools_file.write_text("".join(lines), encoding="utf-8")
                    break
