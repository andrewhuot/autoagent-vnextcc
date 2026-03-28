"""Reward Registry API endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query, Request

router = APIRouter(prefix="/api/rewards", tags=["rewards"])


def _get_registry(request: Request):
    """Retrieve the shared RewardRegistry from app state."""
    registry = getattr(request.app.state, "reward_registry", None)
    if registry is None:
        from rewards.registry import RewardRegistry
        registry = RewardRegistry()
        request.app.state.reward_registry = registry
    return registry


# POST /api/rewards — create reward definition
@router.post("", status_code=201)
async def create_reward(request: Request, body: dict[str, Any] = Body(...)):
    """Create a new reward definition."""
    registry = _get_registry(request)
    required = {"name", "kind"}
    missing = required - set(body.keys())
    if missing:
        raise HTTPException(400, f"Missing: {sorted(missing)}")
    from rewards.types import RewardDefinition
    defn = RewardDefinition.from_dict(body)
    name, version = registry.register(defn)
    return {"ok": True, "name": name, "version": version, "reward_id": defn.reward_id}


# GET /api/rewards — list all rewards
@router.get("")
async def list_rewards(request: Request, kind: str | None = Query(None)):
    registry = _get_registry(request)
    if kind:
        rewards = registry.list_by_kind(kind)
    else:
        rewards = registry.list_all()
    return {"rewards": [r.to_dict() for r in rewards], "count": len(rewards)}


# GET /api/rewards/{name} — get specific reward
@router.get("/{name}")
async def get_reward(request: Request, name: str, version: int | None = Query(None)):
    registry = _get_registry(request)
    reward = registry.get(name, version)
    if reward is None:
        raise HTTPException(404, f"Reward not found: {name}")
    return reward.to_dict()


# POST /api/rewards/{name}/test — test reward against trace
@router.post("/{name}/test")
async def test_reward(request: Request, name: str, body: dict[str, Any] = Body(...)):
    """Test a reward definition against a trace."""
    registry = _get_registry(request)
    reward = registry.get(name)
    if reward is None:
        raise HTTPException(404, f"Reward not found: {name}")
    # Return the reward definition with test context
    return {"ok": True, "reward": reward.to_dict(), "test_input": body}


# GET /api/rewards/hard-gates — list all hard gates
@router.get("/hard-gates/list")
async def list_hard_gates(request: Request):
    registry = _get_registry(request)
    gates = registry.list_hard_gates()
    return {"hard_gates": [g.to_dict() for g in gates], "count": len(gates)}


# POST /api/rewards/{name}/audit — run reward audit
@router.post("/{name}/audit")
async def audit_reward(request: Request, name: str, body: dict[str, Any] = Body(default={})):
    """Run anti-reward-hacking audit on a reward definition."""
    registry = _get_registry(request)
    reward = registry.get(name)
    if reward is None:
        raise HTTPException(404, f"Reward not found: {name}")
    from rewards.auditor import RewardAuditor
    from rewards.types import RewardVector
    auditor = RewardAuditor()
    test_vectors = [RewardVector.from_dict(v) for v in body.get("test_vectors", [])]
    report = auditor.run_audit(reward, test_vectors)
    return report.to_dict()


# POST /api/rewards/challenge — run challenge suite
@router.post("/challenge/run")
async def run_challenge_suite(request: Request, body: dict[str, Any] = Body(default={})):
    """Run sycophancy/reward-hacking challenge suites."""
    from rewards.challenge_suites import ChallengeSuiteRunner, get_builtin_suites
    runner = ChallengeSuiteRunner()
    suite_name = body.get("suite")
    if suite_name:
        suites = [s for s in get_builtin_suites() if s.name == suite_name]
        if not suites:
            raise HTTPException(404, f"Suite not found: {suite_name}")
        reports = [runner.run_suite(s) for s in suites]
    else:
        reports = runner.run_all_builtin()
    return {"reports": [r.to_dict() for r in reports], "count": len(reports)}
