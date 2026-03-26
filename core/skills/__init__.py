"""Core skills module - unified skill system for build-time and run-time capabilities.

Skills are the foundational abstraction for both:
- Build-time skills: optimization strategies AutoAgent uses to improve agents
- Run-time skills: capabilities the deployed agent itself has

This module provides:
- Unified Skill model that works for both kinds
- SQLite-backed skill store with versioning
- Skill composition with dependency resolution
- Skill marketplace for discovery and installation
- Validation and testing infrastructure
"""

from core.skills.types import (
    Skill,
    SkillKind,
    MutationOperator,
    TriggerCondition,
    EvalCriterion,
    ToolDefinition,
    Policy,
    TestCase,
    EffectivenessMetrics,
    SkillDependency,
)

# Note: Store, loader, composer, validator, marketplace are all implemented
from core.skills.store import SkillStore
from core.skills.loader import SkillLoader
from core.skills.composer import SkillComposer, SkillSet, CompositionConflict
from core.skills.validator import SkillValidator, ValidationResult
from core.skills.marketplace import SkillMarketplace

__all__ = [
    # Types
    "Skill",
    "SkillKind",
    "MutationOperator",
    "TriggerCondition",
    "EvalCriterion",
    "ToolDefinition",
    "Policy",
    "TestCase",
    "EffectivenessMetrics",
    "SkillDependency",
    # Store
    "SkillStore",
    # Loader
    "SkillLoader",
    # Composer
    "SkillComposer",
    "SkillSet",
    "CompositionConflict",
    # Validator
    "SkillValidator",
    "ValidationResult",
    # Marketplace
    "SkillMarketplace",
]
