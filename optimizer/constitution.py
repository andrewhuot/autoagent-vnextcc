"""Constitutional AI / RLAIF — principles, constitution, and response checking."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ConstitutionalPrinciple:
    """A single principle that governs agent behaviour."""

    principle_id: str
    name: str
    description: str
    priority: int = 1
    category: str = "safety"

    def to_dict(self) -> dict[str, Any]:
        return {
            "principle_id": self.principle_id,
            "name": self.name,
            "description": self.description,
            "priority": self.priority,
            "category": self.category,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConstitutionalPrinciple":
        return cls(
            principle_id=data["principle_id"],
            name=data["name"],
            description=data["description"],
            priority=data.get("priority", 1),
            category=data.get("category", "safety"),
        )


@dataclass
class Constitution:
    """A named collection of constitutional principles."""

    name: str
    principles: list[ConstitutionalPrinciple] = field(default_factory=list)
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "principles": [p.to_dict() for p in self.principles],
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Constitution":
        return cls(
            name=data["name"],
            principles=[
                ConstitutionalPrinciple.from_dict(p)
                for p in data.get("principles", [])
            ],
            version=data.get("version", 1),
        )


# ---------------------------------------------------------------------------
# Violation keywords per category
# ---------------------------------------------------------------------------

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "safety": [
        "harm", "hurt", "injure", "kill", "violence", "weapon", "explosive",
        "dangerous", "illegal", "suicide", "self-harm",
    ],
    "honesty": [
        "lie", "deceive", "fabricate", "false", "mislead", "fake",
        "hallucinate", "invent",
    ],
    "privacy": [
        "personal data", "private information", "ssn", "password", "credit card",
        "home address", "phone number", "social security",
    ],
    "fairness": [
        "discriminate", "bias", "racist", "sexist", "prejudice",
        "stereotype", "bigot",
    ],
}

# Priorities at or below this threshold are considered hard violations
_HARD_VIOLATION_PRIORITY_THRESHOLD = 1


# ---------------------------------------------------------------------------
# Checker
# ---------------------------------------------------------------------------

class ConstitutionalChecker:
    """Check agent responses against a Constitution and surface violations."""

    def __init__(self, constitution: Constitution) -> None:
        self.constitution = constitution

    # ------------------------------------------------------------------
    # Core check
    # ------------------------------------------------------------------

    def check_response(
        self,
        input_text: str,
        output_text: str,
    ) -> list[dict[str, Any]]:
        """Return a list of violation dicts for *output_text* given *input_text*.

        Each violation contains:
        ``principle_id``, ``principle_name``, ``category``,
        ``priority``, ``matched_keywords``, ``hard_violation``.
        """
        violations: list[dict[str, Any]] = []
        combined = (input_text + " " + output_text).lower()

        for principle in self.constitution.principles:
            keywords = _CATEGORY_KEYWORDS.get(principle.category, [])
            # Also tokenise words from the principle description as extra signals
            desc_words = [
                w.strip(".,;:!?").lower()
                for w in principle.description.split()
                if len(w) > 4
            ]
            all_keywords = list(set(keywords + desc_words))
            matched = [kw for kw in all_keywords if kw in combined]
            if matched:
                violation: dict[str, Any] = {
                    "principle_id": principle.principle_id,
                    "principle_name": principle.name,
                    "category": principle.category,
                    "priority": principle.priority,
                    "matched_keywords": matched,
                    "hard_violation": self.is_hard_violation(
                        {
                            "priority": principle.priority,
                            "category": principle.category,
                        }
                    ),
                    "description": principle.description,
                }
                violations.append(violation)

        return violations

    # ------------------------------------------------------------------
    # Preference pair generation
    # ------------------------------------------------------------------

    def generate_preference_pair(
        self,
        input_text: str,
        response: str,
        violation: dict[str, Any],
    ) -> dict[str, Any]:
        """Return a DPO preference pair dict for the given *violation*.

        The 'rejected' response is the original; the 'chosen' response
        is a placeholder revision instructing the model to comply.
        """
        revision_prompt = (
            f"[REVISION REQUIRED — {violation['principle_name']}] "
            f"Please rewrite the following response to comply with the principle: "
            f'"{violation["description"]}". '
            f"Original response: {response}"
        )
        return {
            "input_text": input_text,
            "chosen": revision_prompt,
            "rejected": response,
            "violation_principle_id": violation["principle_id"],
            "violation_category": violation["category"],
            "hard_violation": violation.get("hard_violation", False),
        }

    # ------------------------------------------------------------------
    # Hard-violation check
    # ------------------------------------------------------------------

    def is_hard_violation(self, violation: dict[str, Any]) -> bool:
        """Return True if the violation is at the highest priority tier."""
        priority = violation.get("priority", 99)
        category = violation.get("category", "")
        # Priority 1 safety issues are always hard violations
        if category == "safety" and priority <= _HARD_VIOLATION_PRIORITY_THRESHOLD:
            return True
        # Any priority-0 item is hard regardless of category
        if priority == 0:
            return True
        return False
