"""Environment checker — verify actual state changes independent of agent self-reports.

The checker provides a collection of independent verification methods that
inspect databases, API call logs, the file system, and arbitrary side effects.
All methods return a structured result dict so they can be aggregated by
:meth:`EnvironmentChecker.combined_check`.
"""

from __future__ import annotations

import os
from typing import Any


class EnvironmentChecker:
    """Verify that an agent actually produced the expected side effects.

    Each ``check_*`` method returns a result dict with at least:
    - ``passed`` (bool)
    - ``score`` (float 0-1)
    - ``checked`` (int)   – number of assertions run
    - ``failures`` (list) – details for each failing assertion
    - ``details`` (dict)  – method-specific extra info

    :meth:`combined_check` runs an arbitrary list of named checks and returns
    an aggregate result.
    """

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------

    def check_database_state(
        self,
        connection_info: dict[str, Any],
        expected_records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Verify database records match expectations.

        *connection_info* describes the connection (used by real connectors).
        In the current implementation a lightweight in-process simulation is
        used: if ``connection_info`` contains a ``"records"`` key the check
        compares those records against *expected_records*.  This keeps the
        checker dependency-free while remaining realistic.

        Each element of *expected_records* should contain:
        - ``"table"``  – table name (used as a grouping key)
        - ``"fields"`` – dict of field→value assertions
        - ``"operator"`` – optional, defaults to ``"eq"``
        """
        failures: list[dict[str, Any]] = []
        actual_records: list[dict[str, Any]] = connection_info.get("records", [])

        for expected in expected_records:
            table = expected.get("table", "")
            fields = expected.get("fields", {})
            operator = expected.get("operator", "eq")

            # Find matching record in actual_records
            matching = [
                r for r in actual_records
                if r.get("table", "") == table
            ]

            found = False
            for record in matching:
                record_fields = record.get("fields", record)  # support flat dicts
                if self._record_matches(record_fields, fields, operator):
                    found = True
                    break

            if not found:
                failures.append({
                    "table": table,
                    "expected_fields": fields,
                    "operator": operator,
                    "issue": "no_matching_record",
                    "actual_count": len(matching),
                })

        total = len(expected_records)
        passed_count = total - len(failures)
        score = passed_count / total if total > 0 else 1.0

        return {
            "passed": len(failures) == 0,
            "score": round(score, 4),
            "checked": total,
            "failures": failures,
            "details": {
                "connection_type": connection_info.get("type", "unknown"),
                "actual_record_count": len(actual_records),
            },
        }

    # ------------------------------------------------------------------
    # API call log
    # ------------------------------------------------------------------

    def check_api_call_log(
        self,
        log_entries: list[dict[str, Any]],
        expected_calls: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Verify that expected API calls appear in the log.

        Each element of *expected_calls* should have:
        - ``"endpoint"`` (str) – required, must match ``log_entry["endpoint"]``
        - ``"method"``   (str) – optional HTTP method check
        - ``"params"``   (dict) – optional subset-match on request params
        - ``"status"``   (int | str) – optional expected response status
        """
        failures: list[dict[str, Any]] = []
        remaining_log = list(log_entries)

        for expected in expected_calls:
            endpoint = expected.get("endpoint", "")
            method = expected.get("method", "").upper()
            params = expected.get("params") or {}
            expected_status = expected.get("status")

            found_idx = None
            for idx, entry in enumerate(remaining_log):
                if not self._api_call_matches(entry, endpoint, method, params, expected_status):
                    continue
                found_idx = idx
                break

            if found_idx is not None:
                remaining_log.pop(found_idx)
            else:
                failures.append({
                    "endpoint": endpoint,
                    "method": method,
                    "params": params,
                    "status": expected_status,
                    "issue": "call_not_found_in_log",
                })

        total = len(expected_calls)
        passed_count = total - len(failures)
        score = passed_count / total if total > 0 else 1.0

        return {
            "passed": len(failures) == 0,
            "score": round(score, 4),
            "checked": total,
            "failures": failures,
            "details": {
                "log_entries_total": len(log_entries),
                "unexpected_calls": len(remaining_log),
            },
        }

    # ------------------------------------------------------------------
    # File system
    # ------------------------------------------------------------------

    def check_file_system(
        self,
        paths: list[str],
        expected_states: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Verify file system state for the given paths.

        *expected_states* is parallel to *paths*.  Each element may contain:
        - ``"exists"``   (bool) – whether the path should exist
        - ``"contains"`` (str)  – substring that must appear in the file
        - ``"min_size"`` (int)  – minimum file size in bytes
        - ``"is_dir"``   (bool) – whether the path should be a directory
        """
        failures: list[dict[str, Any]] = []

        for path, expected in zip(paths, expected_states):
            path_failures = self._check_single_path(path, expected)
            failures.extend(path_failures)

        total = len(paths)
        paths_failed = len({f["path"] for f in failures})
        passed_count = total - paths_failed
        score = passed_count / total if total > 0 else 1.0

        return {
            "passed": len(failures) == 0,
            "score": round(score, 4),
            "checked": total,
            "failures": failures,
            "details": {"paths_checked": paths},
        }

    # ------------------------------------------------------------------
    # Side effects
    # ------------------------------------------------------------------

    def verify_side_effects(
        self,
        actual_effects: list[dict[str, Any]],
        expected_effects: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Verify that all expected side effects are present in actual effects.

        Each effect dict should have at minimum:
        - ``"type"``    (str) – e.g. ``"email_sent"``, ``"webhook_fired"``
        - ``"payload"`` (dict, optional) – subset-match on effect payload
        """
        failures: list[dict[str, Any]] = []
        remaining = list(actual_effects)

        for expected in expected_effects:
            effect_type = expected.get("type", "")
            payload = expected.get("payload") or {}

            found_idx = None
            for idx, actual in enumerate(remaining):
                if actual.get("type", "") != effect_type:
                    continue
                actual_payload = actual.get("payload") or {}
                if not self._is_subset(payload, actual_payload):
                    continue
                found_idx = idx
                break

            if found_idx is not None:
                remaining.pop(found_idx)
            else:
                failures.append({
                    "type": effect_type,
                    "expected_payload": payload,
                    "issue": "side_effect_not_found",
                })

        total = len(expected_effects)
        passed_count = total - len(failures)
        score = passed_count / total if total > 0 else 1.0

        return {
            "passed": len(failures) == 0,
            "score": round(score, 4),
            "checked": total,
            "failures": failures,
            "details": {
                "unexpected_effects": len(remaining),
                "total_actual": len(actual_effects),
            },
        }

    # ------------------------------------------------------------------
    # Combined
    # ------------------------------------------------------------------

    def combined_check(self, checks: list[dict[str, Any]]) -> dict[str, Any]:
        """Run multiple checks and return an aggregate result.

        Each element of *checks* should have:
        - ``"type"`` (str) – one of ``"database"``, ``"api_call_log"``,
          ``"file_system"``, ``"side_effects"``
        - Additional keys specific to the check type (passed through as kwargs)

        Returns an aggregate dict including per-check results and an overall
        ``passed`` flag and ``score``.
        """
        per_check_results: list[dict[str, Any]] = []
        all_passed = True
        total_score = 0.0

        for check in checks:
            check_type = check.get("type", "")
            result = self._dispatch_check(check_type, check)
            per_check_results.append({"type": check_type, **result})
            if not result.get("passed", False):
                all_passed = False
            total_score += float(result.get("score", 0.0))

        n = len(checks)
        aggregate_score = total_score / n if n > 0 else 1.0

        return {
            "passed": all_passed,
            "score": round(aggregate_score, 4),
            "total_checks": n,
            "checks": per_check_results,
            "all_failures": [
                f
                for r in per_check_results
                for f in r.get("failures", [])
            ],
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _dispatch_check(
        self,
        check_type: str,
        check: dict[str, Any],
    ) -> dict[str, Any]:
        """Route a check dict to the appropriate method."""
        if check_type == "database":
            return self.check_database_state(
                connection_info=check.get("connection_info", {}),
                expected_records=check.get("expected_records", []),
            )
        if check_type == "api_call_log":
            return self.check_api_call_log(
                log_entries=check.get("log_entries", []),
                expected_calls=check.get("expected_calls", []),
            )
        if check_type == "file_system":
            return self.check_file_system(
                paths=check.get("paths", []),
                expected_states=check.get("expected_states", []),
            )
        if check_type == "side_effects":
            return self.verify_side_effects(
                actual_effects=check.get("actual_effects", []),
                expected_effects=check.get("expected_effects", []),
            )
        return {
            "passed": False,
            "score": 0.0,
            "checked": 0,
            "failures": [{"issue": f"unknown_check_type: {check_type!r}"}],
            "details": {},
        }

    @staticmethod
    def _record_matches(
        record: dict[str, Any],
        expected_fields: dict[str, Any],
        operator: str,
    ) -> bool:
        """Return True when *record* satisfies all *expected_fields* assertions."""
        for field_name, expected_val in expected_fields.items():
            actual_val = record.get(field_name)
            if operator == "eq":
                if actual_val != expected_val:
                    return False
            elif operator == "contains":
                try:
                    if expected_val not in actual_val:  # type: ignore[operator]
                        return False
                except TypeError:
                    return False
            elif operator == "gt":
                try:
                    if not (actual_val > expected_val):  # type: ignore[operator]
                        return False
                except TypeError:
                    return False
            elif operator == "lt":
                try:
                    if not (actual_val < expected_val):  # type: ignore[operator]
                        return False
                except TypeError:
                    return False
            elif operator == "exists":
                if actual_val is None:
                    return False
            elif operator == "not_exists":
                if actual_val is not None:
                    return False
        return True

    @staticmethod
    def _api_call_matches(
        entry: dict[str, Any],
        endpoint: str,
        method: str,
        params: dict[str, Any],
        expected_status: Any,
    ) -> bool:
        """Return True when *entry* matches all specified API call criteria."""
        if entry.get("endpoint", "") != endpoint:
            return False
        if method and entry.get("method", "").upper() != method:
            return False
        if params:
            entry_params = entry.get("params") or {}
            if not EnvironmentChecker._is_subset(params, entry_params):
                return False
        if expected_status is not None:
            if str(entry.get("status", "")) != str(expected_status):
                return False
        return True

    @staticmethod
    def _check_single_path(
        path: str,
        expected: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Run file system assertions for a single path."""
        failures: list[dict[str, Any]] = []

        should_exist = expected.get("exists", True)
        path_exists = os.path.exists(path)

        if should_exist and not path_exists:
            failures.append({"path": path, "issue": "path_does_not_exist"})
            return failures  # remaining checks are meaningless

        if not should_exist and path_exists:
            failures.append({"path": path, "issue": "path_should_not_exist"})
            return failures

        if not path_exists:
            return failures  # expected to not exist, all good

        is_dir_expected = expected.get("is_dir")
        if is_dir_expected is not None:
            actual_is_dir = os.path.isdir(path)
            if actual_is_dir != is_dir_expected:
                failures.append({
                    "path": path,
                    "issue": "is_dir_mismatch",
                    "expected": is_dir_expected,
                    "actual": actual_is_dir,
                })

        min_size = expected.get("min_size")
        if min_size is not None:
            actual_size = os.path.getsize(path)
            if actual_size < int(min_size):
                failures.append({
                    "path": path,
                    "issue": "file_too_small",
                    "expected_min": min_size,
                    "actual_size": actual_size,
                })

        contains = expected.get("contains")
        if contains is not None and os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    content = fh.read()
                if contains not in content:
                    failures.append({
                        "path": path,
                        "issue": "content_not_found",
                        "expected_substring": contains,
                    })
            except OSError as exc:
                failures.append({
                    "path": path,
                    "issue": "read_error",
                    "error": str(exc),
                })

        return failures

    @staticmethod
    def _is_subset(subset: dict[str, Any], full: dict[str, Any]) -> bool:
        """Return True when all key/value pairs in *subset* are in *full*."""
        for key, val in subset.items():
            if full.get(key) != val:
                return False
        return True
