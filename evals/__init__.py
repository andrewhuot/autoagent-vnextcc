"""Eval framework for AutoAgent-VNext."""

from .combined_eval import CombinedEvalResult, CombinedEvaluator
from .outcome import OutcomeCheck, OutcomeEvaluator, OutcomeResult
from .runner import EvalRunner
from .scorer import CompositeScorer, EvalResult
from .trace_converter import TraceToEvalConverter
from .trajectory import (
    TrajectoryEvaluator,
    TrajectoryExpectation,
    TrajectoryResult,
    TrajectoryStep,
)

__all__ = [
    # Runner / scorer
    "EvalRunner",
    "EvalResult",
    "CompositeScorer",
    # Trajectory evaluation (P0-5)
    "TrajectoryStep",
    "TrajectoryExpectation",
    "TrajectoryResult",
    "TrajectoryEvaluator",
    # Outcome evaluation (P0-5)
    "OutcomeCheck",
    "OutcomeResult",
    "OutcomeEvaluator",
    # Combined evaluation (P0-5)
    "CombinedEvalResult",
    "CombinedEvaluator",
    # Trace-to-eval pipeline (P0-6)
    "TraceToEvalConverter",
]
