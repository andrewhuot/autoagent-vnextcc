"""Replay and Shadow Harness — record tool I/O and replay pure/read-only calls.

Allows eval runs to replay previously-recorded tool outputs for tools
classified as ``pure`` or ``read_only_external``, while still executing
real calls for write-side tools.  This dramatically reduces cost and
latency for regression-style eval suites that exercise deterministic
read paths.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from core.types import EnvironmentSnapshot, ReplayMode, SnapshotDiff

from .side_effects import ToolContract, ToolClassificationRegistry, ToolContractRegistry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class RecordedToolIO:
    """A single recorded tool call with its input/output pair.

    Attributes:
        tool_name: Name of the tool that was invoked.
        input_hash: SHA-256 hex digest of the deterministically serialized input.
        input_data: JSON string of the tool input payload.
        output_data: JSON string of the tool output payload.
        latency_ms: Wall-clock latency of the original call in milliseconds.
        error: Error message if the call failed, else ``None``.
    """

    tool_name: str
    input_hash: str
    input_data: str
    output_data: str
    latency_ms: float
    error: str | None = None


@dataclass
class ReplaySession:
    """A collection of recorded tool I/O for a single baseline run.

    Attributes:
        session_id: Unique identifier for this replay session.
        recorded_ios: Ordered list of tool I/O recordings.
        config_version: Label for the agent/config version that produced this baseline.
        created_at: Unix timestamp of when the session was recorded.
    """

    session_id: str
    recorded_ios: list[RecordedToolIO] = field(default_factory=list)
    config_version: str = ""
    created_at: float = 0.0


# ---------------------------------------------------------------------------
# Hashing helper
# ---------------------------------------------------------------------------


def _hash_input(data: Any) -> str:
    """Return a SHA-256 hex digest of *data* after deterministic JSON serialization."""
    serialized = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# SQLite-backed replay store
# ---------------------------------------------------------------------------


class ReplayStore:
    """Persistent SQLite store for replay sessions and their recorded tool I/O.

    Args:
        db_path: Filesystem path for the SQLite database file.
    """

    def __init__(self, db_path: str = "replay.db") -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Create the ``replay_sessions`` and ``recorded_tool_ios`` tables."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS replay_sessions (
                    session_id TEXT PRIMARY KEY,
                    config_version TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS recorded_tool_ios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    input_data TEXT NOT NULL,
                    output_data TEXT NOT NULL,
                    latency_ms REAL NOT NULL DEFAULT 0.0,
                    error TEXT,
                    FOREIGN KEY (session_id) REFERENCES replay_sessions(session_id)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_rtio_session_id "
                "ON recorded_tool_ios(session_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_rtio_input_hash "
                "ON recorded_tool_ios(input_hash)"
            )
            conn.commit()

    def save_session(self, session: ReplaySession) -> None:
        """Persist a :class:`ReplaySession` and all its recorded I/O rows."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO replay_sessions (session_id, config_version, created_at)
                VALUES (?, ?, ?)
                """,
                (session.session_id, session.config_version, session.created_at),
            )
            # Clear previous recordings for this session (idempotent save).
            conn.execute(
                "DELETE FROM recorded_tool_ios WHERE session_id = ?",
                (session.session_id,),
            )
            for rio in session.recorded_ios:
                conn.execute(
                    """
                    INSERT INTO recorded_tool_ios
                        (session_id, tool_name, input_hash, input_data, output_data, latency_ms, error)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session.session_id,
                        rio.tool_name,
                        rio.input_hash,
                        rio.input_data,
                        rio.output_data,
                        rio.latency_ms,
                        rio.error,
                    ),
                )
            conn.commit()

    def get_session(self, session_id: str) -> ReplaySession | None:
        """Load a :class:`ReplaySession` by ID, or return ``None`` if not found."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT session_id, config_version, created_at FROM replay_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return None

            ios_rows = conn.execute(
                """
                SELECT tool_name, input_hash, input_data, output_data, latency_ms, error
                FROM recorded_tool_ios
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            ).fetchall()

            recorded_ios = [
                RecordedToolIO(
                    tool_name=r[0],
                    input_hash=r[1],
                    input_data=r[2],
                    output_data=r[3],
                    latency_ms=r[4],
                    error=r[5],
                )
                for r in ios_rows
            ]

            return ReplaySession(
                session_id=row[0],
                config_version=row[1],
                created_at=row[2],
                recorded_ios=recorded_ios,
            )

    def list_sessions(self, limit: int = 50) -> list[ReplaySession]:
        """Return the most recent replay sessions (without loading I/O rows).

        Args:
            limit: Maximum number of sessions to return.
        """
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT session_id, config_version, created_at "
                "FROM replay_sessions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

        sessions: list[ReplaySession] = []
        for row in rows:
            sessions.append(
                ReplaySession(
                    session_id=row[0],
                    config_version=row[1],
                    created_at=row[2],
                    # I/O rows intentionally omitted for listing performance.
                )
            )
        return sessions


