"""AST-based parser for ADK agent source files.

Extracts structured agent definitions from Python source code without executing it.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Optional

from adk.errors import AdkParseError
from adk.types import AdkAgent, AdkAgentTree, AdkAgentType, AdkCallbackSpec, AdkTool


def parse_agent_directory(path: Path) -> AdkAgentTree:
    """Parse an ADK agent directory into structured representation.

    Args:
        path: Path to the agent directory containing __init__.py and agent.py

    Returns:
        AdkAgentTree with parsed agent, tools, and sub-agents

    Raises:
        AdkParseError: If directory structure is invalid or parsing fails
    """
    if not path.exists():
        raise AdkParseError(f"Agent directory not found: {path}")

    if not path.is_dir():
        raise AdkParseError(f"Path is not a directory: {path}")

    # Parse main agent definition
    agent, callbacks = _parse_agent_file(path / "agent.py")

    # Parse tools
    tools = _parse_tools_file(path / "tools.py") if (path / "tools.py").exists() else []

    # Parse instruction from prompts.py if it exists
    if (path / "prompts.py").exists():
        instruction = _parse_prompts_file(path / "prompts.py")
        if instruction and not agent.instruction:
            agent.instruction = instruction

    # Parse config.json if it exists
    config = {}
    if (path / "config.json").exists():
        try:
            config = json.loads((path / "config.json").read_text())
        except json.JSONDecodeError as e:
            raise AdkParseError(f"Invalid config.json: {e}")

    # Merge config.json into agent.generate_config if present
    if config:
        agent.generate_config = {**config, **agent.generate_config}

    # Parse sub-agents recursively
    sub_agents_list: list[AdkAgentTree] = []
    sub_agents_dir = path / "sub_agents"
    if sub_agents_dir.exists() and sub_agents_dir.is_dir():
        for sub_dir in sub_agents_dir.iterdir():
            if sub_dir.is_dir() and (sub_dir / "__init__.py").exists():
                try:
                    sub_agent_tree = parse_agent_directory(sub_dir)
                    sub_agents_list.append(sub_agent_tree)
                except AdkParseError:
                    # Skip invalid sub-agent directories
                    pass

    return AdkAgentTree(
        agent=agent,
        tools=tools,
        callbacks=callbacks,
        sub_agents=sub_agents_list,
        config=config,
        source_path=path.resolve(),
    )


_AGENT_CLASS_TO_TYPE = {
    "Agent": AdkAgentType.LLM_AGENT,
    "LlmAgent": AdkAgentType.LLM_AGENT,
    "SequentialAgent": AdkAgentType.SEQUENTIAL_AGENT,
    "ParallelAgent": AdkAgentType.PARALLEL_AGENT,
    "LoopAgent": AdkAgentType.LOOP_AGENT,
}


def _parse_agent_file(agent_path: Path) -> tuple[AdkAgent, list[AdkCallbackSpec]]:
    """Parse agent.py and extract Agent() constructor arguments.

    Args:
        agent_path: Path to agent.py file

    Returns:
        AdkAgent with extracted fields and callback specs

    Raises:
        AdkParseError: If file doesn't exist or parsing fails
    """
    if not agent_path.exists():
        raise AdkParseError(f"agent.py not found: {agent_path}")

    try:
        source = agent_path.read_text()
        tree = ast.parse(source)
    except SyntaxError as e:
        raise AdkParseError(f"Invalid Python syntax in {agent_path}: {e}")

    # Build a module-level constants lookup for resolving variable references
    module_constants = _extract_module_constants(tree)

    # Check if there's a prompts.py import and load those constants too
    prompts_path = agent_path.parent / "prompts.py"
    if prompts_path.exists():
        prompts_constants = _parse_prompts_file_constants(prompts_path)
        module_constants.update(prompts_constants)

    # Find Agent() constructor call
    agent_call, agent_type = _find_agent_call(tree)
    if not agent_call:
        raise AdkParseError(f"No Agent() constructor found in {agent_path}")

    # Extract keyword arguments
    agent = AdkAgent()
    agent.agent_type = agent_type
    callback_bindings: dict[str, str] = {}
    for keyword in agent_call.keywords:
        arg_name = keyword.arg
        if not arg_name:
            continue

        value = _extract_value(keyword.value, module_constants)

        if arg_name == "name":
            agent.name = str(value)
        elif arg_name == "model":
            agent.model = str(value)
        elif arg_name == "instruction":
            agent.instruction = str(value)
        elif arg_name == "tools":
            agent.tools = _extract_tool_names(keyword.value)
        elif arg_name == "sub_agents":
            agent.sub_agents = _extract_agent_names(keyword.value)
        elif arg_name == "generate_config":
            if isinstance(value, dict):
                agent.generate_config = value
        elif arg_name == "before_model_callback":
            agent.before_model_callback = str(value) if value else ""
            if agent.before_model_callback:
                callback_bindings[arg_name] = agent.before_model_callback
        elif arg_name == "after_model_callback":
            agent.after_model_callback = str(value) if value else ""
            if agent.after_model_callback:
                callback_bindings[arg_name] = agent.after_model_callback
        elif arg_name == "before_agent_callback":
            agent.before_agent_callback = str(value) if value else ""
            if agent.before_agent_callback:
                callback_bindings[arg_name] = agent.before_agent_callback
        elif arg_name == "after_agent_callback":
            agent.after_agent_callback = str(value) if value else ""
            if agent.after_agent_callback:
                callback_bindings[arg_name] = agent.after_agent_callback
        elif arg_name == "before_tool_callback":
            agent.before_tool_callback = str(value) if value else ""
            if agent.before_tool_callback:
                callback_bindings[arg_name] = agent.before_tool_callback
        elif arg_name == "after_tool_callback":
            agent.after_tool_callback = str(value) if value else ""
            if agent.after_tool_callback:
                callback_bindings[arg_name] = agent.after_tool_callback

    callbacks = _extract_callback_specs(tree, callback_bindings)
    return agent, callbacks


def _parse_tools_file(tools_path: Path) -> list[AdkTool]:
    """Parse tools.py and extract @tool decorated functions.

    Args:
        tools_path: Path to tools.py file

    Returns:
        List of AdkTool objects with names, descriptions, and function bodies
    """
    if not tools_path.exists():
        return []

    try:
        source = tools_path.read_text()
        tree = ast.parse(source)
    except SyntaxError as e:
        raise AdkParseError(f"Invalid Python syntax in {tools_path}: {e}")

    tools = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            # Check if function has @tool decorator
            if _has_tool_decorator(node):
                tool = AdkTool(
                    name=node.name,
                    description=ast.get_docstring(node) or "",
                    signature=_get_function_signature(node),
                    function_body=ast.unparse(node),
                )
                tools.append(tool)

    return tools


def _parse_prompts_file(prompts_path: Path) -> str:
    """Parse prompts.py and extract instruction string constants.

    Args:
        prompts_path: Path to prompts.py file

    Returns:
        Concatenated instruction text from module-level string constants
    """
    if not prompts_path.exists():
        return ""

    try:
        source = prompts_path.read_text()
        tree = ast.parse(source)
    except SyntaxError:
        return ""

    instructions = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    # Look for module-level string constants that look like instructions
                    if "instruction" in target.id.lower() or "prompt" in target.id.lower():
                        value = _extract_value(node.value)
                        if isinstance(value, str) and value.strip():
                            instructions.append(value.strip())

    return "\n\n".join(instructions)


def _parse_prompts_file_constants(prompts_path: Path) -> dict[str, any]:
    """Parse prompts.py and extract all string constants.

    Args:
        prompts_path: Path to prompts.py file

    Returns:
        Dict mapping constant names to their values
    """
    if not prompts_path.exists():
        return {}

    try:
        source = prompts_path.read_text()
        tree = ast.parse(source)
    except SyntaxError:
        return {}

    return _extract_module_constants(tree)


def _find_agent_call(tree: ast.AST) -> tuple[Optional[ast.Call], AdkAgentType]:
    """Find the first Agent() constructor call in the AST.

    Args:
        tree: Parsed AST

    Returns:
        Tuple of the constructor call and detected ADK agent type
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            class_name = _agent_constructor_name(node.func)
            if class_name:
                return node, _AGENT_CLASS_TO_TYPE[class_name]
    return None, AdkAgentType.LLM_AGENT


