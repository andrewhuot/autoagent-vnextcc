"""AutoAgent MCP tool implementations.

Each tool function takes keyword arguments and returns a dict result.
These functions are standalone — they create their own stores/components
so the MCP server is self-contained.
"""
from __future__ import annotations
import os
from typing import Any

# Lazy imports to avoid circular dependencies
DB_PATH = os.environ.get("AUTOAGENT_DB", "conversations.db")
CONFIGS_DIR = os.environ.get("AUTOAGENT_CONFIGS", "configs")
MEMORY_DB = os.environ.get("AUTOAGENT_MEMORY_DB", "optimizer_memory.db")


def autoagent_status(**kwargs: Any) -> dict[str, Any]:
    """Get current agent health, scores, and failure summary."""
    from logger.store import ConversationStore
    from observer import Observer
    from deployer.canary import Deployer
    from optimizer.memory import OptimizationMemory

    store = ConversationStore(db_path=DB_PATH)
    observer = Observer(store)
    deployer = Deployer(configs_dir=CONFIGS_DIR, store=store)
    memory = OptimizationMemory(db_path=MEMORY_DB)

    report = observer.observe()
    metrics = report.metrics
    dep_status = deployer.status()
    attempts = memory.recent(limit=1)

    return {
        "config_version": dep_status.get("active_version"),
        "conversations": store.count(),
        "eval_score": attempts[0].score_after if attempts else None,
        "safety_violation_rate": metrics.safety_violation_rate,
        "success_rate": metrics.success_rate,
        "avg_latency_ms": metrics.avg_latency_ms,
        "failure_buckets": report.failure_buckets,
    }


def autoagent_explain(**kwargs: Any) -> dict[str, Any]:
    """Get a plain-English summary of the agent's current state."""
    from logger.store import ConversationStore
    from observer import Observer

    store = ConversationStore(db_path=DB_PATH)
    observer = Observer(store)
    report = observer.observe()
    metrics = report.metrics

    sr = metrics.success_rate
    if sr >= 0.9:
        health = "Excellent"
    elif sr >= 0.75:
        health = "Good"
    elif sr >= 0.5:
        health = "Needs Work"
    else:
        health = "Critical"

    buckets = report.failure_buckets or {}
    top = max(buckets, key=buckets.get) if buckets else None

    return {
        "health": health,
        "success_rate": sr,
        "top_failure": top,
        "failure_buckets": buckets,
        "summary": f"Agent health is {health} ({sr:.0%} success rate). Top failure: {top or 'none'}.",
    }


def autoagent_diagnose(**kwargs: Any) -> dict[str, Any]:
    """Run failure analysis and return clustered issues."""
    from optimizer.diagnose_session import DiagnoseSession
    session = DiagnoseSession()
    session.start()
    return session.to_dict()


def autoagent_get_failures(failure_family: str = "", limit: int = 5, **kwargs: Any) -> list[dict]:
    """Get sample conversations for a specific failure type."""
    from logger.store import ConversationStore
    store = ConversationStore(db_path=DB_PATH)
    records = store.get_failures(limit=limit)
    return [
        {
            "conversation_id": getattr(r, 'conversation_id', ''),
            "user_message": r.user_message,
            "outcome": r.outcome,
            "error_message": r.error_message,
        }
        for r in records
        if not failure_family or failure_family in (r.error_message or "")
    ][:limit]


def autoagent_suggest_fix(description: str = "", **kwargs: Any) -> dict[str, Any]:
    """Suggest a config fix based on NL description."""
    from optimizer.nl_editor import NLEditor
    editor = NLEditor()
    config = {}
    try:
        from deployer.canary import Deployer
        from logger.store import ConversationStore
        store = ConversationStore(db_path=DB_PATH)
        deployer = Deployer(configs_dir=CONFIGS_DIR, store=store)
        config = deployer.get_active_config() or {}
    except Exception:
        pass
    result = editor.apply_and_eval(description, config)
    return result.to_dict()


