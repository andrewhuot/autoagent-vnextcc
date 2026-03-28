"""Freshness tracking — score how current each memory/context entry is."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


def _parse_iso(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp, returning UTC-aware datetime."""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class FreshnessScore:
    key: str
    score: float          # 0.0 (stale) – 1.0 (fresh)
    last_accessed: str
    last_validated: str
    is_stale: bool

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "score": self.score,
            "last_accessed": self.last_accessed,
            "last_validated": self.last_validated,
            "is_stale": self.is_stale,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FreshnessScore":
        return cls(
            key=d["key"],
            score=d.get("score", 0.0),
            last_accessed=d.get("last_accessed", ""),
            last_validated=d.get("last_validated", ""),
            is_stale=d.get("is_stale", True),
        )


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------

class FreshnessTracker:
    """Scores context/memory entries based on recency of access and validation."""

    # Default half-life in days for the exponential decay function
    HALF_LIFE_DAYS: float = 7.0
    # Default threshold (score below which an entry is "stale")
    STALE_THRESHOLD: float = 0.2

    def score(self, entry: dict) -> FreshnessScore:
        """Compute a freshness score for a single entry dict.

        Score is derived from time since last_accessed using exponential decay:
            score = 2^(-age_days / HALF_LIFE_DAYS)

        Where the age used is the minimum of last_accessed and last_validated
        ages (most recent wins).
        """
        now = _now_utc()
        key = entry.get("key", "")

        last_accessed_str = entry.get("last_accessed", "")
        last_validated_str = entry.get("last_validated", last_accessed_str)

        last_accessed_dt = _parse_iso(last_accessed_str) if last_accessed_str else now
        last_validated_dt = _parse_iso(last_validated_str) if last_validated_str else now

        age_accessed = (now - last_accessed_dt).total_seconds() / 86400
        age_validated = (now - last_validated_dt).total_seconds() / 86400

        # Use the most-recent event (smallest age)
        effective_age = min(age_accessed, age_validated)

        raw_score = 2.0 ** (-effective_age / self.HALF_LIFE_DAYS)
        score = max(0.0, min(1.0, raw_score))
        is_stale = score < self.STALE_THRESHOLD

        return FreshnessScore(
            key=key,
            score=round(score, 4),
            last_accessed=last_accessed_str,
            last_validated=last_validated_str,
            is_stale=is_stale,
        )

    def batch_score(self, entries: list[dict]) -> list[FreshnessScore]:
        """Return freshness scores for a list of entries."""
        return [self.score(e) for e in entries]

    def get_stale(
        self,
        entries: list[dict],
        threshold_days: int = 30,
    ) -> list[FreshnessScore]:
        """Return entries whose last_accessed age exceeds threshold_days.

        Also marks any entry with a score below STALE_THRESHOLD as stale,
        regardless of threshold_days.
        """
        now = _now_utc()
        stale: list[FreshnessScore] = []
        for entry in entries:
            fs = self.score(entry)

            last_accessed_str = entry.get("last_accessed", "")
            if last_accessed_str:
                last_accessed_dt = _parse_iso(last_accessed_str)
                age_days = (now - last_accessed_dt).total_seconds() / 86400
                if age_days >= threshold_days or fs.is_stale:
                    fs.is_stale = True
                    stale.append(fs)
            elif fs.is_stale:
                stale.append(fs)
        return stale
