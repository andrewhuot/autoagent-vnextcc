"""WebArena web task benchmark adapter."""

from __future__ import annotations

from typing import Callable

from .adapter import BenchmarkAdapter


class WebArenaBenchAdapter(BenchmarkAdapter):
    """Benchmark adapter for WebArena: web navigation and interaction evaluation.

    WebArena tests agents on realistic web tasks such as browsing, form submission,
    navigation, and information extraction across simulated website environments.
    """

    name = "webarena"
    description = (
        "Web task benchmark that tests agents on navigation, form interaction, "
        "and information extraction across simulated website environments."
    )
    version = "1.0.0"

    # ------------------------------------------------------------------
    # Dataset
    # ------------------------------------------------------------------

    def load_dataset(self) -> list[dict]:
        """Return sample web navigation and interaction cases.

        Each case specifies a starting URL, a task instruction, required actions,
        and a success criterion. In production these would be loaded from the
        official WebArena task suite.

        Returns:
            List of case dicts with ``id``, ``task``, ``start_url``,
            ``required_actions``, and ``success_criterion`` fields.
        """
        return [
            {
                "id": "webarena-001",
                "task": "Find the price of the cheapest red laptop on the shopping site.",
                "start_url": "http://shopping.webarena.example/",
                "site": "shopping",
                "required_actions": ["search", "filter_by_color", "extract_price"],
                "success_criterion": {
                    "type": "value_match",
                    "field": "extracted_price",
                    "pattern": r"\$[\d,]+\.?\d*",
                },
                "metadata": {"difficulty": "easy", "category": "information_extraction"},
            },
            {
                "id": "webarena-002",
                "task": "Post a comment saying 'Great product!' on the first item in the forum.",
                "start_url": "http://forum.webarena.example/",
                "site": "forum",
                "required_actions": ["navigate_to_item", "click_comment", "type_comment", "submit"],
                "success_criterion": {
                    "type": "state_change",
                    "condition": "comment_posted",
                    "expected_text": "Great product!",
                },
                "metadata": {"difficulty": "medium", "category": "form_interaction"},
            },
            {
                "id": "webarena-003",
                "task": "Change the shipping address in account settings to '123 Main St, Springfield'.",
                "start_url": "http://shopping.webarena.example/account",
                "site": "shopping",
                "required_actions": [
                    "navigate_to_settings",
                    "click_edit_address",
                    "clear_field",
                    "type_address",
                    "save",
                ],
                "success_criterion": {
                    "type": "state_change",
                    "condition": "address_updated",
                    "expected_text": "123 Main St, Springfield",
                },
                "metadata": {"difficulty": "medium", "category": "account_management"},
            },
            {
                "id": "webarena-004",
                "task": "Find and download the Q3 financial report PDF from the investor relations page.",
                "start_url": "http://corporate.webarena.example/investors",
                "site": "corporate",
                "required_actions": ["navigate_to_reports", "find_q3_report", "download_pdf"],
                "success_criterion": {
                    "type": "file_downloaded",
                    "file_pattern": r"q3.*\.pdf",
                },
                "metadata": {"difficulty": "hard", "category": "document_retrieval"},
            },
            {
                "id": "webarena-005",
                "task": "Book a table for 2 at 7pm tonight at any Italian restaurant on the site.",
                "start_url": "http://restaurant.webarena.example/",
                "site": "restaurant",
                "required_actions": [
                    "search_italian",
                    "select_restaurant",
                    "choose_date_time",
                    "set_party_size",
                    "confirm_booking",
                ],
                "success_criterion": {
                    "type": "booking_confirmed",
                    "party_size": 2,
                    "cuisine": "italian",
                },
                "metadata": {"difficulty": "hard", "category": "multi_step_booking"},
            },
            {
                "id": "webarena-006",
                "task": "What is the return policy for electronics on the shopping site?",
                "start_url": "http://shopping.webarena.example/",
                "site": "shopping",
                "required_actions": ["find_help_or_faq", "navigate_to_returns", "extract_policy_text"],
                "success_criterion": {
                    "type": "value_match",
                    "field": "policy_text",
                    "contains": "return",
                },
                "metadata": {"difficulty": "easy", "category": "information_extraction"},
            },
        ]

    # ------------------------------------------------------------------
    # Case execution
    # ------------------------------------------------------------------

    def run_case(self, agent_fn: Callable, case: dict) -> dict:
        """Run a single WebArena case.

        Args:
            agent_fn: Callable that accepts a dict with ``task``, ``start_url``,
                ``site``, and ``required_actions`` fields, and returns a dict with
                ``actions_taken``, ``result``, and ``success`` fields.
            case: A single case dict from :meth:`load_dataset`.

        Returns:
            Result dict with ``case_id``, ``passed``, ``output``,
            ``actions_taken``, ``required_actions_coverage``, and
            ``task_complete`` fields.
        """
        try:
            output = agent_fn({
                "task": case.get("task", ""),
                "start_url": case.get("start_url", ""),
                "site": case.get("site", ""),
                "required_actions": case.get("required_actions", []),
                "success_criterion": case.get("success_criterion", {}),
            })
        except Exception as exc:  # noqa: BLE001
            return {
                "case_id": case["id"],
                "passed": False,
                "output": None,
                "error": str(exc),
                "actions_taken": [],
                "required_actions_coverage": 0.0,
                "task_complete": False,
            }

        if isinstance(output, str):
            output = {"result": output, "actions_taken": [], "success": False}

        actions_taken = output.get("actions_taken", [])
        required = case.get("required_actions", [])
        if required:
            covered = sum(1 for a in required if a in actions_taken)
            coverage = covered / len(required)
        else:
            coverage = 1.0

        task_complete = bool(output.get("success", False))
        passed = task_complete and coverage >= 0.8

        return {
            "case_id": case["id"],
            "passed": passed,
            "output": output,
            "actions_taken": actions_taken,
            "required_actions_coverage": round(coverage, 4),
            "task_complete": task_complete,
            "site": case.get("site", ""),
            "difficulty": case.get("metadata", {}).get("difficulty", ""),
        }

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def score(self, results: list[dict]) -> dict:
        """Compute WebArena aggregate scores from case results.

        Metrics:
        - ``task_completion``: fraction of cases where the task was fully
          completed (``task_complete`` is True).
        - ``action_accuracy``: mean required-actions coverage across all cases.
        - ``overall``: geometric mean of the two metrics.

        Args:
            results: List of result dicts produced by :meth:`run_case`.

        Returns:
            Dictionary of metric name -> float score.
        """
        if not results:
            return {
                "task_completion": 0.0,
                "action_accuracy": 0.0,
                "overall": 0.0,
            }

        task_completion = sum(
            1 for r in results if r.get("task_complete", False)
        ) / len(results)

        coverages = [r.get("required_actions_coverage", 0.0) for r in results]
        action_accuracy = sum(coverages) / len(coverages)

        # Geometric mean of both metrics
        product = task_completion * action_accuracy
        overall = product ** 0.5 if product > 0 else 0.0

        return {
            "task_completion": round(task_completion, 4),
            "action_accuracy": round(action_accuracy, 4),
            "overall": round(overall, 4),
        }
