"""CLI e2e tests for doctor mock_reason (R1.12)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_doctor(cwd: Path, env_override: dict[str, str] | None = None, json_out: bool = True) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    # Strip provider keys so we can control them deterministically.
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "GOOGLE_GENAI_API_KEY"):
        env.pop(var, None)
    if env_override:
        env.update(env_override)
    env["PYTHONPATH"] = str(REPO_ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    args = [sys.executable, "-m", "runner", "doctor"]
    if json_out:
        args.append("--json")
    return subprocess.run(args, capture_output=True, text=True, env=env, cwd=str(cwd))


def _seed_workspace(tmp_path: Path, use_mock: bool) -> None:
    (tmp_path / ".agentlab").mkdir(parents=True, exist_ok=True)
    (tmp_path / "configs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "agentlab.yaml").write_text(
        f"name: test\noptimizer:\n  use_mock: {'true' if use_mock else 'false'}\n"
    )


def _parse_json_payload(stdout: str) -> dict:
    """Find and parse the JSON envelope from mixed stdout."""
    # The envelope is multi-line JSON. Find the outermost { ... } block.
    stdout = stdout.strip()
    # Try: full stdout first
    try:
        return json.loads(stdout)
    except Exception:
        pass
    # Find the first '{' and try progressively larger substrings starting from it
    idx = stdout.find("{")
    if idx >= 0:
        candidate = stdout[idx:]
        try:
            return json.loads(candidate)
        except Exception:
            pass
    # Fallback: last line
    return json.loads(stdout.splitlines()[-1])


def test_doctor_reports_configured_when_yaml_true(tmp_path):
    _seed_workspace(tmp_path, use_mock=True)
    result = _run_doctor(tmp_path, json_out=True)
    assert result.returncode == 0, result.stderr
    payload = _parse_json_payload(result.stdout)
    assert payload["data"]["mock_reason"] == "configured"


def test_doctor_reports_valid_reason_when_yaml_absent_no_key(tmp_path):
    # No optimizer section — runtime defaults to use_mock=false, so "disabled".
    # This test covers the envelope shape and valid-reason invariant.
    (tmp_path / ".agentlab").mkdir()
    (tmp_path / "agentlab.yaml").write_text("name: test\n")
    result = _run_doctor(tmp_path, json_out=True)
    assert result.returncode == 0, result.stderr
    payload = _parse_json_payload(result.stdout)
    assert payload["data"]["mock_reason"] in ("disabled", "configured", "missing_provider_key")
    assert "mock_reason_detail" in payload["data"]


def test_doctor_reports_disabled_when_key_present_and_yaml_false(tmp_path):
    _seed_workspace(tmp_path, use_mock=False)
    result = _run_doctor(
        tmp_path,
        env_override={"OPENAI_API_KEY": "sk-" + "a" * 40},
        json_out=True,
    )
    assert result.returncode == 0, result.stderr
    payload = _parse_json_payload(result.stdout)
    assert payload["data"]["mock_reason"] == "disabled"


def test_doctor_text_output_includes_configured_word(tmp_path):
    _seed_workspace(tmp_path, use_mock=True)
    result = _run_doctor(tmp_path, json_out=False)
    combined = result.stdout + result.stderr
    assert "configured" in combined.lower() or "enabled" in combined.lower()


def test_doctor_text_output_includes_missing_key_hint(tmp_path):
    (tmp_path / "agentlab.yaml").write_text("name: test\n")
    result = _run_doctor(tmp_path, json_out=False)
    combined = result.stdout + result.stderr
    # The "Fix:" line should mention OPENAI/ANTHROPIC/GOOGLE
    assert any(k in combined for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"))
