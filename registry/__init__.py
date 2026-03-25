"""Modular Registry for AutoAgent.

Re-exports the public API for convenient imports.
"""

from registry.store import RegistryStore
from registry.skills import SkillRegistry
from registry.policies import PolicyRegistry
from registry.tool_contracts import ToolContractRegistry
from registry.handoff_schemas import HandoffSchemaRegistry
from registry.playbooks import Playbook, PlaybookStore, seed_starter_playbooks

__all__ = [
    "RegistryStore",
    "SkillRegistry",
    "PolicyRegistry",
    "ToolContractRegistry",
    "HandoffSchemaRegistry",
    "Playbook",
    "PlaybookStore",
    "seed_starter_playbooks",
]