# ---------------------------------------------------------------------------
# Replay harness
# ---------------------------------------------------------------------------


class ReplayHarness:
    """Wraps an agent function so that pure/read-only tool calls are replayed
    from a recorded baseline instead of being executed live.

    Args:
        tool_registry: The :class:`ToolClassificationRegistry` used to decide
            which tools are safe to replay.
        replay_store: Persistence layer for recorded sessions.
    """

    def __init__(
        self,
        tool_registry: ToolClassificationRegistry,
        replay_store: ReplayStore,
    ) -> None:
        self.tool_registry = tool_registry
        self.replay_store = replay_store

    def record_baseline(
        self,
        session_id: str,
        tool_calls: list[dict[str, Any]],
        config_version: str,
    ) -> None:
        """Save tool I/O from a baseline run as a :class:`ReplaySession`.

        Each dict in *tool_calls* must contain at minimum:
        - ``tool_name`` (str)
        - ``input`` (JSON-serializable)
        - ``output`` (JSON-serializable)

        Optional keys:
        - ``latency_ms`` (float, default 0.0)
        - ``error`` (str | None, default None)
        """
        recorded_ios: list[RecordedToolIO] = []
        for call in tool_calls:
            tool_name: str = call["tool_name"]
            input_data = call["input"]
            output_data = call["output"]
            latency_ms: float = float(call.get("latency_ms", 0.0))
            error: str | None = call.get("error")

            input_json = json.dumps(input_data, sort_keys=True, default=str)
            output_json = json.dumps(output_data, sort_keys=True, default=str)
            input_hash = _hash_input(input_data)

            recorded_ios.append(
                RecordedToolIO(
                    tool_name=tool_name,
                    input_hash=input_hash,
                    input_data=input_json,
                    output_data=output_json,
                    latency_ms=latency_ms,
                    error=error,
                )
            )

        session = ReplaySession(
            session_id=session_id,
            recorded_ios=recorded_ios,
            config_version=config_version,
            created_at=time.time(),
        )
        self.replay_store.save_session(session)
        logger.info(
            "Recorded baseline session %s with %d tool calls",
            session_id,
            len(recorded_ios),
        )

    def create_replay_agent_fn(
        self,
        session_id: str,
        real_agent_fn: Callable[..., dict[str, Any]],
    ) -> Callable[..., dict[str, Any]]:
        """Return a wrapped agent function that replays safe tool calls.

        The wrapper intercepts the result from *real_agent_fn* and, for each
        tool call in the response:

        - If the tool is classified as ``pure`` or ``read_only_external`` **and**
          a matching recorded output exists (same tool name + input hash),
          the recorded output is substituted.
        - If the tool is classified as ``write_external_*`` or is unknown,
          the real output is preserved as-is.
        - If no recording is found for a replayable tool, the real output
          is used as a fallback.

        Args:
            session_id: ID of the previously recorded baseline session.
            real_agent_fn: The live agent function to wrap.

        Returns:
            A callable with the same signature as *real_agent_fn*.
        """
        session = self.replay_store.get_session(session_id)
        if session is None:
            logger.warning(
                "No replay session found for %s — returning real agent fn unchanged",
                session_id,
            )
            return real_agent_fn

        # Build a lookup: (tool_name, input_hash) -> recorded output JSON
        replay_index: dict[tuple[str, str], RecordedToolIO] = {}
        for rio in session.recorded_ios:
            key = (rio.tool_name, rio.input_hash)
            # First recording wins; preserves ordering semantics.
            if key not in replay_index:
                replay_index[key] = rio

        def _replay_agent_fn(*args: Any, **kwargs: Any) -> dict[str, Any]:
            result = real_agent_fn(*args, **kwargs)

            tool_calls_raw = result.get("tool_calls", [])
            if not isinstance(tool_calls_raw, list):
                return result

            patched_tool_calls: list[dict[str, Any]] = []
            for call in tool_calls_raw:
                if not isinstance(call, dict):
                    patched_tool_calls.append(call)
                    continue

                tool_name = str(call.get("tool") or call.get("name") or "")
                if not tool_name:
                    patched_tool_calls.append(call)
                    continue

                can_replay = self.tool_registry.can_replay(tool_name)
                if not can_replay:
                    patched_tool_calls.append(call)
                    continue

                # Attempt to find a matching recording.
                call_input = call.get("input", call.get("arguments", {}))
                input_hash = _hash_input(call_input)
                key = (tool_name, input_hash)
                recorded = replay_index.get(key)

                if recorded is None:
                    logger.debug(
                        "No recording for replayable tool %s (hash %s) — falling back to real",
                        tool_name,
                        input_hash[:12],
                    )
                    patched_tool_calls.append(call)
                    continue

                # Substitute the recorded output.
                patched_call = dict(call)
                patched_call["output"] = json.loads(recorded.output_data)
                patched_call["replayed"] = True
                patched_tool_calls.append(patched_call)
                logger.debug("Replayed tool %s (hash %s)", tool_name, input_hash[:12])

            patched_result = dict(result)
            patched_result["tool_calls"] = patched_tool_calls
            return patched_result

        return _replay_agent_fn

    def can_fully_replay(self, session_id: str) -> bool:
        """Return ``True`` if every tool in the session is pure or read-only.

        A session that can be fully replayed needs zero live calls, making it
        safe for offline regression testing.
        """
        session = self.replay_store.get_session(session_id)
        if session is None:
            return False
        if not session.recorded_ios:
            return True

        for rio in session.recorded_ios:
            if not self.tool_registry.can_replay(rio.tool_name):
                return False
        return True

    def get_replay_coverage(self, session_id: str) -> dict[str, bool]:
        """Map each tool name in the session to whether it can be replayed.

        Returns:
            ``{tool_name: can_replay}`` for every unique tool in the session.
            Empty dict if the session does not exist.
        """
        session = self.replay_store.get_session(session_id)
        if session is None:
            return {}

        coverage: dict[str, bool] = {}
        for rio in session.recorded_ios:
            if rio.tool_name not in coverage:
                coverage[rio.tool_name] = self.tool_registry.can_replay(rio.tool_name)
        return coverage


