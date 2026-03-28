"""Domain types for business-outcome joins — P0-9."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# OutcomeType enum
# ---------------------------------------------------------------------------

class OutcomeType(str, Enum):
    """Supported business-outcome signal types."""

    CSAT = "CSAT"
    NPS = "NPS"
    RESOLUTION_RATE = "RESOLUTION_RATE"
    ESCALATION_RATE = "ESCALATION_RATE"
    REFUND_RATE = "REFUND_RATE"
    CONVERSION_RATE = "CONVERSION_RATE"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"
    HUMAN_QA_SCORE = "HUMAN_QA_SCORE"
    TICKET_REOPEN = "TICKET_REOPEN"
    CHURN = "CHURN"
    CUSTOM = "CUSTOM"


# ---------------------------------------------------------------------------
# BusinessOutcome
# ---------------------------------------------------------------------------

@dataclass
class BusinessOutcome:
    """A single business-outcome signal optionally linked to a trace."""

    outcome_id: str = field(default_factory=_new_uuid)
    trace_id: str = ""
    outcome_type: OutcomeType = OutcomeType.CUSTOM
    outcome_value: float = 0.0
    timestamp: str = field(default_factory=_now_iso)
    confidence: float = 1.0
    source: str = ""
    delay_hours: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome_id": self.outcome_id,
            "trace_id": self.trace_id,
            "outcome_type": self.outcome_type.value,
            "outcome_value": self.outcome_value,
            "timestamp": self.timestamp,
            "confidence": self.confidence,
            "source": self.source,
            "delay_hours": self.delay_hours,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BusinessOutcome":
        return cls(
            outcome_id=d.get("outcome_id", _new_uuid()),
            trace_id=d.get("trace_id", ""),
            outcome_type=OutcomeType(d.get("outcome_type", OutcomeType.CUSTOM.value)),
            outcome_value=float(d.get("outcome_value", 0.0)),
            timestamp=d.get("timestamp", _now_iso()),
            confidence=float(d.get("confidence", 1.0)),
            source=d.get("source", ""),
            delay_hours=float(d.get("delay_hours", 0.0)),
            metadata=d.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# OutcomeJoin
# ---------------------------------------------------------------------------

@dataclass
class OutcomeJoin:
    """Join record linking a BusinessOutcome to a trace."""

    join_id: str = field(default_factory=_new_uuid)
    trace_id: str = ""
    outcome_id: str = ""
    joined_at: str = field(default_factory=_now_iso)
    join_method: str = "exact_match"

    def to_dict(self) -> dict[str, Any]:
        return {
            "join_id": self.join_id,
            "trace_id": self.trace_id,
            "outcome_id": self.outcome_id,
            "joined_at": self.joined_at,
            "join_method": self.join_method,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "OutcomeJoin":
        return cls(
            join_id=d.get("join_id", _new_uuid()),
            trace_id=d.get("trace_id", ""),
            outcome_id=d.get("outcome_id", ""),
            joined_at=d.get("joined_at", _now_iso()),
            join_method=d.get("join_method", "exact_match"),
        )


# ---------------------------------------------------------------------------
# OutcomeConnectorConfig
# ---------------------------------------------------------------------------

@dataclass
class OutcomeConnectorConfig:
    """Configuration for an external outcome data connector."""

    connector_type: str = ""
    source_name: str = ""
    config: dict[str, Any] = field(default_factory=dict)
    polling_interval_seconds: int = 3600

    def to_dict(self) -> dict[str, Any]:
        return {
            "connector_type": self.connector_type,
            "source_name": self.source_name,
            "config": self.config,
            "polling_interval_seconds": self.polling_interval_seconds,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "OutcomeConnectorConfig":
        return cls(
            connector_type=d.get("connector_type", ""),
            source_name=d.get("source_name", ""),
            config=d.get("config", {}),
            polling_interval_seconds=int(d.get("polling_interval_seconds", 3600)),
        )


# ---------------------------------------------------------------------------
# JudgeCalibrationSignal
# ---------------------------------------------------------------------------

@dataclass
class JudgeCalibrationSignal:
    """Alignment signal comparing a judge score against a real business outcome."""

    judge_id: str = ""
    trace_id: str = ""
    judge_score: float = 0.0
    business_outcome_value: float = 0.0
    drift_detected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "judge_id": self.judge_id,
            "trace_id": self.trace_id,
            "judge_score": self.judge_score,
            "business_outcome_value": self.business_outcome_value,
            "drift_detected": self.drift_detected,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "JudgeCalibrationSignal":
        return cls(
            judge_id=d.get("judge_id", ""),
            trace_id=d.get("trace_id", ""),
            judge_score=float(d.get("judge_score", 0.0)),
            business_outcome_value=float(d.get("business_outcome_value", 0.0)),
            drift_detected=bool(d.get("drift_detected", False)),
        )


# ---------------------------------------------------------------------------
# SkillCalibrationSignal
# ---------------------------------------------------------------------------

@dataclass
class SkillCalibrationSignal:
    """Alignment signal comparing skill judge improvement to actual outcome delta."""

    skill_name: str = ""
    judge_improvement: float = 0.0
    business_outcome_delta: float = 0.0
    misaligned: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_name": self.skill_name,
            "judge_improvement": self.judge_improvement,
            "business_outcome_delta": self.business_outcome_delta,
            "misaligned": self.misaligned,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SkillCalibrationSignal":
        return cls(
            skill_name=d.get("skill_name", ""),
            judge_improvement=float(d.get("judge_improvement", 0.0)),
            business_outcome_delta=float(d.get("business_outcome_delta", 0.0)),
            misaligned=bool(d.get("misaligned", False)),
        )