def _agent_constructor_name(func: ast.AST) -> str | None:
    """Return a supported ADK constructor name for a call target."""

    if isinstance(func, ast.Name) and func.id in _AGENT_CLASS_TO_TYPE:
        return func.id
    if isinstance(func, ast.Attribute) and func.attr in _AGENT_CLASS_TO_TYPE:
        return func.attr
    return None


def _has_tool_decorator(func_node: ast.FunctionDef) -> bool:
    """Check if a function has @tool decorator.

    Args:
        func_node: AST FunctionDef node

    Returns:
        True if function has @tool decorator
    """
    for decorator in func_node.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == "tool":
            return True
        elif isinstance(decorator, ast.Attribute) and decorator.attr == "tool":
            return True
    return False


def _get_function_signature(func_node: ast.FunctionDef) -> str:
    """Extract function signature as a string.

    Args:
        func_node: AST FunctionDef node

    Returns:
        Function signature like "func_name(arg1: type, arg2: type, kwarg1=default)"
    """
    args_list = []
    for arg in func_node.args.args:
        arg_str = arg.arg
        # Add type annotation if present
        if arg.annotation:
            type_str = ast.unparse(arg.annotation)
            arg_str = f"{arg_str}: {type_str}"
        args_list.append(arg_str)

    # Add defaults
    defaults = func_node.args.defaults
    if defaults:
        num_defaults = len(defaults)
        num_args = len(args_list)
        for i, default in enumerate(defaults):
            idx = num_args - num_defaults + i
            default_repr = ast.unparse(default)
            # If type annotation already present, append the default
            if ": " in args_list[idx]:
                args_list[idx] = f"{args_list[idx]} = {default_repr}"
            else:
                args_list[idx] = f"{args_list[idx]}={default_repr}"

    return f"{func_node.name}({', '.join(args_list)})"