def autoagent_edit(description: str = "", auto_apply: bool = False, **kwargs: Any) -> dict[str, Any]:
    """Apply a natural language edit to the agent config."""
    from optimizer.nl_editor import NLEditor
    editor = NLEditor()
    config = {}
    try:
        from deployer.canary import Deployer
        from logger.store import ConversationStore
        store = ConversationStore(db_path=DB_PATH)
        deployer = Deployer(configs_dir=CONFIGS_DIR, store=store)
        config = deployer.get_active_config() or {}
    except Exception:
        pass
    result = editor.apply_and_eval(description, config)
    return result.to_dict()


def autoagent_eval(config_path: str | None = None, **kwargs: Any) -> dict[str, Any]:
    """Run eval suite and return scores."""
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
    config = None
    if config_path:
        import yaml
        with open(config_path) as f:
            config = yaml.safe_load(f)
    score = runner.run(config=config)
    return {
        "quality": score.quality,
        "safety": score.safety,
        "latency": score.latency,
        "cost": score.cost,
        "composite": score.composite,
        "passed_cases": score.passed_cases,
        "total_cases": score.total_cases,
    }


def autoagent_eval_compare(config_a: str = "", config_b: str = "", **kwargs: Any) -> dict[str, Any]:
    """Compare two configs via eval."""
    from evals.runner import EvalRunner
    from agent.config.runtime import load_runtime_config
    import yaml
    runtime = load_runtime_config()
    runner = EvalRunner(
        history_db_path=runtime.eval.history_db_path,
        cache_enabled=runtime.eval.cache_enabled,
        cache_db_path=runtime.eval.cache_db_path,
        dataset_strict_integrity=runtime.eval.dataset_strict_integrity,
        random_seed=runtime.eval.random_seed,
        token_cost_per_1k=runtime.eval.token_cost_per_1k,
    )

    with open(config_a) as f:
        ca = yaml.safe_load(f)
    with open(config_b) as f:
        cb = yaml.safe_load(f)

    score_a = runner.run(config=ca)
    score_b = runner.run(config=cb)
    winner = "a" if score_a.composite >= score_b.composite else "b"
    return {
        "config_a_score": score_a.composite,
        "config_b_score": score_b.composite,
        "winner": winner,
        "delta": abs(score_a.composite - score_b.composite),
    }


def autoagent_skill_gaps(**kwargs: Any) -> list[dict]:
    """Identify capabilities the agent is missing."""
    try:
        from agent_skills.gap_analyzer import GapAnalyzer
        analyzer = GapAnalyzer()
        gaps = analyzer.analyze(blame_clusters=[], opportunities=[])
        return [{"description": g.description, "priority": g.priority} for g in gaps]
    except Exception:
        return []


def autoagent_skill_recommend(**kwargs: Any) -> list[dict]:
    """Recommend optimization skills."""
    try:
        from registry.skill_store import SkillStore
        store = SkillStore(db_path=os.environ.get("AUTOAGENT_REGISTRY_DB", "registry.db"))
        skills = store.recommend()
        result = [
            {"name": s.name, "category": s.category, "description": s.description}
            for s in skills
        ]
        store.close()
        return result
    except Exception:
        return []


def autoagent_replay(limit: int = 10, **kwargs: Any) -> list[dict]:
    """Get optimization history."""
    from optimizer.memory import OptimizationMemory
    memory = OptimizationMemory(db_path=MEMORY_DB)
    attempts = memory.recent(limit=limit)
    return [
        {
            "version": i + 1,
            "score_before": a.score_before,
            "score_after": a.score_after,
            "status": a.status,
            "change_description": a.change_description,
            "timestamp": a.timestamp,
        }
        for i, a in enumerate(reversed(attempts))
    ]


def autoagent_diff(version_a: int = 0, version_b: int = 0, **kwargs: Any) -> str:
    """Get diff between two config versions."""
    try:
        from deployer.versioning import ConfigVersionManager
        vm = ConfigVersionManager(configs_dir=CONFIGS_DIR)
        config_a = vm.load_version(version_a)
        config_b = vm.load_version(version_b)
        if config_a and config_b:
            from agent.config.schema import validate_config, config_diff
            va = validate_config(config_a)
            vb = validate_config(config_b)
            return config_diff(va, vb)
    except Exception:
        pass
    return "Could not compute diff."


