"""MCP Resources — read-only data exposed to AI coding assistants.

Resources are identified by URI and provide structured data about agent
configurations, traces, eval results, skills, and datasets.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class McpResource:
    """A single MCP resource (read-only data identified by URI)."""
    uri: str
    name: str
    description: str
    mime_type: str = "application/json"

    def to_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "name": self.name,
            "description": self.description,
            "mimeType": self.mime_type,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "McpResource":
        return cls(
            uri=d["uri"],
            name=d["name"],
            description=d["description"],
            mime_type=d.get("mimeType", d.get("mime_type", "application/json")),
        )


class ResourceProvider:
    """Provides MCP resources for the AutoAgent system."""

    CONFIGS_DIR = os.environ.get("AUTOAGENT_CONFIGS", "configs")
    DB_PATH = os.environ.get("AUTOAGENT_DB", "conversations.db")
    MEMORY_DB = os.environ.get("AUTOAGENT_MEMORY_DB", "optimizer_memory.db")

    # ------------------------------------------------------------------
    # Resource list methods
    # ------------------------------------------------------------------

    def get_agent_configs(self) -> list[McpResource]:
        """Return resources for all agent configurations."""
        resources: list[McpResource] = []
        configs_dir = self.CONFIGS_DIR
        try:
            if os.path.isdir(configs_dir):
                for fname in sorted(os.listdir(configs_dir)):
                    if fname.endswith((".yaml", ".yml", ".json")):
                        resources.append(McpResource(
                            uri=f"autoagent://configs/{fname}",
                            name=fname,
                            description=f"Agent configuration file: {fname}",
                            mime_type="application/yaml" if fname.endswith((".yaml", ".yml")) else "application/json",
                        ))
        except OSError:
            pass
        if not resources:
            resources.append(McpResource(
                uri="autoagent://configs/active",
                name="active_config",
                description="Currently active agent configuration",
            ))
        return resources

    def get_trace_summaries(self, limit: int = 20) -> list[McpResource]:
        """Return resources for recent conversation traces."""
        resources: list[McpResource] = []
        try:
            from logger.store import ConversationStore
            store = ConversationStore(db_path=self.DB_PATH)
            records = store.get_failures(limit=limit)
            for r in records:
                cid = getattr(r, "conversation_id", "unknown")
                resources.append(McpResource(
                    uri=f"autoagent://traces/{cid}",
                    name=f"trace_{cid}",
                    description=f"Conversation trace {cid} — outcome: {getattr(r, 'outcome', 'unknown')}",
                ))
        except Exception:
            pass
        if not resources:
            resources.append(McpResource(
                uri="autoagent://traces/recent",
                name="recent_traces",
                description=f"Most recent {limit} conversation traces",
            ))
        return resources

    def get_eval_results(self, run_id: str | None = None) -> list[McpResource]:
        """Return resources for eval run results."""
        resources: list[McpResource] = []
        try:
            from optimizer.memory import OptimizationMemory
            memory = OptimizationMemory(db_path=self.MEMORY_DB)
            attempts = memory.recent(limit=20)
            for i, attempt in enumerate(attempts):
                rid = getattr(attempt, "run_id", None) or f"run_{i}"
                if run_id and rid != run_id:
                    continue
                resources.append(McpResource(
                    uri=f"autoagent://evals/{rid}",
                    name=f"eval_{rid}",
                    description=(
                        f"Eval run {rid} — score: {getattr(attempt, 'score_after', 'n/a')}, "
                        f"status: {getattr(attempt, 'status', 'unknown')}"
                    ),
                ))
        except Exception:
            pass
        if not resources:
            uri = f"autoagent://evals/{run_id}" if run_id else "autoagent://evals/latest"
            resources.append(McpResource(
                uri=uri,
                name="eval_results",
                description="Latest eval run results",
            ))
        return resources

    def get_skill_catalog(self) -> list[McpResource]:
        """Return resources for all available skills."""
        resources: list[McpResource] = []
        try:
            from registry.skill_store import SkillStore
            store = SkillStore(db_path=os.environ.get("AUTOAGENT_REGISTRY_DB", "registry.db"))
            skills = store.recommend()
            for skill in skills:
                resources.append(McpResource(
                    uri=f"autoagent://skills/{skill.name}",
                    name=skill.name,
                    description=getattr(skill, "description", f"Skill: {skill.name}"),
                ))
            store.close()
        except Exception:
            pass
        if not resources:
            resources.append(McpResource(
                uri="autoagent://skills/catalog",
                name="skill_catalog",
                description="Full catalog of available agent skills",
            ))
        return resources

    def get_dataset_stats(self) -> list[McpResource]:
        """Return resources for dataset statistics."""
        resources = [
            McpResource(
                uri="autoagent://datasets/eval_cases",
                name="eval_cases_stats",
                description="Statistics for the eval case dataset",
            ),
            McpResource(
                uri="autoagent://datasets/conversations",
                name="conversation_stats",
                description="Statistics for the conversation/trace dataset",
            ),
            McpResource(
                uri="autoagent://datasets/failure_clusters",
                name="failure_clusters_stats",
                description="Statistics for failure cluster dataset",
            ),
        ]
        return resources

    # ------------------------------------------------------------------
    # Resource read method
    # ------------------------------------------------------------------

    def read_resource(self, uri: str) -> dict[str, Any]:
        """Read the content of a resource by URI."""
        if uri == "autoagent://configs/active":
            return self._read_active_config()
        if uri.startswith("autoagent://configs/"):
            fname = uri.removeprefix("autoagent://configs/")
            return self._read_config_file(fname)
        if uri.startswith("autoagent://traces/"):
            trace_id = uri.removeprefix("autoagent://traces/")
            return self._read_trace(trace_id)
        if uri.startswith("autoagent://evals/"):
            run_id = uri.removeprefix("autoagent://evals/")
            return self._read_eval(run_id)
        if uri.startswith("autoagent://skills/"):
            skill_name = uri.removeprefix("autoagent://skills/")
            return self._read_skill(skill_name)
        if uri.startswith("autoagent://datasets/"):
            dataset = uri.removeprefix("autoagent://datasets/")
            return self._read_dataset_stats(dataset)
        return {"error": f"Unknown resource URI: {uri}"}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _read_active_config(self) -> dict[str, Any]:
        try:
            from deployer.canary import Deployer
            from logger.store import ConversationStore
            store = ConversationStore(db_path=self.DB_PATH)
            deployer = Deployer(configs_dir=self.CONFIGS_DIR, store=store)
            config = deployer.get_active_config() or {}
            return {"source": "active", "config": config}
        except Exception as exc:
            return {"error": str(exc)}

    def _read_config_file(self, fname: str) -> dict[str, Any]:
        path = os.path.join(self.CONFIGS_DIR, fname)
        try:
            with open(path) as f:
                if fname.endswith(".json"):
                    return json.load(f)
                import yaml  # type: ignore[import]
                return yaml.safe_load(f) or {}
        except Exception as exc:
            return {"error": str(exc)}

    def _read_trace(self, trace_id: str) -> dict[str, Any]:
        if trace_id == "recent":
            try:
                from logger.store import ConversationStore
                store = ConversationStore(db_path=self.DB_PATH)
                records = store.get_failures(limit=20)
                return {
                    "traces": [
                        {
                            "conversation_id": getattr(r, "conversation_id", ""),
                            "user_message": getattr(r, "user_message", ""),
                            "outcome": getattr(r, "outcome", ""),
                            "error_message": getattr(r, "error_message", ""),
                        }
                        for r in records
                    ]
                }
            except Exception as exc:
                return {"error": str(exc)}
        return {"trace_id": trace_id, "note": "Individual trace lookup not yet implemented"}

    def _read_eval(self, run_id: str) -> dict[str, Any]:
        try:
            from optimizer.memory import OptimizationMemory
            memory = OptimizationMemory(db_path=self.MEMORY_DB)
            attempts = memory.recent(limit=50)
            for attempt in attempts:
                if getattr(attempt, "run_id", None) == run_id:
                    return {
                        "run_id": run_id,
                        "score_before": attempt.score_before,
                        "score_after": attempt.score_after,
                        "status": attempt.status,
                        "change_description": attempt.change_description,
                        "timestamp": attempt.timestamp,
                    }
            if run_id == "latest" and attempts:
                a = attempts[0]
                return {
                    "run_id": "latest",
                    "score_before": a.score_before,
                    "score_after": a.score_after,
                    "status": a.status,
                    "change_description": a.change_description,
                    "timestamp": a.timestamp,
                }
        except Exception as exc:
            return {"error": str(exc)}
        return {"run_id": run_id, "error": "Not found"}

    def _read_skill(self, skill_name: str) -> dict[str, Any]:
        if skill_name == "catalog":
            try:
                from registry.skill_store import SkillStore
                store = SkillStore(db_path=os.environ.get("AUTOAGENT_REGISTRY_DB", "registry.db"))
                skills = store.recommend()
                result = [
                    {
                        "name": s.name,
                        "category": getattr(s, "category", ""),
                        "description": getattr(s, "description", ""),
                    }
                    for s in skills
                ]
                store.close()
                return {"skills": result}
            except Exception as exc:
                return {"error": str(exc)}
        return {"skill_name": skill_name, "note": "Per-skill detail lookup not yet implemented"}

    def _read_dataset_stats(self, dataset: str) -> dict[str, Any]:
        if dataset == "conversations":
            try:
                from logger.store import ConversationStore
                store = ConversationStore(db_path=self.DB_PATH)
                return {"dataset": "conversations", "count": store.count()}
            except Exception as exc:
                return {"error": str(exc)}
        if dataset == "eval_cases":
            try:
                from evals.runner import EvalRunner
                from agent.config.runtime import load_runtime_config
                runtime = load_runtime_config()
                runner = EvalRunner(
                    history_db_path=runtime.eval.history_db_path,
                    cache_enabled=runtime.eval.cache_enabled,
                    cache_db_path=runtime.eval.cache_db_path,
                    dataset_strict_integrity=runtime.eval.dataset_strict_integrity,
                    random_seed=runtime.eval.random_seed,
                    token_cost_per_1k=runtime.eval.token_cost_per_1k,
                )
                cases = getattr(runner, "dataset", None)
                count = len(cases) if cases is not None else "unknown"
                return {"dataset": "eval_cases", "count": count}
            except Exception as exc:
                return {"error": str(exc)}
        return {"dataset": dataset, "note": "Stats not yet implemented for this dataset"}