def _extract_callback_specs(
    tree: ast.AST,
    callback_bindings: dict[str, str],
) -> list[AdkCallbackSpec]:
    """Extract callback function specs for bound callback names."""

    if not callback_bindings:
        return []

    function_defs = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    callbacks: list[AdkCallbackSpec] = []
    for binding, callback_name in callback_bindings.items():
        node = function_defs.get(callback_name)
        callbacks.append(
            AdkCallbackSpec(
                name=callback_name,
                callback_type=binding,
                function_name=callback_name,
                description=ast.get_docstring(node) or "" if node else "",
                signature=_get_function_signature(node) if node else callback_name,
                function_body=ast.unparse(node) if node else "",
            )
        )
    return callbacks


def _extract_module_constants(tree: ast.AST) -> dict[str, Any]:
    """Extract module-level constant assignments from AST.

    Args:
        tree: Parsed AST

    Returns:
        Dict mapping constant names to their values
    """
    constants = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    # Try to extract the value
                    try:
                        value = _extract_value(node.value, {})
                        if isinstance(value, (str, int, float, bool)):
                            constants[target.id] = value
                    except Exception:
                        pass
    return constants


def _extract_value(node: ast.AST, constants: dict[str, Any] | None = None) -> Any:
    """Extract a Python value from an AST node.

    Args:
        node: AST node representing a value
        constants: Dict of module-level constants for resolving Name nodes

    Returns:
        Extracted Python value (str, int, dict, list, etc.)
    """
    if constants is None:
        constants = {}

    if isinstance(node, ast.Constant):
        return node.value
    elif isinstance(node, ast.List):
        return [_extract_value(elt, constants) for elt in node.elts]
    elif isinstance(node, ast.Dict):
        result = {}
        for key_node, value_node in zip(node.keys, node.values):
            if key_node is not None:
                key = _extract_value(key_node, constants)
                value = _extract_value(value_node, constants)
                result[key] = value
        return result
    elif isinstance(node, ast.Name):
        # Try to resolve from constants first
        if node.id in constants:
            return constants[node.id]
        return node.id
    elif isinstance(node, ast.Attribute):
        return ast.unparse(node)
    elif isinstance(node, ast.JoinedStr):
        # f-string - extract as template
        return ast.unparse(node)
    else:
        # For complex expressions, return unparsed string
        try:
            return ast.unparse(node)
        except Exception:
            return ""


def _extract_tool_names(node: ast.AST) -> list[str]:
    """Extract tool names from a tools list in Agent() constructor.

    Args:
        node: AST node representing tools argument (typically a List)

    Returns:
        List of tool names (strings)
    """
    if isinstance(node, ast.List):
        names = []
        for elt in node.elts:
            if isinstance(elt, ast.Name):
                names.append(elt.id)
            elif isinstance(elt, ast.Attribute):
                names.append(elt.attr)
        return names
    return []


def _extract_agent_names(node: ast.AST) -> list[str]:
    """Extract sub-agent names from a sub_agents list in Agent() constructor.

    Args:
        node: AST node representing sub_agents argument (typically a List)

    Returns:
        List of agent names (strings)
    """
    if isinstance(node, ast.List):
        names = []
        for elt in node.elts:
            if isinstance(elt, ast.Name):
                names.append(elt.id)
            elif isinstance(elt, ast.Attribute):
                names.append(elt.attr)
        return names
    return []