# ---------------------------------------------------------------------------
# Build Surface tools (P0-10)
# ---------------------------------------------------------------------------

def scaffold_agent(
    name: str = "",
    agent_type: str = "specialist",
    description: str = "",
    output_dir: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
    """Scaffold a new ADK agent project with boilerplate files."""
    import textwrap
    agent_name = name or "my_agent"
    out_dir = output_dir or os.path.join(CONFIGS_DIR, agent_name)

    try:
        os.makedirs(out_dir, exist_ok=True)

        # Minimal agent config
        config = {
            "name": agent_name,
            "type": agent_type,
            "description": description or f"Agent: {agent_name}",
            "instructions": f"You are {agent_name}, a {agent_type} agent.",
            "tools": [],
            "guardrails": [],
        }

        config_path = os.path.join(out_dir, "config.yaml")
        try:
            import yaml
            with open(config_path, "w") as f:
                yaml.safe_dump(config, f, default_flow_style=False)
        except ImportError:
            import json as _json
            config_path = os.path.join(out_dir, "config.json")
            with open(config_path, "w") as f:
                _json.dump(config, f, indent=2)

        # Minimal README
        readme_path = os.path.join(out_dir, "README.md")
        readme = textwrap.dedent(f"""\
            # {agent_name}

            {description or 'An AutoAgent specialist.'}

            ## Type
            {agent_type}

            ## Getting started
            Edit `config.yaml` to customise instructions and tools.
        """)
        with open(readme_path, "w") as f:
            f.write(readme)

        return {
            "status": "created",
            "agent_name": agent_name,
            "output_dir": out_dir,
            "files_created": [config_path, readme_path],
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def generate_evals(
    agent_name: str = "",
    capability: str = "",
    num_cases: int = 10,
    include_adversarial: bool = False,
    output_path: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
    """Generate an eval pack (YAML test cases) for an agent capability."""
    import json as _json

    cases = []
    for i in range(1, num_cases + 1):
        cases.append({
            "case_id": f"{agent_name or 'agent'}_eval_{i:03d}",
            "task": f"[TODO] Happy-path test {i} for capability: {capability}",
            "category": capability or "general",
            "suite_type": "capability",
            "expected_behavior": "[TODO] Describe expected behaviour",
            "expected_keywords": [],
            "safety_probe": False,
        })

    if include_adversarial:
        for i in range(1, 4):
            cases.append({
                "case_id": f"{agent_name or 'agent'}_adversarial_{i:03d}",
                "task": f"[TODO] Adversarial test {i} for capability: {capability}",
                "category": capability or "general",
                "suite_type": "adversarial",
                "expected_behavior": "[TODO] Describe expected safe / correct behaviour",
                "expected_keywords": [],
                "safety_probe": True,
            })

    out_path = output_path or os.path.join(CONFIGS_DIR, f"{agent_name or 'agent'}_evals.json")
    try:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "w") as f:
            _json.dump({"cases": cases}, f, indent=2)
        saved = True
    except Exception:
        saved = False

    return {
        "agent_name": agent_name,
        "capability": capability,
        "num_cases_generated": len(cases),
        "output_path": out_path if saved else None,
        "cases": cases,
    }


def run_sandbox(
    agent_name: str = "",
    task: str = "",
    config_path: str = "",
    timeout_seconds: int = 30,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run an agent task in an isolated sandbox and return the result."""
    try:
        from agent.config.runtime import load_runtime_config
        runtime = load_runtime_config()
        sandbox_cfg = getattr(runtime, "sandbox", None)
        sandbox_enabled = getattr(sandbox_cfg, "enabled", False) if sandbox_cfg else False

        # Load config if provided
        agent_config: dict[str, Any] = {}
        if config_path and os.path.isfile(config_path):
            try:
                import yaml
                with open(config_path) as f:
                    agent_config = yaml.safe_load(f) or {}
            except Exception:
                import json as _json
                with open(config_path) as f:
                    agent_config = _json.load(f)

        return {
            "agent_name": agent_name,
            "task": task,
            "sandbox_enabled": sandbox_enabled,
            "status": "sandbox_run_stub",
            "note": (
                "Sandbox execution requires a live agent runtime. "
                "Connect an ADK runtime to enable real sandbox runs."
            ),
            "config_loaded": bool(agent_config),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def inspect_trace(
    trace_id: str = "",
    limit: int = 1,
    **kwargs: Any,
) -> dict[str, Any]:
    """Inspect a specific conversation trace by ID."""
    try:
        from logger.store import ConversationStore
        store = ConversationStore(db_path=DB_PATH)
        if trace_id:
            record = store.get(trace_id) if hasattr(store, "get") else None
            if record:
                return {
                    "trace_id": trace_id,
                    "user_message": getattr(record, "user_message", ""),
                    "agent_response": getattr(record, "agent_response", ""),
                    "outcome": getattr(record, "outcome", ""),
                    "error_message": getattr(record, "error_message", ""),
                    "metadata": getattr(record, "metadata", {}),
                }
        # Fall back to recent failures
        records = store.get_failures(limit=limit)
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


def sync_adk_source(
    source_dir: str = "",
    target_dir: str = "",
    dry_run: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """Sync local agent changes back to the ADK source tree."""
    import shutil

    src = source_dir or CONFIGS_DIR
    dst = target_dir or CONFIGS_DIR

    if src == dst:
        return {"status": "noop", "message": "Source and target directories are the same."}

    if not os.path.isdir(src):
        return {"status": "error", "error": f"Source directory not found: {src}"}

    synced: list[str] = []
    errors: list[str] = []

    for fname in os.listdir(src):
        src_path = os.path.join(src, fname)
        dst_path = os.path.join(dst, fname)
        if dry_run:
            synced.append(f"[dry-run] {src_path} -> {dst_path}")
        else:
            try:
                os.makedirs(dst, exist_ok=True)
                shutil.copy2(src_path, dst_path)
                synced.append(dst_path)
            except Exception as exc:
                errors.append(f"{fname}: {exc}")

    return {
        "status": "ok" if not errors else "partial",
        "dry_run": dry_run,
        "synced": synced,
        "errors": errors,
    }


def open_pr(
    branch_name: str = "",
    title: str = "",
    body: str = "",
    base_branch: str = "main",
    **kwargs: Any,
) -> dict[str, Any]:
    """Create a git branch and open a pull request for pending changes."""
    import subprocess

    branch = branch_name or "autoagent/auto-improvement"
    results: dict[str, Any] = {"branch": branch, "base": base_branch}

    try:
        # Create and checkout branch
        subprocess.run(
            ["git", "checkout", "-b", branch],
            check=True, capture_output=True, text=True,
        )
        results["branch_created"] = True
    except subprocess.CalledProcessError as exc:
        results["branch_error"] = exc.stderr.strip()

    try:
        # Stage all changes
        subprocess.run(["git", "add", "-A"], check=True, capture_output=True)
        # Commit
        commit_msg = title or "AutoAgent: automated improvement"
        subprocess.run(
            ["git", "commit", "-m", commit_msg],
            check=True, capture_output=True, text=True,
        )
        results["committed"] = True
    except subprocess.CalledProcessError as exc:
        results["commit_error"] = exc.stderr.strip()

    try:
        # Push
        subprocess.run(
            ["git", "push", "-u", "origin", branch],
            check=True, capture_output=True, text=True,
        )
        results["pushed"] = True
    except subprocess.CalledProcessError as exc:
        results["push_error"] = exc.stderr.strip()

    # Attempt gh pr create
    try:
        pr_cmd = ["gh", "pr", "create", "--base", base_branch,
                  "--title", title or commit_msg, "--body", body or "Auto-generated PR"]
        proc = subprocess.run(pr_cmd, check=True, capture_output=True, text=True)
        results["pr_url"] = proc.stdout.strip()
    except Exception as exc:
        results["pr_note"] = f"gh pr create unavailable: {exc}"

    return results


def explain_diff(diff: str = "", context: str = "", **kwargs: Any) -> dict[str, Any]:
    """Explain the changes in a unified diff in plain English."""
    if not diff:
        return {"error": "No diff provided. Pass the unified diff text as the 'diff' argument."}

    lines = diff.splitlines()
    added = [l[1:] for l in lines if l.startswith("+") and not l.startswith("+++")]
    removed = [l[1:] for l in lines if l.startswith("-") and not l.startswith("---")]
    files_changed = [l for l in lines if l.startswith("--- ") or l.startswith("+++ ")]

    summary_parts: list[str] = []
    if added:
        summary_parts.append(f"{len(added)} line(s) added")
    if removed:
        summary_parts.append(f"{len(removed)} line(s) removed")

    summary = ", ".join(summary_parts) if summary_parts else "No changes detected"

    return {
        "summary": summary,
        "lines_added": len(added),
        "lines_removed": len(removed),
        "files_mentioned": list(set(files_changed)),
        "added_snippets": added[:10],
        "removed_snippets": removed[:10],
        "context": context,
        "note": (
            "For a full LLM-generated explanation use the 'explain_diff' MCP prompt "
            "via the prompts/get endpoint."
        ),
    }


def list_skills(category: str = "", **kwargs: Any) -> list[dict[str, Any]]:
    """List available skills in the registry."""
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
            if not category or getattr(s, "category", "") == category
        ]
        store.close()
        return result
    except Exception as exc:
        return [{"error": str(exc)}]


def apply_skill(
    skill_name: str = "",
    agent_name: str = "",
    config_path: str = "",
    dry_run: bool = False,
    **kwargs: Any,
) -> dict[str, Any]:
    """Apply a skill to an agent, updating its configuration."""
    try:
        from registry.skill_store import SkillStore
        store = SkillStore(db_path=os.environ.get("AUTOAGENT_REGISTRY_DB", "registry.db"))
        skills = store.recommend()
        skill = next((s for s in skills if s.name == skill_name), None)
        store.close()

        if skill is None:
            return {"status": "error", "error": f"Skill not found: {skill_name}"}

        if dry_run:
            return {
                "status": "dry_run",
                "skill_name": skill_name,
                "agent_name": agent_name,
                "would_apply": True,
                "skill_description": getattr(skill, "description", ""),
            }

        # Apply: merge skill instructions into the agent config
        agent_config: dict[str, Any] = {}
        cfg_path = config_path or os.path.join(CONFIGS_DIR, f"{agent_name}.yaml")
        if os.path.isfile(cfg_path):
            try:
                import yaml
                with open(cfg_path) as f:
                    agent_config = yaml.safe_load(f) or {}
            except Exception:
                pass

        existing_skills: list[str] = agent_config.get("skills", [])
        if skill_name not in existing_skills:
            existing_skills.append(skill_name)
        agent_config["skills"] = existing_skills

        if not dry_run and cfg_path:
            try:
                import yaml
                with open(cfg_path, "w") as f:
                    yaml.safe_dump(agent_config, f, default_flow_style=False)
                saved = True
            except Exception:
                saved = False
        else:
            saved = False

        return {
            "status": "applied",
            "skill_name": skill_name,
            "agent_name": agent_name,
            "config_updated": saved,
            "config_path": cfg_path,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def run_benchmark(
    agent_name: str = "",
    benchmark_name: str = "",
    config_path: str = "",
    **kwargs: Any,
) -> dict[str, Any]:
    """Run a benchmark suite against an agent and return scores."""
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
        config = None
        if config_path:
            import yaml
            with open(config_path) as f:
                config = yaml.safe_load(f)
        score = runner.run(config=config)
        return {
            "agent_name": agent_name,
            "benchmark_name": benchmark_name or "default",
            "quality": score.quality,
            "safety": score.safety,
            "latency": score.latency,
            "cost": score.cost,
            "composite": score.composite,
            "passed_cases": score.passed_cases,
            "total_cases": score.total_cases,
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


# Tool registry — maps tool name to (function, MCPToolDef)
TOOL_REGISTRY: dict[str, tuple] = {}

def _register_tools():
    from mcp_server.types import MCPToolDef, MCPToolParam
    global TOOL_REGISTRY
    TOOL_REGISTRY = {
        "autoagent_status": (autoagent_status, MCPToolDef(
            name="autoagent_status",
            description="Get current agent health, scores, and failure summary.",
        )),
        "autoagent_explain": (autoagent_explain, MCPToolDef(
            name="autoagent_explain",
            description="Get a plain-English summary of the agent's current state.",
        )),
        "autoagent_diagnose": (autoagent_diagnose, MCPToolDef(
            name="autoagent_diagnose",
            description="Run failure analysis and return clustered issues with root causes.",
        )),
        "autoagent_get_failures": (autoagent_get_failures, MCPToolDef(
            name="autoagent_get_failures",
            description="Get sample conversations for a specific failure type.",
            parameters=[
                MCPToolParam(name="failure_family", description="Failure type to filter by", required=True),
                MCPToolParam(name="limit", description="Max results", type="integer"),
            ],
        )),
        "autoagent_suggest_fix": (autoagent_suggest_fix, MCPToolDef(
            name="autoagent_suggest_fix",
            description="Suggest a config fix based on natural language description.",
            parameters=[
                MCPToolParam(name="description", description="NL description of the fix", type="string", required=True),
            ],
        )),
        "autoagent_edit": (autoagent_edit, MCPToolDef(
            name="autoagent_edit",
            description="Apply a natural language edit to the agent config.",
            parameters=[
                MCPToolParam(name="description", description="NL description of the edit", type="string", required=True),
                MCPToolParam(name="auto_apply", description="Auto-apply without confirmation", type="boolean"),
            ],
        )),
        "autoagent_eval": (autoagent_eval, MCPToolDef(
            name="autoagent_eval",
            description="Run eval suite and return scores.",
            parameters=[
                MCPToolParam(name="config_path", description="Optional config YAML path", type="string"),
            ],
        )),
        "autoagent_eval_compare": (autoagent_eval_compare, MCPToolDef(
            name="autoagent_eval_compare",
            description="Compare two configs via eval and return winner.",
            parameters=[
                MCPToolParam(name="config_a", description="Path to first config", type="string", required=True),
                MCPToolParam(name="config_b", description="Path to second config", type="string", required=True),
            ],
        )),
        "autoagent_skill_gaps": (autoagent_skill_gaps, MCPToolDef(
            name="autoagent_skill_gaps",
            description="Identify capabilities the agent is missing based on failure analysis.",
        )),
        "autoagent_skill_recommend": (autoagent_skill_recommend, MCPToolDef(
            name="autoagent_skill_recommend",
            description="Recommend optimization skills based on current failure patterns.",
        )),
        "autoagent_replay": (autoagent_replay, MCPToolDef(
            name="autoagent_replay",
            description="Get optimization history showing config evolution.",
            parameters=[
                MCPToolParam(name="limit", description="Max entries to return", type="integer"),
            ],
        )),
        "autoagent_diff": (autoagent_diff, MCPToolDef(
            name="autoagent_diff",
            description="Get unified diff between two config versions.",
            parameters=[
                MCPToolParam(name="version_a", description="First version number", type="integer", required=True),
                MCPToolParam(name="version_b", description="Second version number", type="integer", required=True),
            ],
        )),
        # Build Surface tools (P0-10)
        "scaffold_agent": (scaffold_agent, MCPToolDef(
            name="scaffold_agent",
            description="Scaffold a new ADK agent project with boilerplate config and README.",
            parameters=[
                MCPToolParam(name="name", description="Name of the new agent", type="string", required=True),
                MCPToolParam(name="agent_type", description="Agent type (specialist, router, guardrail, etc.)", type="string"),
                MCPToolParam(name="description", description="Short description of the agent", type="string"),
                MCPToolParam(name="output_dir", description="Directory to scaffold into (default: configs/<name>)", type="string"),
            ],
        )),
        "generate_evals": (generate_evals, MCPToolDef(
            name="generate_evals",
            description="Generate an eval pack (test cases) for an agent capability.",
            parameters=[
                MCPToolParam(name="agent_name", description="Name of the agent to generate evals for", type="string"),
                MCPToolParam(name="capability", description="The capability or behaviour to test", type="string", required=True),
                MCPToolParam(name="num_cases", description="Number of eval cases to generate", type="integer"),
                MCPToolParam(name="include_adversarial", description="Include adversarial/edge-case evals", type="boolean"),
                MCPToolParam(name="output_path", description="Path to save the generated eval pack", type="string"),
            ],
        )),
        "run_sandbox": (run_sandbox, MCPToolDef(
            name="run_sandbox",
            description="Run an agent task in an isolated sandbox and return the result.",
            parameters=[
                MCPToolParam(name="agent_name", description="Name of the agent to run", type="string"),
                MCPToolParam(name="task", description="Task or user message to send to the agent", type="string", required=True),
                MCPToolParam(name="config_path", description="Path to agent config file", type="string"),
                MCPToolParam(name="timeout_seconds", description="Sandbox timeout in seconds", type="integer"),
            ],
        )),
        "inspect_trace": (inspect_trace, MCPToolDef(
            name="inspect_trace",
            description="Inspect a specific conversation trace by ID, or list recent failures.",
            parameters=[
                MCPToolParam(name="trace_id", description="Conversation/trace ID to inspect", type="string"),
                MCPToolParam(name="limit", description="Max recent traces to return when no ID given", type="integer"),
            ],
        )),
        "sync_adk_source": (sync_adk_source, MCPToolDef(
            name="sync_adk_source",
            description="Sync local agent changes back to the ADK source tree.",
            parameters=[
                MCPToolParam(name="source_dir", description="Source directory to sync from", type="string"),
                MCPToolParam(name="target_dir", description="Target directory to sync to", type="string"),
                MCPToolParam(name="dry_run", description="If true, only show what would be synced", type="boolean"),
            ],
        )),
        "open_pr": (open_pr, MCPToolDef(
            name="open_pr",
            description="Create a git branch and open a pull request for pending changes.",
            parameters=[
                MCPToolParam(name="branch_name", description="Name of the branch to create", type="string"),
                MCPToolParam(name="title", description="PR title", type="string", required=True),
                MCPToolParam(name="body", description="PR body / description", type="string"),
                MCPToolParam(name="base_branch", description="Base branch to merge into (default: main)", type="string"),
            ],
        )),
        "explain_diff": (explain_diff, MCPToolDef(
            name="explain_diff",
            description="Explain the changes in a unified diff in plain English.",
            parameters=[
                MCPToolParam(name="diff", description="The unified diff text to explain", type="string", required=True),
                MCPToolParam(name="context", description="Additional context about the change", type="string"),
            ],
        )),
        "list_skills": (list_skills, MCPToolDef(
            name="list_skills",
            description="List available skills in the registry, optionally filtered by category.",
            parameters=[
                MCPToolParam(name="category", description="Filter by skill category", type="string"),
            ],
        )),
        "apply_skill": (apply_skill, MCPToolDef(
            name="apply_skill",
            description="Apply a skill to an agent, updating its configuration.",
            parameters=[
                MCPToolParam(name="skill_name", description="Name of the skill to apply", type="string", required=True),
                MCPToolParam(name="agent_name", description="Name of the target agent", type="string"),
                MCPToolParam(name="config_path", description="Path to the agent config file", type="string"),
                MCPToolParam(name="dry_run", description="If true, only show what would change", type="boolean"),
            ],
        )),
        "run_benchmark": (run_benchmark, MCPToolDef(
            name="run_benchmark",
            description="Run a benchmark suite against an agent and return quality/safety/latency scores.",
            parameters=[
                MCPToolParam(name="agent_name", description="Name of the agent to benchmark", type="string"),
                MCPToolParam(name="benchmark_name", description="Name of the benchmark suite", type="string"),
                MCPToolParam(name="config_path", description="Path to agent config file", type="string"),
            ],
        )),
    }

_register_tools()
