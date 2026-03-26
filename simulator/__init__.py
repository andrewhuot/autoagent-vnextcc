"""Simulation sandbox for generating synthetic conversations and stress-testing configs."""

from .persona import PERSONAS, Persona, get_persona_by_name, get_personas_by_difficulty
from .sandbox import (
    ComparisonResult,
    SimulationSandbox,
    StressTestResult,
    SyntheticConversation,
)

__all__ = [
    "PERSONAS",
    "ComparisonResult",
    "Persona",
    "SimulationSandbox",
    "StressTestResult",
    "SyntheticConversation",
    "get_persona_by_name",
    "get_personas_by_difficulty",
]
