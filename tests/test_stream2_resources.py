"""Tests for Stream 2 — Resources & Durability (FR-05, FR-06, FR-07, FR-08, FR-13).

Covers:
  FR-05: autoagent config import
  FR-06: Durable semantics (release create, trace promote, autofix apply writes config)
  FR-07: --json output standard envelope
  FR-08: Standard selectors (latest/active/pending)
  FR-13: Inspect commands (build-show, policy list/show, autofix show, eval show, trace show)
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from click.testing import CliRunner

from optimizer.autofix import AutoFixProposal, AutoFixStore
from runner import cli


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_yaml(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _write_json(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def _setup_configs_dir(tmp_path: Path) -> Path:
    """Create a configs dir with a base config and manifest."""
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    config = {"prompts": {"root": "test"}, "routing": {"rules": []}}
    _write_yaml(configs_dir / "v001_base.yaml", config)
    manifest = {
        "versions": [
            {
                "version": 1,
                "config_hash": "abc123",
                "filename": "v001_base.yaml",
                "timestamp": 1700000000.0,
                "scores": {"composite": 0.75},
                "status": "active",
            }
        ],
        "active_version": 1,
        "canary_version": None,
    }
    _write_json(configs_dir / "manifest.json", manifest)
    return configs_dir


# ---------------------------------------------------------------------------
# FR-05: Config import
# ---------------------------------------------------------------------------

class TestConfigImport:
    def test_import_yaml_config(self, tmp_path: Path) -> None:
        configs_dir = _setup_configs_dir(tmp_path)
        source = _write_yaml(tmp_path / "my_config.yaml", {"prompts": {"root": "imported"}})

        runner = CliRunner()
        result = runner.invoke(cli, ["config", "import", str(source), "--configs-dir", str(configs_dir)])
        assert result.exit_code == 0
        assert "Config Imported" in result.output
        assert "v002" in result.output

        # Verify file was written
        assert (configs_dir / "v002_imported.yaml").exists()

        # Verify manifest updated
        manifest = json.loads((configs_dir / "manifest.json").read_text())
        assert len(manifest["versions"]) == 2
        assert manifest["versions"][-1]["version"] == 2
        assert manifest["versions"][-1]["status"] == "imported"

    def test_import_json_config(self, tmp_path: Path) -> None:
        configs_dir = _setup_configs_dir(tmp_path)
        source = _write_json(tmp_path / "my_config.json", {"prompts": {"root": "from json"}})

        runner = CliRunner()
        result = runner.invoke(cli, ["config", "import", str(source), "--configs-dir", str(configs_dir)])
        assert result.exit_code == 0
        assert "Config Imported" in result.output

    def test_import_config_json_output(self, tmp_path: Path) -> None:
        configs_dir = _setup_configs_dir(tmp_path)
        source = _write_yaml(tmp_path / "cfg.yaml", {"test": True})

        runner = CliRunner()
        result = runner.invoke(cli, ["config", "import", str(source), "--configs-dir", str(configs_dir), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "ok"
        assert data["data"]["version"] == 2
        assert "next" in data

    def test_import_appears_in_config_list(self, tmp_path: Path) -> None:
        configs_dir = _setup_configs_dir(tmp_path)
        source = _write_yaml(tmp_path / "cfg.yaml", {"test": True})

        runner = CliRunner()
        runner.invoke(cli, ["config", "import", str(source), "--configs-dir", str(configs_dir)])

        result = runner.invoke(cli, ["config", "list", "--configs-dir", str(configs_dir)])
        assert result.exit_code == 0
        assert "imported" in result.output


# ---------------------------------------------------------------------------
# FR-06: Durable semantics
# ---------------------------------------------------------------------------

class TestDurableSemantics:
    def test_release_create_persists(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["release", "create", "--experiment-id", "exp-test123"])
        assert result.exit_code == 0
        assert "Release created" in result.output
        assert "rel-" in result.output

        # Verify file was persisted
        releases_dir = tmp_path / ".autoagent" / "releases"
        release_files = list(releases_dir.glob("rel-*.json"))
        assert len(release_files) == 1
        release = json.loads(release_files[0].read_text())
        assert release["experiment_id"] == "exp-test123"
        assert release["status"] == "DRAFT"

    def test_release_list_shows_created(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        runner.invoke(cli, ["release", "create", "--experiment-id", "exp-a"])
        runner.invoke(cli, ["release", "create", "--experiment-id", "exp-b"])

        result = runner.invoke(cli, ["release", "list"])
        assert result.exit_code == 0
        assert "exp-a" in result.output or "exp-b" in result.output

    def test_release_create_json(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["release", "create", "--experiment-id", "exp-json", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "ok"
        assert data["data"]["experiment_id"] == "exp-json"

    def test_trace_promote_writes_eval_case(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        eval_dir = tmp_path / "evals" / "cases"
        eval_dir.mkdir(parents=True)

        runner = CliRunner()
        result = runner.invoke(cli, ["trace", "promote", "test-trace-abc", "--eval-cases-dir", str(eval_dir)])
        assert result.exit_code == 0
        assert "Promoted" in result.output

        # Verify eval case file written
        case_file = eval_dir / "promoted_test-trace-abc.yaml"
        assert case_file.exists()
        content = yaml.safe_load(case_file.read_text())
        assert "cases" in content
        assert content["cases"][0]["case_id"] == "promoted_test-trace-abc"


# ---------------------------------------------------------------------------
# FR-07: Standard JSON output
# ---------------------------------------------------------------------------

class TestJsonOutput:
    def test_config_list_json(self, tmp_path: Path) -> None:
        configs_dir = _setup_configs_dir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "list", "--configs-dir", str(configs_dir), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "ok"
        assert isinstance(data["data"], list)
        assert len(data["data"]) == 1
        assert data["data"][0]["version"] == 1

    def test_config_show_json(self, tmp_path: Path) -> None:
        configs_dir = _setup_configs_dir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "show", "1", "--configs-dir", str(configs_dir), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "ok"
        assert "config" in data["data"]

    def test_release_list_json(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        runner.invoke(cli, ["release", "create", "--experiment-id", "exp-j"])
        result = runner.invoke(cli, ["release", "list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "ok"
        assert len(data["data"]) >= 1

    def test_json_envelope_format(self, tmp_path: Path) -> None:
        """All --json commands should return {"status": ..., "data": ...}."""
        configs_dir = _setup_configs_dir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "list", "--configs-dir", str(configs_dir), "--json"])
        data = json.loads(result.output)
        assert "status" in data
        assert "data" in data


# ---------------------------------------------------------------------------
# FR-08: Standard selectors
# ---------------------------------------------------------------------------

class TestStandardSelectors:
    def test_config_show_active_selector(self, tmp_path: Path) -> None:
        configs_dir = _setup_configs_dir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "show", "active", "--configs-dir", str(configs_dir)])
        assert result.exit_code == 0
        assert "v001" in result.output

    def test_config_show_latest_selector(self, tmp_path: Path) -> None:
        configs_dir = _setup_configs_dir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "show", "latest", "--configs-dir", str(configs_dir)])
        assert result.exit_code == 0
        assert "v001" in result.output

    def test_config_show_latest_json(self, tmp_path: Path) -> None:
        configs_dir = _setup_configs_dir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["config", "show", "latest", "--configs-dir", str(configs_dir), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "ok"
        assert data["data"]["version"] == 1


# ---------------------------------------------------------------------------
# FR-13: Inspect commands
# ---------------------------------------------------------------------------

class TestInspectCommands:
    def test_build_show_no_artifact(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["build-show", "latest"])
        assert result.exit_code == 0
        assert "No build artifact found" in result.output

    def test_build_show_with_artifact(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        aa_dir = tmp_path / ".autoagent"
        aa_dir.mkdir()
        _write_json(aa_dir / "build_artifact_latest.json", {
            "source_prompt": "Build a support bot",
            "connectors": ["Shopify"],
            "intents": [{"name": "order_status"}],
            "tools": [],
            "guardrails": ["no_pii"],
            "skills": [],
        })

        runner = CliRunner()
        result = runner.invoke(cli, ["build-show", "latest"])
        assert result.exit_code == 0
        assert "Build a support bot" in result.output
        assert "Shopify" in result.output

    def test_build_show_json(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        aa_dir = tmp_path / ".autoagent"
        aa_dir.mkdir()
        _write_json(aa_dir / "build_artifact_latest.json", {
            "source_prompt": "test",
            "connectors": [],
            "intents": [],
            "tools": [],
            "guardrails": [],
            "skills": [],
        })

        runner = CliRunner()
        result = runner.invoke(cli, ["build-show", "latest", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "ok"
        assert data["data"]["source_prompt"] == "test"

    def test_build_show_reads_from_shared_store(self, tmp_path: Path, monkeypatch) -> None:
        from shared.build_artifact_store import BuildArtifactStore
        from shared.contracts import BuildArtifact

        monkeypatch.chdir(tmp_path)
        store = BuildArtifactStore(
            path=tmp_path / ".autoagent" / "build_artifacts.json",
            latest_path=tmp_path / ".autoagent" / "build_artifact_latest.json",
        )
        store.save_latest(
            BuildArtifact(
                id="build-store-001",
                created_at="2026-03-29T12:00:00Z",
                updated_at="2026-03-29T12:00:00Z",
                source="prompt",
                status="complete",
                config_yaml="agent_name: Test",
                prompt_used="Build a support bot",
                selector="latest",
                metadata={
                    "connectors": ["Shopify"],
                    "intents": [{"name": "order_status"}],
                    "tools": [],
                    "guardrails": ["no_pii"],
                    "skills": [],
                },
            )
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["build-show", "latest"])
        assert result.exit_code == 0
        assert "Build a support bot" in result.output
        assert "Shopify" in result.output

    def test_eval_show_no_results(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["eval", "show", "latest"])
        assert result.exit_code == 0
        assert "No eval results found" in result.output

    def test_eval_show_with_results(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        results_data = {
            "timestamp": "2024-01-01T00:00:00",
            "config_path": "configs/v001.yaml",
            "passed": 8,
            "total": 10,
            "scores": {"quality": 0.85, "safety": 1.0, "latency": 0.9, "cost": 0.8, "composite": 0.88},
            "results": [],
        }
        _write_json(tmp_path / "eval_results.json", results_data)

        runner = CliRunner()
        result = runner.invoke(cli, ["eval", "show", "latest"])
        assert result.exit_code == 0
        assert "8/10 passed" in result.output

    def test_policy_list_empty(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["policy", "list"])
        assert result.exit_code == 0
        # Either shows "No policy artifacts" or shows a list
        assert "policy" in result.output.lower() or "No policy" in result.output

    def test_autofix_show_pending_uses_store_pending_selector(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        aa_dir = tmp_path / ".autoagent"
        aa_dir.mkdir()
        store = AutoFixStore(db_path=str(aa_dir / "autofix.db"))
        store.save(
            AutoFixProposal(
                proposal_id="prop-pending",
                mutation_name="tighten_refund_check",
                surface="prompts.root",
                diff_preview="Add verification reminder",
            )
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["autofix", "show", "pending", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "ok"
        assert data["data"]["proposal_id"] == "prop-pending"

    def test_autofix_apply_pending_resolves_pending_store_entry(self, tmp_path: Path, monkeypatch) -> None:
        import optimizer.autofix as autofix_module

        monkeypatch.chdir(tmp_path)
        aa_dir = tmp_path / ".autoagent"
        aa_dir.mkdir()
        store = AutoFixStore(db_path=str(aa_dir / "autofix.db"))
        store.save(
            AutoFixProposal(
                proposal_id="prop-apply",
                mutation_name="tighten_refund_check",
                surface="prompts.root",
                diff_preview="Add verification reminder",
            )
        )

        def _fake_apply(self, proposal_id: str, current_config: dict) -> tuple[dict, str]:
            del self, current_config
            assert proposal_id == "prop-apply"
            return {"model": "demo-model"}, "Applied pending proposal"

        monkeypatch.setattr(autofix_module.AutoFixEngine, "apply", _fake_apply)

        runner = CliRunner()
        result = runner.invoke(cli, ["autofix", "apply", "pending", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "ok"
        assert data["data"]["proposal_id"] == "prop-apply"
        assert data["data"]["config_version"] == 2


# ---------------------------------------------------------------------------
# stream2_helpers unit tests
# ---------------------------------------------------------------------------

class TestStream2Helpers:
    def test_config_importer(self, tmp_path: Path) -> None:
        from cli.stream2_helpers import ConfigImporter

        configs_dir = tmp_path / "configs"
        configs_dir.mkdir()
        source = _write_yaml(tmp_path / "input.yaml", {"test": "value"})

        importer = ConfigImporter(configs_dir=str(configs_dir))
        result = importer.import_config(str(source))

        assert result["version"] == 1
        assert result["source_file"] == "input.yaml"
        assert (configs_dir / "v001_imported.yaml").exists()

    def test_json_response_format(self) -> None:
        from cli.stream2_helpers import json_response

        output = json_response("ok", {"key": "val"}, next_cmd="autoagent status")
        data = json.loads(output)
        assert data["status"] == "ok"
        assert data["data"]["key"] == "val"
        assert data["next"] == "autoagent status"

    def test_json_response_no_next(self) -> None:
        from cli.stream2_helpers import json_response

        output = json_response("error", {"message": "fail"})
        data = json.loads(output)
        assert data["status"] == "error"
        assert "next" not in data

    def test_is_selector(self) -> None:
        from cli.stream2_helpers import is_selector

        assert is_selector("latest") is True
        assert is_selector("LATEST") is True
        assert is_selector("active") is True
        assert is_selector("current") is True
        assert is_selector("pending") is True
        assert is_selector("abc123") is False
        assert is_selector("3") is False

    def test_resolve_selector(self) -> None:
        from cli.stream2_helpers import resolve_selector

        items = [
            {"version": 3, "status": "candidate"},
            {"version": 2, "status": "active"},
            {"version": 1, "status": "retired"},
        ]
        assert resolve_selector("latest", items)["version"] == 3
        assert resolve_selector("active", items)["version"] == 2
        assert resolve_selector("pending", items)["version"] == 3
        assert resolve_selector("latest", []) is None

    def test_release_store_create_and_list(self, tmp_path: Path) -> None:
        from cli.stream2_helpers import ReleaseStore

        store = ReleaseStore(store_dir=str(tmp_path / "releases"))
        r1 = store.create("exp-1")
        r2 = store.create("exp-2")

        assert r1["release_id"].startswith("rel-")
        assert r1["status"] == "DRAFT"

        releases = store.list_releases()
        assert len(releases) == 2

        fetched = store.get(r1["release_id"])
        assert fetched is not None
        assert fetched["experiment_id"] == "exp-1"

    def test_write_trace_eval_case(self, tmp_path: Path) -> None:
        from cli.stream2_helpers import write_trace_eval_case

        eval_dir = tmp_path / "evals" / "cases"
        case = {"case_id": "promoted_t1", "task": "test task", "category": "promoted"}
        path = write_trace_eval_case("t1", case, eval_cases_dir=str(eval_dir))

        assert Path(path).exists()
        content = yaml.safe_load(Path(path).read_text())
        assert content["cases"][0]["case_id"] == "promoted_t1"

    def test_apply_autofix_to_config(self, tmp_path: Path) -> None:
        from cli.stream2_helpers import apply_autofix_to_config

        configs_dir = tmp_path / "configs"
        configs_dir.mkdir()
        manifest = {"versions": [], "active_version": None, "canary_version": None}
        (configs_dir / "manifest.json").write_text(json.dumps(manifest))

        result = apply_autofix_to_config("prop123", {"test": "fixed"}, configs_dir=str(configs_dir))
        assert result["version"] == 1
        assert "autofix" in result["filename"]
        assert Path(result["path"]).exists()

    def test_get_latest_build_artifact(self, tmp_path: Path, monkeypatch) -> None:
        from cli.stream2_helpers import get_latest_build_artifact

        monkeypatch.chdir(tmp_path)
        assert get_latest_build_artifact() is None

        aa_dir = tmp_path / ".autoagent"
        aa_dir.mkdir(exist_ok=True)
        _write_json(aa_dir / "build_artifact_latest.json", {"source_prompt": "hello"})
        assert get_latest_build_artifact()["source_prompt"] == "hello"

    def test_get_latest_build_artifact_prefers_shared_store(self, tmp_path: Path, monkeypatch) -> None:
        from cli.stream2_helpers import get_latest_build_artifact
        from shared.build_artifact_store import BuildArtifactStore
        from shared.contracts import BuildArtifact

        monkeypatch.chdir(tmp_path)
        store = BuildArtifactStore(
            path=tmp_path / ".autoagent" / "build_artifacts.json",
            latest_path=tmp_path / ".autoagent" / "build_artifact_latest.json",
        )
        store.save_latest(
            BuildArtifact(
                id="build-store-002",
                created_at="2026-03-29T12:10:00Z",
                updated_at="2026-03-29T12:10:00Z",
                source="prompt",
                status="complete",
                config_yaml="agent_name: Store Preferred",
                prompt_used="Build from store",
                selector="latest",
            )
        )

        artifact = get_latest_build_artifact()
        assert artifact is not None
        assert artifact["source_prompt"] == "Build from store"
        assert artifact["artifact_id"] == "build-store-002"