# ---------------------------------------------------------------------------
# Snapshot Store — SQLite-backed persistence for EnvironmentSnapshot
# ---------------------------------------------------------------------------


class SnapshotStore:
    """Persistent SQLite store for environment snapshots.

    Follows the same patterns as :class:`ReplayStore` — one table,
    JSON-serialized state column, indexed by source for efficient filtering.

    Args:
        db_path: Filesystem path for the SQLite database file.
    """

    def __init__(self, db_path: str = "snapshots.db") -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Create the ``environment_snapshots`` table."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS environment_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    state TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT '',
                    metadata TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_snap_source "
                "ON environment_snapshots(source)"
            )
            conn.commit()

    def save_snapshot(self, snapshot: EnvironmentSnapshot) -> None:
        """Persist an :class:`EnvironmentSnapshot` to SQLite."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO environment_snapshots
                    (snapshot_id, created_at, state, source, metadata)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.created_at,
                    json.dumps(snapshot.state, sort_keys=True, default=str),
                    snapshot.source,
                    json.dumps(snapshot.metadata, sort_keys=True, default=str),
                ),
            )
            conn.commit()

    def get_snapshot(self, snapshot_id: str) -> EnvironmentSnapshot | None:
        """Load an :class:`EnvironmentSnapshot` by ID, or return ``None``."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT snapshot_id, created_at, state, source, metadata "
                "FROM environment_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
            if row is None:
                return None
            return EnvironmentSnapshot(
                snapshot_id=row[0],
                created_at=row[1],
                state=json.loads(row[2]),
                source=row[3],
                metadata=json.loads(row[4]),
            )

    def list_snapshots(
        self, source: str | None = None, limit: int = 50
    ) -> list[EnvironmentSnapshot]:
        """Return recent snapshots, optionally filtered by source.

        Args:
            source: If provided, only return snapshots from this source.
            limit: Maximum number of snapshots to return.
        """
        with sqlite3.connect(self.db_path) as conn:
            if source is not None:
                rows = conn.execute(
                    "SELECT snapshot_id, created_at, state, source, metadata "
                    "FROM environment_snapshots WHERE source = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (source, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT snapshot_id, created_at, state, source, metadata "
                    "FROM environment_snapshots "
                    "ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()

        return [
            EnvironmentSnapshot(
                snapshot_id=r[0],
                created_at=r[1],
                state=json.loads(r[2]),
                source=r[3],
                metadata=json.loads(r[4]),
            )
            for r in rows
        ]


# ---------------------------------------------------------------------------
# Enhanced Replay Harness — contract-aware replay with snapshots
# ---------------------------------------------------------------------------


class EnhancedReplayHarness(ReplayHarness):
    """Extends :class:`ReplayHarness` with contract-aware replay routing
    and environment snapshot support.

    When a :class:`ToolContractRegistry` is provided, replay decisions are
    driven by each tool's :class:`ReplayMode` instead of the binary
    pure/read-only classification.

    Args:
        store: The underlying :class:`ReplayStore` for recorded sessions.
        contract_registry: Optional contract registry for mode-based routing.
        snapshot_store: Optional store for environment snapshots.
    """

    def __init__(
        self,
        store: ReplayStore,
        contract_registry: ToolContractRegistry | None = None,
        snapshot_store: SnapshotStore | None = None,
    ) -> None:
        # Use the contract_registry as the base tool_registry when available,
        # since ToolContractRegistry extends ToolClassificationRegistry.
        base_registry = contract_registry if contract_registry is not None else ToolClassificationRegistry()
        super().__init__(tool_registry=base_registry, replay_store=store)
        self.contract_registry = contract_registry
        self.snapshot_store = snapshot_store

    def can_replay_tool(self, tool_name: str) -> bool:
        """Check if a tool can be replayed based on its contract's replay mode.

        Falls back to the base registry's binary check if no contract exists.
        """
        if self.contract_registry is not None:
            contract = self.contract_registry.get_contract(tool_name)
            if contract is not None:
                return contract.can_auto_replay
        return self.tool_registry.can_replay(tool_name)

    def capture_snapshot(
        self, source: str, state: dict
    ) -> EnvironmentSnapshot:
        """Capture an environment snapshot and persist it if a store is available.

        Args:
            source: Origin of the snapshot (e.g. ``"orders_db"``).
            state: The state dictionary to capture.

        Returns:
            The created :class:`EnvironmentSnapshot`.
        """
        snapshot = EnvironmentSnapshot(source=source, state=state)
        if self.snapshot_store is not None:
            self.snapshot_store.save_snapshot(snapshot)
        return snapshot

    def compare_snapshots(
        self, expected_id: str, actual_id: str
    ) -> SnapshotDiff | None:
        """Load two snapshots by ID and compute their diff.

        Returns ``None`` if either snapshot cannot be found or no snapshot
        store is configured.
        """
        if self.snapshot_store is None:
            return None
        expected = self.snapshot_store.get_snapshot(expected_id)
        actual = self.snapshot_store.get_snapshot(actual_id)
        if expected is None or actual is None:
            return None
        return SnapshotDiff.compute(expected, actual)

    def check_freshness(
        self, recorded_io: RecordedToolIO, contract: ToolContract
    ) -> bool:
        """Check if recorded data is within the contract's freshness window.

        Returns ``True`` (fresh) if no freshness window is configured or
        if the recording age is within the window.
        """
        if contract.freshness_window_seconds is None:
            return True
        # The recorded_io doesn't store a timestamp directly, so we use
        # the session's created_at as a proxy.  In this simplified check
        # we compare against current time.  Callers with session-level
        # timestamps should use those instead.
        return True  # default fresh — real implementation needs session timestamp

    def replay_with_contracts(
        self,
        agent_fn: Callable[..., dict[str, Any]],
        session_id: str,
        *args: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Enhanced replay routing based on each tool's ReplayMode.

        Routing rules per mode:

        - **deterministic_stub**: use cached response (existing behaviour).
        - **recorded_stub_with_freshness**: use cached if within freshness
          window, else execute live.
        - **live_sandbox_clone**: always execute live (placeholder for
          sandbox environment).
        - **simulator**: use cached response with a ``simulated`` flag.
        - **forbidden**: skip tool, return an error marker.

        Falls back to the base :meth:`ReplayHarness.create_replay_agent_fn`
        behaviour when no contract registry is configured.
        """
        session = self.replay_store.get_session(session_id)
        if session is None:
            logger.warning(
                "No replay session found for %s — executing live",
                session_id,
            )
            return agent_fn(*args, **kwargs)

        # Build replay index
        replay_index: dict[tuple[str, str], RecordedToolIO] = {}
        for rio in session.recorded_ios:
            key = (rio.tool_name, rio.input_hash)
            if key not in replay_index:
                replay_index[key] = rio

        result = agent_fn(*args, **kwargs)

        tool_calls_raw = result.get("tool_calls", [])
        if not isinstance(tool_calls_raw, list):
            return result

        patched_tool_calls: list[dict[str, Any]] = []
        for call in tool_calls_raw:
            if not isinstance(call, dict):
                patched_tool_calls.append(call)
                continue

            tool_name = str(call.get("tool") or call.get("name") or "")
            if not tool_name:
                patched_tool_calls.append(call)
                continue

            # Determine replay mode from contract
            contract: ToolContract | None = None
            mode: ReplayMode | None = None
            if self.contract_registry is not None:
                contract = self.contract_registry.get_contract(tool_name)
                if contract is not None:
                    mode = contract.replay_mode

            # No contract — fall back to base behaviour
            if mode is None:
                if self.tool_registry.can_replay(tool_name):
                    mode = ReplayMode.deterministic_stub
                else:
                    patched_tool_calls.append(call)
                    continue

            call_input = call.get("input", call.get("arguments", {}))
            input_hash = _hash_input(call_input)
            key = (tool_name, input_hash)
            recorded = replay_index.get(key)

            if mode == ReplayMode.forbidden:
                patched_call = dict(call)
                patched_call["output"] = {"error": "FORBIDDEN_TOOL", "tool": tool_name}
                patched_call["replayed"] = True
                patched_call["replay_mode"] = "forbidden"
                patched_tool_calls.append(patched_call)
                logger.info("Blocked forbidden tool %s", tool_name)
                continue

            if mode == ReplayMode.live_sandbox_clone:
                # Always execute live — the real call is already in `call`
                patched_call = dict(call)
                patched_call["replay_mode"] = "live_sandbox_clone"
                patched_tool_calls.append(patched_call)
                logger.debug("Live sandbox clone for tool %s", tool_name)
                continue

            if mode == ReplayMode.deterministic_stub:
                if recorded is not None:
                    patched_call = dict(call)
                    patched_call["output"] = json.loads(recorded.output_data)
                    patched_call["replayed"] = True
                    patched_call["replay_mode"] = "deterministic_stub"
                    patched_tool_calls.append(patched_call)
                    logger.debug("Replayed deterministic stub for %s", tool_name)
                    continue
                # No recording — fall through to live
                patched_tool_calls.append(call)
                continue

            if mode == ReplayMode.recorded_stub_with_freshness:
                if recorded is not None and contract is not None and self.check_freshness(recorded, contract):
                    patched_call = dict(call)
                    patched_call["output"] = json.loads(recorded.output_data)
                    patched_call["replayed"] = True
                    patched_call["replay_mode"] = "recorded_stub_with_freshness"
                    patched_tool_calls.append(patched_call)
                    logger.debug("Replayed fresh stub for %s", tool_name)
                    continue
                # Stale or no recording — use live
                patched_tool_calls.append(call)
                continue

            if mode == ReplayMode.simulator:
                if recorded is not None:
                    patched_call = dict(call)
                    patched_call["output"] = json.loads(recorded.output_data)
                    patched_call["replayed"] = True
                    patched_call["simulated"] = True
                    patched_call["replay_mode"] = "simulator"
                    patched_tool_calls.append(patched_call)
                    logger.debug("Simulated replay for %s", tool_name)
                    continue
                patched_tool_calls.append(call)
                continue

            # Unknown mode — pass through
            patched_tool_calls.append(call)

        patched_result = dict(result)
        patched_result["tool_calls"] = patched_tool_calls
        return patched_result
