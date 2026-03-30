"""Adapters between the SQLite experiment model and the shared contract."""

from __future__ import annotations

from optimizer.experiments import ExperimentCard
from shared.contracts import ExperimentRecord


def experiment_card_to_record(card: ExperimentCard) -> ExperimentRecord:
    """Convert an internal experiment card into the shared record contract."""
    return card.to_record()


def experiment_record_to_card(record: ExperimentRecord) -> ExperimentCard:
    """Convert the shared record contract back into the SQLite experiment model."""
    return ExperimentCard.from_record(record)
