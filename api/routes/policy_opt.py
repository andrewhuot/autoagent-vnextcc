"""Policy Optimization API endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request

router = APIRouter(prefix="/api/rl", tags=["policy-optimization"])


def _get_orchestrator(request: Request):
    """Retrieve the shared PolicyOptOrchestrator."""
    orch = getattr(request.app.state, "policy_orchestrator", None)
    if orch is None:
        from policy_opt.registry import PolicyArtifactRegistry
        from policy_opt.orchestrator import PolicyOptOrchestrator
        registry = PolicyArtifactRegistry()
        orch = PolicyOptOrchestrator(policy_registry=registry)
        request.app.state.policy_orchestrator = orch
    return orch


def _get_registry(request: Request):
    orch = _get_orchestrator(request)
    return orch._registry


# POST /api/rl/datasets/build — build training dataset
@router.post("/datasets/build")
async def build_dataset(request: Request, body: dict[str, Any] = Body(...)):
    """Build a training dataset from episodes."""
    from data.episodes import EpisodeStore
    from policy_opt.dataset_builder import RewardDatasetBuilder
    episode_store = EpisodeStore()
    builder = RewardDatasetBuilder()
    mode = body.get("mode", "verifiable")
    episode_ids = body.get("episode_ids")
    if episode_ids:
        episodes = [episode_store.get_episode(eid) for eid in episode_ids]
        episodes = [e for e in episodes if e is not None]
    else:
        episodes = episode_store.list_episodes(limit=body.get("limit", 1000))
    if mode == "verifiable":
        path = builder.build_verifiable_dataset(episodes)
    elif mode == "preference":
        path = builder.build_preference_pairs(episodes)
    elif mode == "episode":
        path = builder.build_episode_export(episodes)
    elif mode == "audit":
        path = builder.build_audit_set(episodes)
    else:
        raise HTTPException(400, f"Unknown mode: {mode}")
    return {"ok": True, "path": path, "mode": mode, "n_episodes": len(episodes)}


# POST /api/rl/train — start training job
@router.post("/train", status_code=202)
async def start_training(request: Request, body: dict[str, Any] = Body(...)):
    orch = _get_orchestrator(request)
    required = {"mode", "backend", "dataset_path"}
    missing = required - set(body.keys())
    if missing:
        raise HTTPException(400, f"Missing: {sorted(missing)}")
    try:
        job = orch.create_training_job(
            mode=body["mode"],
            backend=body["backend"],
            dataset_path=body["dataset_path"],
            reward_spec=body.get("reward_spec"),
            config=body.get("config"),
        )
        # Start the job
        job = orch.start_training(job.job_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "job": job.to_dict()}


# GET /api/rl/jobs — list training jobs
@router.get("/jobs")
async def list_jobs(request: Request, status: str | None = Query(None)):
    orch = _get_orchestrator(request)
    jobs = orch.list_jobs(status=status)
    return {"jobs": [j.to_dict() for j in jobs], "count": len(jobs)}


# GET /api/rl/jobs/{job_id} — get job details
@router.get("/jobs/{job_id}")
async def get_job(request: Request, job_id: str):
    orch = _get_orchestrator(request)
    job = orch.get_job(job_id)
    if job is None:
        raise HTTPException(404, f"Job not found: {job_id}")
    return job.to_dict()


# GET /api/rl/policies — list policy artifacts
@router.get("/policies")
async def list_policies(request: Request, policy_type: str | None = Query(None), status: str | None = Query(None)):
    registry = _get_registry(request)
    if status:
        policies = registry.list_by_status(status)
    elif policy_type:
        policies = registry.list_by_type(policy_type)
    else:
        policies = registry.list_all()
    return {"policies": [p.to_dict() for p in policies], "count": len(policies)}


# GET /api/rl/policies/{policy_id} — get policy
@router.get("/policies/{policy_id}")
async def get_policy(request: Request, policy_id: str):
    registry = _get_registry(request)
    policy = registry.get_by_id(policy_id)
    if policy is None:
        raise HTTPException(404, f"Policy not found: {policy_id}")
    return policy.to_dict()


# POST /api/rl/evaluate — offline eval
@router.post("/evaluate")
async def evaluate_policy(request: Request, body: dict[str, Any] = Body(...)):
    orch = _get_orchestrator(request)
    policy_id = body.get("policy_id")
    if not policy_id:
        raise HTTPException(400, "Missing policy_id")
    try:
        report = orch.evaluate_policy(policy_id)
    except KeyError as e:
        raise HTTPException(404, str(e))
    return {"ok": True, "report": report}


# POST /api/rl/ope — off-policy evaluation
@router.post("/ope")
async def ope_evaluate(request: Request, body: dict[str, Any] = Body(...)):
    """Run off-policy evaluation."""
    policy_id = body.get("policy_id")
    if not policy_id:
        raise HTTPException(400, "Missing policy_id")
    registry = _get_registry(request)
    policy = registry.get_by_id(policy_id)
    if policy is None:
        raise HTTPException(404, f"Policy not found: {policy_id}")
    from data.episodes import EpisodeStore
    from policy_opt.ope import OffPolicyEvaluator
    episode_store = EpisodeStore()
    episodes = episode_store.list_episodes(limit=body.get("n_episodes", 500))
    evaluator = OffPolicyEvaluator()
    report = evaluator.evaluate(policy, episodes)
    return {"ok": True, "report": report.to_dict()}


# POST /api/rl/canary — start canary
@router.post("/canary")
async def start_canary(request: Request, body: dict[str, Any] = Body(...)):
    policy_id = body.get("policy_id")
    if not policy_id:
        raise HTTPException(400, "Missing policy_id")
    registry = _get_registry(request)
    policy = registry.get_by_id(policy_id)
    if policy is None:
        raise HTTPException(404, f"Policy not found: {policy_id}")
    registry.update_status(policy_id, "canary")
    return {"ok": True, "policy_id": policy_id, "status": "canary"}


# POST /api/rl/promote — promote policy
@router.post("/promote")
async def promote_policy(request: Request, body: dict[str, Any] = Body(...)):
    orch = _get_orchestrator(request)
    policy_id = body.get("policy_id")
    if not policy_id:
        raise HTTPException(400, "Missing policy_id")
    try:
        policy = orch.promote_policy(policy_id)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "policy": policy.to_dict()}


# POST /api/rl/rollback — rollback policy
@router.post("/rollback")
async def rollback_policy(request: Request, body: dict[str, Any] = Body(...)):
    orch = _get_orchestrator(request)
    policy_id = body.get("policy_id")
    if not policy_id:
        raise HTTPException(400, "Missing policy_id")
    try:
        rollback_target = orch.rollback_policy(policy_id)
    except KeyError as e:
        raise HTTPException(404, str(e))
    return {"ok": True, "rolled_back": policy_id, "rollback_target": rollback_target}
