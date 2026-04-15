"""End-to-end test: workspace config + credentials → live LLM worker.

This test is the "canary": if it ever starts returning deterministic
stubs again when a workspace is fully configured, the regression that
prompted this whole change has returned.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from builder.coordinator_runtime import CoordinatorWorkerRuntime
from builder.events import EventBroker
from builder.llm_worker import LLMWorkerAdapter
from builder.orchestrator import BuilderOrchestrator
from builder.store import BuilderStore
from builder.worker_adapters import DeterministicWorkerAdapter
from builder.worker_mode import WorkerMode


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "AGENTLAB_WORKER_MODE",
    ):
        monkeypatch.delenv(name, raising=False)


def test_golden_path_config_and_creds_yields_llm_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", "ai-key")
    config = {
        "harness": {
            "models": {
                "worker": {
                    "provider": "google",
                    "model": "gemini-2.5-pro",
                    "api_key_env": "GOOGLE_API_KEY",
                }
            }
        }
    }
    (tmp_path / "agentlab.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    store = BuilderStore(db_path=str(tmp_path / "builder.db"))
    runtime = CoordinatorWorkerRuntime(
        store=store,
        orchestrator=BuilderOrchestrator(store=store),
        events=EventBroker(),
    )

    assert runtime.worker_mode is WorkerMode.LLM
    assert runtime.worker_mode_degraded_reason is None
    # Peek at the actual adapter to confirm it's not the deterministic stub.
    default_adapter = runtime._default_worker_adapter  # noqa: SLF001 - intentional peek
    assert isinstance(default_adapter, LLMWorkerAdapter)
    assert not isinstance(default_adapter, DeterministicWorkerAdapter)
