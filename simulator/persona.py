"""Synthetic user personas for generating realistic test conversations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Persona:
    """A synthetic user persona with characteristic traits."""

    name: str
    traits: list[str]
    description: str


# Predefined personas for conversation generation
PERSONAS = [
    Persona(
        name="angry_customer",
        traits=["impatient", "demanding", "emotional", "caps_lock"],
        description="An upset customer who uses aggressive language and ALL CAPS",
    ),
    Persona(
        name="confused_customer",
        traits=["uncertain", "asking_multiple_questions", "rambling"],
        description="A customer who isn't sure what they need and provides unclear information",
    ),
    Persona(
        name="technical_user",
        traits=["precise", "knowledgeable", "detail_oriented", "uses_jargon"],
        description="A technically savvy user who expects detailed and accurate responses",
    ),
    Persona(
        name="multi_intent_user",
        traits=["compound_requests", "context_switching", "multiple_goals"],
        description="A user who combines multiple requests in one conversation",
    ),
    Persona(
        name="polite_customer",
        traits=["courteous", "patient", "clear_communicator"],
        description="A well-mannered customer who communicates clearly",
    ),
    Persona(
        name="brief_customer",
        traits=["terse", "minimal_context", "short_messages"],
        description="A customer who provides minimal information in very short messages",
    ),
    Persona(
        name="verbose_customer",
        traits=["overly_detailed", "backstory_provider", "long_messages"],
        description="A customer who provides excessive detail and context",
    ),
    Persona(
        name="edge_case_user",
        traits=["unusual_requests", "boundary_conditions", "rare_scenarios"],
        description="A user with unusual or edge-case requests",
    ),
    Persona(
        name="adversarial_user",
        traits=["prompt_injection", "jailbreak_attempts", "malicious_intent"],
        description="A user attempting to abuse or manipulate the system",
    ),
    Persona(
        name="non_native_speaker",
        traits=["grammar_errors", "translation_artifacts", "cultural_differences"],
        description="A user communicating in their non-native language",
    ),
]


def get_persona_by_name(name: str) -> Persona | None:
    """Retrieve a persona by name."""
    for persona in PERSONAS:
        if persona.name == name:
            return persona
    return None


def get_personas_by_difficulty(difficulty: str) -> list[Persona]:
    """Get personas appropriate for a given difficulty level."""
    if difficulty == "normal":
        return [p for p in PERSONAS if p.name in ["polite_customer", "brief_customer", "technical_user"]]
    elif difficulty == "edge_case":
        return [p for p in PERSONAS if p.name in ["confused_customer", "verbose_customer", "multi_intent_user", "non_native_speaker"]]
    elif difficulty == "adversarial":
        return [p for p in PERSONAS if p.name in ["angry_customer", "adversarial_user", "edge_case_user"]]
    else:
        return PERSONAS
