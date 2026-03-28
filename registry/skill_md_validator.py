"""Validation for SKILL.md format compliance."""

from __future__ import annotations

from registry.skill_md import SkillMdParser


REQUIRED_FRONTMATTER_FIELDS: list[str] = ["name", "version", "kind", "category", "description"]
REQUIRED_BODY_SECTIONS: list[str] = ["description"]
RECOMMENDED_BODY_SECTIONS: list[str] = ["instructions", "mutations", "eval_criteria"]

VALID_KINDS: frozenset[str] = frozenset({"runtime", "buildtime"})
VALID_CATEGORIES: frozenset[str] = frozenset({"routing", "safety", "latency", "quality", "cost"})
VALID_TRUST_LEVELS: frozenset[str] = frozenset(
    {"unverified", "community-tested", "benchmark-validated", "enterprise-certified"}
)
VALID_ROLLOUT_POLICIES: frozenset[str] = frozenset({"gradual", "immediate", "canary", "manual"})


class SkillMdValidationError(Exception):
    """Raised when a SKILL.md document fails validation."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"SKILL.md validation failed with {len(errors)} error(s): {errors}")


class SkillMdValidator:
    """Validates SKILL.md documents for format compliance.

    Usage::

        validator = SkillMdValidator()
        errors = validator.validate(content)
        if errors:
            raise SkillMdValidationError(errors)
    """

    def __init__(self) -> None:
        self._parser = SkillMdParser()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(self, content: str) -> list[str]:
        """Validate a SKILL.md string and return a list of error messages.

        An empty list means the document is valid.

        Args:
            content: Full SKILL.md file content.

        Returns:
            List of human-readable error strings.
        """
        errors: list[str] = []

        try:
            parsed = self._parser.parse(content)
        except Exception as exc:  # noqa: BLE001
            return [f"Failed to parse SKILL.md: {exc}"]

        frontmatter = parsed.get("frontmatter", {})
        errors.extend(self.validate_frontmatter(frontmatter))

        # Build sections dict (everything except frontmatter)
        sections = {k: v for k, v in parsed.items() if k != "frontmatter"}
        errors.extend(self.validate_body(sections))

        # Validate eval contract if present
        eval_contract = frontmatter.get("eval_contract", {})
        if eval_contract:
            errors.extend(self.validate_eval_contract(eval_contract))

        return errors

    def validate_frontmatter(self, frontmatter: dict) -> list[str]:
        """Check required and well-typed frontmatter fields.

        Args:
            frontmatter: Parsed YAML frontmatter dict.

        Returns:
            List of error strings (empty = valid).
        """
        errors: list[str] = []

        # Required fields
        for field in REQUIRED_FRONTMATTER_FIELDS:
            if field not in frontmatter or frontmatter[field] is None:
                errors.append(f"Missing required frontmatter field: '{field}'")

        # Type checks for present fields
        if "name" in frontmatter and not isinstance(frontmatter["name"], str):
            errors.append("Frontmatter field 'name' must be a string")

        if "version" in frontmatter:
            version = frontmatter["version"]
            if not isinstance(version, (int, float)) or (isinstance(version, float) and not version.is_integer()):
                errors.append("Frontmatter field 'version' must be an integer")

        if "kind" in frontmatter and frontmatter["kind"] not in VALID_KINDS:
            errors.append(
                f"Frontmatter field 'kind' must be one of {sorted(VALID_KINDS)}, "
                f"got: '{frontmatter['kind']}'"
            )

        if "category" in frontmatter and frontmatter["category"] not in VALID_CATEGORIES:
            errors.append(
                f"Frontmatter field 'category' must be one of {sorted(VALID_CATEGORIES)}, "
                f"got: '{frontmatter['category']}'"
            )

        if "trust_level" in frontmatter and frontmatter["trust_level"] not in VALID_TRUST_LEVELS:
            errors.append(
                f"Frontmatter field 'trust_level' must be one of {sorted(VALID_TRUST_LEVELS)}, "
                f"got: '{frontmatter['trust_level']}'"
            )

        if "rollout_policy" in frontmatter and frontmatter["rollout_policy"] not in VALID_ROLLOUT_POLICIES:
            errors.append(
                f"Frontmatter field 'rollout_policy' must be one of {sorted(VALID_ROLLOUT_POLICIES)}, "
                f"got: '{frontmatter['rollout_policy']}'"
            )

        # List fields
        for list_field in ("tags", "dependencies", "allowed_tools", "supported_frameworks", "required_approvals"):
            val = frontmatter.get(list_field)
            if val is not None and not isinstance(val, list):
                errors.append(f"Frontmatter field '{list_field}' must be a list, got: {type(val).__name__}")

        # Trigger validation
        triggers = frontmatter.get("triggers", [])
        if triggers is not None and not isinstance(triggers, list):
            errors.append("Frontmatter field 'triggers' must be a list")
        elif isinstance(triggers, list):
            for i, trigger in enumerate(triggers):
                if not isinstance(trigger, dict):
                    errors.append(f"Trigger #{i} must be a dict")
                    continue
                if "operator" in trigger and trigger["operator"] not in ("gt", "lt", "gte", "lte", "eq"):
                    errors.append(
                        f"Trigger #{i} has invalid operator '{trigger['operator']}'; "
                        "expected: gt, lt, gte, lte, eq"
                    )

        return errors

    def validate_body(self, sections: dict) -> list[str]:
        """Check required and recommended body sections.

        Args:
            sections: Dict of section names (lowercased, underscored) to content.

        Returns:
            List of error strings (empty = valid).
        """
        errors: list[str] = []

        # Normalize section keys
        normalized = {k.lower().replace(" ", "_"): v for k, v in sections.items()}

        for required in REQUIRED_BODY_SECTIONS:
            if required not in normalized:
                errors.append(f"Missing required body section: '{required.replace('_', ' ').title()}'")

        # Recommended sections produce warnings (not errors) - represented as info messages
        # We keep them as non-fatal strings prefixed with [warning] so callers can distinguish.
        for recommended in RECOMMENDED_BODY_SECTIONS:
            if recommended not in normalized:
                errors.append(
                    f"[warning] Recommended body section missing: "
                    f"'{recommended.replace('_', ' ').title()}'"
                )

        # Validate mutations if present
        mutations = normalized.get("mutations", [])
        if isinstance(mutations, list):
            for i, mut in enumerate(mutations):
                if isinstance(mut, dict):
                    if not mut.get("name"):
                        errors.append(f"Mutation #{i} is missing 'name'")
                    if not mut.get("mutation_type") and not mut.get("type"):
                        errors.append(f"Mutation #{i} ('{mut.get('name', '?')}') is missing 'type'")

        # Validate examples if present
        examples = normalized.get("examples", [])
        if isinstance(examples, list):
            for i, ex in enumerate(examples):
                if isinstance(ex, dict):
                    if "improvement" in ex:
                        try:
                            imp = float(ex["improvement"])
                            if not (-1.0 <= imp <= 1.0):
                                errors.append(
                                    f"Example #{i} improvement {imp} is outside expected range [-1.0, 1.0]"
                                )
                        except (TypeError, ValueError):
                            errors.append(f"Example #{i} improvement must be a number")

        return errors

    def validate_eval_contract(self, contract: dict) -> list[str]:
        """Validate an eval contract dict.

        Args:
            contract: The ``eval_contract`` dict from the frontmatter.

        Returns:
            List of error strings (empty = valid).
        """
        errors: list[str] = []

        if not isinstance(contract, dict):
            return [f"eval_contract must be a dict, got: {type(contract).__name__}"]

        for key in ("metrics", "criteria"):
            val = contract.get(key)
            if val is not None and not isinstance(val, list):
                errors.append(f"eval_contract.{key} must be a list")

        # Validate individual criteria
        criteria = contract.get("criteria", [])
        if isinstance(criteria, list):
            for i, criterion in enumerate(criteria):
                if not isinstance(criterion, dict):
                    errors.append(f"eval_contract.criteria[{i}] must be a dict")
                    continue
                if "metric" not in criterion:
                    errors.append(f"eval_contract.criteria[{i}] missing 'metric'")
                if "target" not in criterion:
                    errors.append(f"eval_contract.criteria[{i}] missing 'target'")
                else:
                    try:
                        float(criterion["target"])
                    except (TypeError, ValueError):
                        errors.append(f"eval_contract.criteria[{i}].target must be numeric")

        return errors

    def is_valid(self, content: str) -> bool:
        """Return True if the SKILL.md document has no errors (warnings are ignored).

        Args:
            content: Full SKILL.md file content.

        Returns:
            True if there are no non-warning errors.
        """
        errors = self.validate(content)
        hard_errors = [e for e in errors if not e.startswith("[warning]")]
        return len(hard_errors) == 0
