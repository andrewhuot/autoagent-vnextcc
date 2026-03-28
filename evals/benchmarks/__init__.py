"""Standard benchmark integrations for AutoAgent evals."""

from .adapter import BenchmarkAdapter, BenchmarkResult
from .tau2 import Tau2BenchAdapter
from .webarena import WebArenaBenchAdapter
from .coding import CodingBenchAdapter

__all__ = [
    "BenchmarkAdapter",
    "BenchmarkResult",
    "Tau2BenchAdapter",
    "WebArenaBenchAdapter",
    "CodingBenchAdapter",
]
