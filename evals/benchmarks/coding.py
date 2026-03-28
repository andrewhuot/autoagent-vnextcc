"""Coding benchmark adapter for code generation and bug-fix evaluation."""

from __future__ import annotations

import re
from typing import Callable

from .adapter import BenchmarkAdapter


class CodingBenchAdapter(BenchmarkAdapter):
    """Benchmark adapter for coding tasks: generation, bug-fixing, and test passing.

    This adapter covers common coding benchmark scenarios including function
    generation from docstrings, bug fixing, and algorithmic problem-solving,
    evaluated on correctness and test pass rate.
    """

    name = "coding"
    description = (
        "Coding benchmark that tests code generation and bug-fixing across "
        "multiple languages and difficulty levels, evaluated on correctness "
        "and test pass rate."
    )
    version = "1.0.0"

    # ------------------------------------------------------------------
    # Dataset
    # ------------------------------------------------------------------

    def load_dataset(self) -> list[dict]:
        """Return sample code generation and bug-fix cases.

        Each case contains a ``prompt``, a ``task_type`` (generate or fix),
        a reference ``solution``, and a list of ``test_cases`` with
        input/expected-output pairs. In production these would be loaded from
        HumanEval, MBPP, SWE-bench, or a similar dataset.

        Returns:
            List of case dicts with ``id``, ``task_type``, ``language``,
            ``prompt``, ``solution``, and ``test_cases`` fields.
        """
        return [
            {
                "id": "coding-001",
                "task_type": "generate",
                "language": "python",
                "prompt": (
                    "Write a Python function `add(a, b)` that returns the sum of "
                    "two numbers."
                ),
                "solution": "def add(a, b):\n    return a + b\n",
                "test_cases": [
                    {"input": {"a": 1, "b": 2}, "expected": 3},
                    {"input": {"a": -5, "b": 5}, "expected": 0},
                    {"input": {"a": 0, "b": 0}, "expected": 0},
                ],
                "metadata": {"difficulty": "easy", "category": "arithmetic"},
            },
            {
                "id": "coding-002",
                "task_type": "generate",
                "language": "python",
                "prompt": (
                    "Write a Python function `is_palindrome(s: str) -> bool` that "
                    "returns True if the string is a palindrome (ignoring case and "
                    "non-alphanumeric characters)."
                ),
                "solution": (
                    "def is_palindrome(s: str) -> bool:\n"
                    "    cleaned = re.sub(r'[^a-z0-9]', '', s.lower())\n"
                    "    return cleaned == cleaned[::-1]\n"
                ),
                "test_cases": [
                    {"input": {"s": "racecar"}, "expected": True},
                    {"input": {"s": "hello"}, "expected": False},
                    {"input": {"s": "A man a plan a canal Panama"}, "expected": True},
                    {"input": {"s": ""}, "expected": True},
                ],
                "metadata": {"difficulty": "easy", "category": "string_manipulation"},
            },
            {
                "id": "coding-003",
                "task_type": "fix",
                "language": "python",
                "prompt": (
                    "Fix the bug in the following function that should return the "
                    "nth Fibonacci number:\n\n"
                    "def fib(n):\n"
                    "    if n <= 0:\n"
                    "        return 0\n"
                    "    if n == 1:\n"
                    "        return 1\n"
                    "    return fib(n - 1) + fib(n - 3)  # BUG: should be n-2\n"
                ),
                "solution": (
                    "def fib(n):\n"
                    "    if n <= 0:\n"
                    "        return 0\n"
                    "    if n == 1:\n"
                    "        return 1\n"
                    "    return fib(n - 1) + fib(n - 2)\n"
                ),
                "test_cases": [
                    {"input": {"n": 0}, "expected": 0},
                    {"input": {"n": 1}, "expected": 1},
                    {"input": {"n": 6}, "expected": 8},
                    {"input": {"n": 10}, "expected": 55},
                ],
                "metadata": {"difficulty": "medium", "category": "bug_fix"},
            },
            {
                "id": "coding-004",
                "task_type": "generate",
                "language": "python",
                "prompt": (
                    "Write a function `two_sum(nums: list[int], target: int) -> list[int]` "
                    "that returns the indices of two numbers in nums that add up to target. "
                    "You may assume exactly one solution exists."
                ),
                "solution": (
                    "def two_sum(nums: list[int], target: int) -> list[int]:\n"
                    "    seen = {}\n"
                    "    for i, v in enumerate(nums):\n"
                    "        complement = target - v\n"
                    "        if complement in seen:\n"
                    "            return [seen[complement], i]\n"
                    "        seen[v] = i\n"
                    "    return []\n"
                ),
                "test_cases": [
                    {"input": {"nums": [2, 7, 11, 15], "target": 9}, "expected": [0, 1]},
                    {"input": {"nums": [3, 2, 4], "target": 6}, "expected": [1, 2]},
                    {"input": {"nums": [3, 3], "target": 6}, "expected": [0, 1]},
                ],
                "metadata": {"difficulty": "medium", "category": "algorithms"},
            },
            {
                "id": "coding-005",
                "task_type": "fix",
                "language": "python",
                "prompt": (
                    "Fix the off-by-one error in this binary search implementation:\n\n"
                    "def binary_search(arr, target):\n"
                    "    lo, hi = 0, len(arr)\n"
                    "    while lo < hi:\n"
                    "        mid = (lo + hi) // 2\n"
                    "        if arr[mid] == target:\n"
                    "            return mid\n"
                    "        elif arr[mid] < target:\n"
                    "            lo = mid\n"  # BUG: should be mid + 1
                    "        else:\n"
                    "            hi = mid - 1\n"  # BUG: should be mid
                    "    return -1\n"
                ),
                "solution": (
                    "def binary_search(arr, target):\n"
                    "    lo, hi = 0, len(arr) - 1\n"
                    "    while lo <= hi:\n"
                    "        mid = (lo + hi) // 2\n"
                    "        if arr[mid] == target:\n"
                    "            return mid\n"
                    "        elif arr[mid] < target:\n"
                    "            lo = mid + 1\n"
                    "        else:\n"
                    "            hi = mid - 1\n"
                    "    return -1\n"
                ),
                "test_cases": [
                    {"input": {"arr": [1, 3, 5, 7, 9], "target": 5}, "expected": 2},
                    {"input": {"arr": [1, 3, 5, 7, 9], "target": 1}, "expected": 0},
                    {"input": {"arr": [1, 3, 5, 7, 9], "target": 9}, "expected": 4},
                    {"input": {"arr": [1, 3, 5, 7, 9], "target": 4}, "expected": -1},
                ],
                "metadata": {"difficulty": "hard", "category": "bug_fix"},
            },
        ]

    # ------------------------------------------------------------------
    # Case execution
    # ------------------------------------------------------------------

    def run_case(self, agent_fn: Callable, case: dict) -> dict:
        """Run a single coding case.

        Args:
            agent_fn: Callable that accepts a dict with ``prompt``,
                ``task_type``, ``language``, and ``test_cases`` fields, and
                returns a dict with ``code``, ``tests_passed``, and
                ``tests_total`` fields.
            case: A single case dict from :meth:`load_dataset`.

        Returns:
            Result dict with ``case_id``, ``passed``, ``output``, ``code``,
            ``tests_passed``, ``tests_total``, and ``test_pass_rate`` fields.
        """
        try:
            output = agent_fn({
                "prompt": case.get("prompt", ""),
                "task_type": case.get("task_type", "generate"),
                "language": case.get("language", "python"),
                "test_cases": case.get("test_cases", []),
                "solution": case.get("solution", ""),
            })
        except Exception as exc:  # noqa: BLE001
            return {
                "case_id": case["id"],
                "passed": False,
                "output": None,
                "error": str(exc),
                "code": "",
                "tests_passed": 0,
                "tests_total": len(case.get("test_cases", [])),
                "test_pass_rate": 0.0,
                "syntactically_correct": False,
            }

        if isinstance(output, str):
            output = {"code": output, "tests_passed": 0, "tests_total": 0}

        code = output.get("code", "")
        tests_total = output.get("tests_total", len(case.get("test_cases", [])))
        tests_passed = output.get("tests_passed", 0)
        test_pass_rate = tests_passed / tests_total if tests_total > 0 else 0.0

        # Basic syntactic check: does the output contain a function definition?
        syntactically_correct = bool(
            re.search(r"\bdef\s+\w+\s*\(", code)
            if case.get("language", "python") == "python"
            else len(code.strip()) > 0
        )

        passed = syntactically_correct and test_pass_rate >= 1.0

        return {
            "case_id": case["id"],
            "passed": passed,
            "output": output,
            "code": code,
            "tests_passed": tests_passed,
            "tests_total": tests_total,
            "test_pass_rate": round(test_pass_rate, 4),
            "syntactically_correct": syntactically_correct,
            "task_type": case.get("task_type", ""),
            "difficulty": case.get("metadata", {}).get("difficulty", ""),
        }

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def score(self, results: list[dict]) -> dict:
        """Compute coding benchmark aggregate scores from case results.

        Metrics:
        - ``correctness``: fraction of cases that fully passed (all tests green).
        - ``test_pass_rate``: mean test pass rate across all cases.
        - ``syntax_rate``: fraction of cases producing syntactically valid code.
        - ``overall``: weighted combination (correctness 50%, test_pass_rate 30%,
          syntax_rate 20%).

        Args:
            results: List of result dicts produced by :meth:`run_case`.

        Returns:
            Dictionary of metric name -> float score.
        """
        if not results:
            return {
                "correctness": 0.0,
                "test_pass_rate": 0.0,
                "syntax_rate": 0.0,
                "overall": 0.0,
            }

        correctness = sum(1 for r in results if r.get("passed", False)) / len(results)

        pass_rates = [r.get("test_pass_rate", 0.0) for r in results]
        test_pass_rate = sum(pass_rates) / len(pass_rates)

        syntax_rate = sum(
            1 for r in results if r.get("syntactically_correct", False)
        ) / len(results)

        overall = 0.5 * correctness + 0.3 * test_pass_rate + 0.2 * syntax_rate

        return {
            "correctness": round(correctness, 4),
            "test_pass_rate": round(test_pass_rate, 4),
            "syntax_rate": round(syntax_rate, 4),
            "overall": round(overall, 4),
        }
