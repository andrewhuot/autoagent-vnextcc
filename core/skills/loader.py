"""Load skills from multiple sources with validation and error handling.

This module provides a comprehensive skill loading system that supports:
- YAML files (single skill or skill packs)
- Python modules (skills defined as code)
- SkillStore (database-backed skills)

All loading operations include validation and detailed error reporting.
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any

import yaml

from core.skills.store import SkillStore
from core.skills.types import (
    EvalCriterion,
    MutationOperator,
    Policy,
    Skill,
    SkillDependency,
    SkillExample,
    SkillKind,
    TestCase,
    ToolDefinition,
    TriggerCondition,
)
from core.skills.validator import SkillValidator, ValidationResult

logger = logging.getLogger(__name__)


class SkillLoadError(Exception):
    """Raised when skill loading fails."""

    pass


class SkillLoader:
    """Load skills from YAML files, Python modules, or the SkillStore.

    Provides comprehensive error handling, validation, and logging for all
    skill loading operations.

    Example:
        ```python
        loader = SkillLoader()

        # Load from YAML
        skills, errors = loader.validate_and_load("skills/my_skill.yaml")
        if errors:
            print(f"Validation errors: {errors}")

        # Load a skill pack
        skills = loader.load_pack("skills/customer_support_pack.yaml")

        # Load from Python module
        skills = loader.load_from_python("plugins.custom_skills")
        ```
    """

    def __init__(self, validator: SkillValidator | None = None) -> None:
        """Initialize the skill loader.

        Args:
            validator: Optional custom validator. If None, uses default SkillValidator.
        """
        self.validator = validator or SkillValidator()

    # ------------------------------------------------------------------
    # YAML Loading
    # ------------------------------------------------------------------

    def load_from_yaml(self, path: str) -> list[Skill]:
        """Load skills from a YAML file.

        Supports both single skill files and skill packs (multiple skills).

        YAML format for single skill:
        ```yaml
        id: skill-001
        name: keyword_expansion
        kind: build
        version: "1.0"
        description: Expand routing keywords
        ...
        ```

        YAML format for skill pack:
        ```yaml
        skills:
          - id: skill-001
            name: keyword_expansion
            ...
          - id: skill-002
            name: instruction_hardening
            ...
        ```

        Args:
            path: Path to YAML file

        Returns:
            List of loaded Skill instances

        Raises:
            SkillLoadError: If file not found, invalid YAML, or parsing fails
        """
        file_path = Path(path)

        if not file_path.exists():
            raise SkillLoadError(f"File not found: {path}")

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise SkillLoadError(f"Invalid YAML in {path}: {e}") from e
        except Exception as e:
            raise SkillLoadError(f"Failed to read {path}: {e}") from e

        if data is None:
            raise SkillLoadError(f"Empty YAML file: {path}")

        try:
            # Check if this is a skill pack (has 'skills' key) or single skill
            if isinstance(data, dict) and "skills" in data:
                # Skill pack
                skills_data = data["skills"]
                if not isinstance(skills_data, list):
                    raise SkillLoadError(f"'skills' key must be a list in {path}")

                skills = [self._parse_skill_dict(skill_dict, path) for skill_dict in skills_data]
                logger.info(f"Loaded {len(skills)} skills from pack: {path}")
                return skills

            elif isinstance(data, dict):
                # Single skill
                skill = self._parse_skill_dict(data, path)
                logger.info(f"Loaded skill: {skill.name} from {path}")
                return [skill]

            else:
                raise SkillLoadError(f"Invalid YAML structure in {path}: expected dict or list")

        except SkillLoadError:
            raise
        except Exception as e:
            raise SkillLoadError(f"Failed to parse skills from {path}: {e}") from e

    def load_pack(self, pack_path: str) -> list[Skill]:
        """Load a skill pack (YAML file with multiple skills).

        This is an alias for load_from_yaml that explicitly expects a pack format.

        Args:
            pack_path: Path to skill pack YAML file

        Returns:
            List of loaded Skill instances

        Raises:
            SkillLoadError: If file not found, invalid format, or parsing fails
        """
        skills = self.load_from_yaml(pack_path)

        if len(skills) == 0:
            logger.warning(f"Skill pack is empty: {pack_path}")

        return skills

    def _parse_skill_dict(self, data: dict[str, Any], source: str) -> Skill:
        """Parse a skill dictionary into a Skill instance.

        Args:
            data: Raw skill data from YAML
            source: Source file path (for error messages)

        Returns:
            Parsed Skill instance

        Raises:
            SkillLoadError: If required fields are missing or invalid
        """
        try:
            # Parse kind
            kind_str = data.get("kind", "build")
            if kind_str not in ["build", "runtime"]:
                raise SkillLoadError(f"Invalid skill kind: {kind_str}. Must be 'build' or 'runtime'")
            kind = SkillKind.BUILD if kind_str == "build" else SkillKind.RUNTIME

            # Parse nested objects with field name normalization
            mutations = []
            if "mutations" in data:
                for m in data.get("mutations", []):
                    # Normalize field names: mutation_type -> operator_type
                    m_normalized = dict(m)
                    if "mutation_type" in m_normalized and "operator_type" not in m_normalized:
                        m_normalized["operator_type"] = m_normalized.pop("mutation_type")
                    mutations.append(MutationOperator.from_dict(m_normalized))

            triggers = [
                TriggerCondition.from_dict(t) for t in data.get("triggers", [])
            ] if "triggers" in data else []

            eval_criteria = [
                EvalCriterion.from_dict(e) for e in data.get("eval_criteria", [])
            ] if "eval_criteria" in data else []

            tools = [
                ToolDefinition.from_dict(t) for t in data.get("tools", [])
            ] if "tools" in data else []

            policies = [
                Policy.from_dict(p) for p in data.get("policies", [])
            ] if "policies" in data else []

            dependencies = [
                SkillDependency.from_dict(d) for d in data.get("dependencies", [])
            ] if "dependencies" in data else []

            test_cases = [
                TestCase.from_dict(t) for t in data.get("test_cases", [])
            ] if "test_cases" in data else []

            examples = []
            if "examples" in data:
                for e in data.get("examples", []):
                    # Normalize field names: surface -> description if description missing
                    e_normalized = dict(e)
                    if "description" not in e_normalized and "surface" in e_normalized:
                        # Use context as description if available, otherwise use a default
                        e_normalized["description"] = e_normalized.get("context", f"Example for {e_normalized.get('surface', 'unknown surface')}")
                    elif "description" not in e_normalized:
                        e_normalized["description"] = e_normalized.get("context", "Skill example")
                    examples.append(SkillExample.from_dict(e_normalized))

            # Generate ID from name if missing
            skill_id = data.get("id", "")
            if not skill_id and data.get("name"):
                # Generate ID from name: convert to lowercase, replace spaces with hyphens
                skill_id = data.get("name", "").lower().replace(" ", "-").replace("_", "-")

            # Normalize version to semver format
            version = str(data.get("version", "1.0.0"))
            if version and "." not in version:
                version = f"{version}.0.0"
            elif version and version.count(".") == 1:
                version = f"{version}.0"

            # Build the skill
            skill = Skill(
                id=skill_id,
                name=data.get("name", ""),
                kind=kind,
                version=version,
                description=data.get("description", ""),
                capabilities=data.get("capabilities", []),
                mutations=mutations,
                triggers=triggers,
                eval_criteria=eval_criteria,
                guardrails=data.get("guardrails", []),
                examples=examples,
                tools=tools,
                instructions=data.get("instructions", ""),
                policies=policies,
                dependencies=dependencies,
                test_cases=test_cases,
                tags=data.get("tags", []),
                domain=data.get("domain", "general"),
                metadata=data.get("metadata", {}),
                author=data.get("author", "autoagent"),
                status=data.get("status", "active"),
            )

            return skill

        except KeyError as e:
            raise SkillLoadError(f"Missing required field in {source}: {e}") from e
        except Exception as e:
            raise SkillLoadError(f"Failed to parse skill from {source}: {e}") from e

    # ------------------------------------------------------------------
    # Python Module Loading
    # ------------------------------------------------------------------

    def load_from_python(self, module_path: str) -> list[Skill]:
        """Load skills from a Python module.

        The module must define skills in one of these ways:
        1. A `SKILLS` list/tuple of Skill instances
        2. A `get_skills()` function that returns list[Skill]
        3. Individual Skill instances as module-level variables

        Example module:
        ```python
        from core.skills.types import Skill, SkillKind

        SKILLS = [
            Skill(
                id="custom-001",
                name="custom_skill",
                kind=SkillKind.BUILD,
                version="1.0",
                description="A custom skill",
            ),
        ]
        ```

        Args:
            module_path: Python module path (e.g., "plugins.my_skills" or "/path/to/module.py")

        Returns:
            List of loaded Skill instances

        Raises:
            SkillLoadError: If module not found, invalid format, or loading fails
        """
        try:
            # Try importing as a module path first
            if "/" in module_path or module_path.endswith(".py"):
                # File path
                file_path = Path(module_path)
                if not file_path.exists():
                    raise SkillLoadError(f"Module file not found: {module_path}")

                spec = importlib.util.spec_from_file_location("_skill_module", file_path)
                if spec is None or spec.loader is None:
                    raise SkillLoadError(f"Failed to load module spec from {module_path}")

                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            else:
                # Module import path
                try:
                    module = importlib.import_module(module_path)
                except ModuleNotFoundError as e:
                    raise SkillLoadError(f"Module not found: {module_path}") from e

            # Extract skills from module
            skills: list[Skill] = []

            # Method 1: SKILLS constant
            if hasattr(module, "SKILLS"):
                skills_obj = getattr(module, "SKILLS")
                if isinstance(skills_obj, (list, tuple)):
                    skills.extend(s for s in skills_obj if isinstance(s, Skill))
                else:
                    logger.warning(f"SKILLS in {module_path} is not a list/tuple")

            # Method 2: get_skills() function
            elif hasattr(module, "get_skills"):
                get_skills = getattr(module, "get_skills")
                if callable(get_skills):
                    result = get_skills()
                    if isinstance(result, (list, tuple)):
                        skills.extend(s for s in result if isinstance(s, Skill))
                    else:
                        logger.warning(f"get_skills() in {module_path} did not return a list")

            # Method 3: Scan for Skill instances
            else:
                for attr_name in dir(module):
                    if attr_name.startswith("_"):
                        continue
                    attr = getattr(module, attr_name)
                    if isinstance(attr, Skill):
                        skills.append(attr)

            if not skills:
                logger.warning(f"No skills found in module: {module_path}")

            logger.info(f"Loaded {len(skills)} skills from Python module: {module_path}")
            return skills

        except SkillLoadError:
            raise
        except Exception as e:
            raise SkillLoadError(f"Failed to load skills from Python module {module_path}: {e}") from e

    # ------------------------------------------------------------------
    # Store Loading
    # ------------------------------------------------------------------

    def load_from_store(self, skill_ids: list[str], store: SkillStore) -> list[Skill]:
        """Load skills from a SkillStore by IDs.

        Args:
            skill_ids: List of skill IDs to load
            store: SkillStore instance to load from

        Returns:
            List of loaded Skill instances (may be fewer than requested if some IDs not found)

        Raises:
            SkillLoadError: If store access fails
        """
        if not skill_ids:
            return []

        try:
            skills: list[Skill] = []

            for skill_id in skill_ids:
                skill = store.get(skill_id)
                if skill is None:
                    logger.warning(f"Skill not found in store: {skill_id}")
                else:
                    skills.append(skill)

            logger.info(f"Loaded {len(skills)}/{len(skill_ids)} skills from store")
            return skills

        except Exception as e:
            raise SkillLoadError(f"Failed to load skills from store: {e}") from e

    # ------------------------------------------------------------------
    # Validated Loading
    # ------------------------------------------------------------------

    def validate_and_load(self, path: str) -> tuple[list[Skill], list[str]]:
        """Load skills from a file with validation.

        This method loads skills and validates them, returning both the skills
        and any validation errors. Unlike load_from_yaml, this does not raise
        an exception on validation errors.

        Args:
            path: Path to skill file (YAML or Python)

        Returns:
            Tuple of (loaded_skills, error_messages)
            - loaded_skills: List of valid Skill instances
            - error_messages: List of validation error messages

        Example:
            ```python
            skills, errors = loader.validate_and_load("skills/my_skill.yaml")
            if errors:
                print("Validation errors:", errors)
            else:
                print(f"Loaded {len(skills)} valid skills")
            ```
        """
        all_errors: list[str] = []
        valid_skills: list[Skill] = []

        try:
            # Load skills based on file extension
            if path.endswith((".yaml", ".yml")):
                skills = self.load_from_yaml(path)
            elif path.endswith(".py"):
                skills = self.load_from_python(path)
            else:
                return [], [f"Unsupported file type: {path}. Must be .yaml, .yml, or .py"]

            # Validate each skill
            for skill in skills:
                result = self.validator.validate_schema(skill)

                if result.is_valid:
                    valid_skills.append(skill)
                    if result.warnings:
                        for warning in result.warnings:
                            logger.warning(f"Skill {skill.name}: {warning}")
                else:
                    for error in result.errors:
                        error_msg = f"Skill {skill.name or '(unnamed)'}: {error}"
                        all_errors.append(error_msg)
                        logger.error(error_msg)

        except SkillLoadError as e:
            all_errors.append(str(e))
        except Exception as e:
            all_errors.append(f"Unexpected error loading {path}: {e}")

        return valid_skills, all_errors

    # ------------------------------------------------------------------
    # Batch Loading
    # ------------------------------------------------------------------

    def load_directory(
        self,
        directory: str,
        recursive: bool = False,
        validate: bool = True,
    ) -> tuple[list[Skill], list[str]]:
        """Load all skill files from a directory.

        Args:
            directory: Path to directory containing skill files
            recursive: Whether to search subdirectories recursively
            validate: Whether to validate skills before returning

        Returns:
            Tuple of (loaded_skills, error_messages)

        Example:
            ```python
            skills, errors = loader.load_directory("skills/", recursive=True)
            print(f"Loaded {len(skills)} skills with {len(errors)} errors")
            ```
        """
        dir_path = Path(directory)

        if not dir_path.exists():
            return [], [f"Directory not found: {directory}"]

        if not dir_path.is_dir():
            return [], [f"Not a directory: {directory}"]

        all_skills: list[Skill] = []
        all_errors: list[str] = []

        # Find all skill files
        patterns = ["*.yaml", "*.yml", "*.py"]
        skill_files: list[Path] = []

        for pattern in patterns:
            if recursive:
                skill_files.extend(dir_path.rglob(pattern))
            else:
                skill_files.extend(dir_path.glob(pattern))

        if not skill_files:
            logger.warning(f"No skill files found in {directory}")
            return [], []

        # Load each file
        for file_path in skill_files:
            try:
                if validate:
                    skills, errors = self.validate_and_load(str(file_path))
                    all_skills.extend(skills)
                    all_errors.extend(errors)
                else:
                    if file_path.suffix in [".yaml", ".yml"]:
                        skills = self.load_from_yaml(str(file_path))
                    else:
                        skills = self.load_from_python(str(file_path))
                    all_skills.extend(skills)

            except SkillLoadError as e:
                all_errors.append(f"{file_path}: {e}")
            except Exception as e:
                all_errors.append(f"{file_path}: Unexpected error: {e}")

        logger.info(
            f"Loaded {len(all_skills)} skills from {len(skill_files)} files "
            f"in {directory} ({len(all_errors)} errors)"
        )

        return all_skills, all_errors
