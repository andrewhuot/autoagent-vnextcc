"""CLI tests for Stream 3 integrations and mode control."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from runner import cli


def _archive_path(tmp_path: Path) -> Path:
    transcripts = [
        {
            "conversation_id": "cli-001",
            "session_id": "s1",
            "user_message": "Where is my order? I do not have the order number.",
            "agent_response": "I need to transfer you to live support.",
            "outcome": "transfer",
        },
        {
            "conversation_id": "cli-002",
            "session_id": "s2",
            "user_message": "Please cancel my order.",
            "agent_response": "First verify identity, then cancel it.",
            "outcome": "success",
        },
    ]

    archive_path = tmp_path / "support.zip"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as zf:
        zf.writestr("transcripts.json", json.dumps(transcripts))
        zf.writestr("playbook.txt", "Verify identity. Use email fallback when order number is missing.")

    archive_path.write_bytes(buffer.getvalue())
    return archive_path


class TestTranscriptIntelligenceCLI:
    def test_upload_lists_and_shows_report(self, tmp_path: Path) -> None:
        runner = CliRunner()
        archive_path = _archive_path(tmp_path)

        with runner.isolated_filesystem(temp_dir=str(tmp_path)):
            upload_result = runner.invoke(cli, ["intelligence", "upload", str(archive_path)])

            assert upload_result.exit_code == 0, upload_result.output
            assert "Report ID:" in upload_result.output

            list_result = runner.invoke(cli, ["intelligence", "report", "list"])
            assert list_result.exit_code == 0, list_result.output
            assert "support.zip" in list_result.output

            report_id = upload_result.output.split("Report ID:", 1)[1].strip().splitlines()[0].strip()
            show_result = runner.invoke(cli, ["intelligence", "report", "show", report_id])
            assert show_result.exit_code == 0, show_result.output
            assert "support.zip" in show_result.output
            assert "Conversation count:" in show_result.output

    def test_generate_agent_uses_uploaded_report(self, tmp_path: Path) -> None:
        runner = CliRunner()
        archive_path = _archive_path(tmp_path)

        with runner.isolated_filesystem(temp_dir=str(tmp_path)):
            upload_result = runner.invoke(cli, ["intelligence", "upload", str(archive_path)])
            assert upload_result.exit_code == 0, upload_result.output
            report_id = upload_result.output.split("Report ID:", 1)[1].strip().splitlines()[0].strip()

            generate_result = runner.invoke(cli, ["intelligence", "generate-agent", report_id, "--json"])

            assert generate_result.exit_code == 0, generate_result.output
            payload = json.loads(generate_result.output)
            assert payload["metadata"]["created_from"] == "transcript"
            assert payload["system_prompt"]
            assert payload["tools"]

    def test_upload_resolves_relative_archive_from_nested_workspace_directory(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Relative archive paths should still work after workspace auto-discovery changes cwd."""
        runner = CliRunner()
        workspace = tmp_path / "workspace"
        init_result = runner.invoke(cli, ["init", "--dir", str(workspace), "--demo"])
        assert init_result.exit_code == 0, init_result.output

        nested_dir = workspace / "scratch" / "deeply" / "nested"
        nested_dir.mkdir(parents=True)
        archive_path = _archive_path(nested_dir)
        monkeypatch.chdir(nested_dir)

        result = runner.invoke(cli, ["intelligence", "upload", archive_path.name])

        assert result.exit_code == 0, result.output
        assert "Report ID:" in result.output


class TestMCPSetupCLI:
    @pytest.mark.parametrize(
        ("client_name", "relative_path", "expected_fragment"),
        [
            ("claude-code", Path(".claude") / "mcp.json", '"command": "agentlab"'),
            ("codex", Path(".codex") / "config.toml", 'command = "agentlab"'),
            ("cursor", Path(".cursor") / "mcp.json", '"command": "agentlab"'),
            ("windsurf", Path(".codeium") / "windsurf" / "mcp_config.json", '"command": "agentlab"'),
        ],
    )
    def test_mcp_init_writes_expected_config(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        client_name: str,
        relative_path: Path,
        expected_fragment: str,
    ) -> None:
        runner = CliRunner()
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        monkeypatch.chdir(workspace_dir)

        env = {"HOME": str(home_dir)}
        result = runner.invoke(cli, ["mcp", "init", client_name], env=env)

        assert result.exit_code == 0, result.output
        config_path = home_dir / relative_path if client_name != "cursor" else workspace_dir / relative_path
        assert config_path.exists()
        assert expected_fragment in config_path.read_text(encoding="utf-8")
        assert "Verification" in result.output

    def test_mcp_init_backs_up_existing_config_and_status_reports_clients(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        runner = CliRunner()
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        monkeypatch.chdir(workspace_dir)

        codex_dir = home_dir / ".codex"
        codex_dir.mkdir(parents=True)
        config_path = codex_dir / "config.toml"
        config_path.write_text("[existing]\nvalue = true\n", encoding="utf-8")

        env = {"HOME": str(home_dir)}
        init_result = runner.invoke(cli, ["mcp", "init", "codex"], env=env)

        assert init_result.exit_code == 0, init_result.output
        assert list(codex_dir.glob("config.toml.bak.*"))

        status_result = runner.invoke(cli, ["mcp", "status"], env=env)
        assert status_result.exit_code == 0, status_result.output
        assert "codex" in status_result.output.lower()
        assert "configured" in status_result.output.lower()

    def test_mcp_init_codex_preserves_quoted_keys_in_existing_toml(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        runner = CliRunner()
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        monkeypatch.chdir(workspace_dir)

        codex_dir = home_dir / ".codex"
        codex_dir.mkdir(parents=True)
        config_path = codex_dir / "config.toml"
        config_path.write_text(
            """
[mcp_servers.context7]
command = "npx"
args = ["-y", "@upstash/context7-mcp@latest"]

[projects."/Users/example/project"]
trust_level = "trusted"

[notice.model_migrations]
"gpt-5.3-codex" = "gpt-5.4"
""".strip()
            + "\n",
            encoding="utf-8",
        )

        env = {"HOME": str(home_dir)}
        init_result = runner.invoke(cli, ["mcp", "init", "codex"], env=env)

        assert init_result.exit_code == 0, init_result.output
        rewritten = config_path.read_text(encoding="utf-8")
        assert '[projects."/Users/example/project"]' in rewritten
        assert '"gpt-5.3-codex" = "gpt-5.4"' in rewritten

        status_result = runner.invoke(cli, ["mcp", "status"], env=env)
        assert status_result.exit_code == 0, status_result.output
        assert "codex" in status_result.output.lower()
        assert "configured" in status_result.output.lower()


class TestModeCLI:
    def test_mode_set_mock_persists_workspace_preference_and_show_reports_mock(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        runner = CliRunner()
        monkeypatch.chdir(tmp_path)

        set_result = runner.invoke(cli, ["mode", "set", "mock"])
        assert set_result.exit_code == 0, set_result.output
        assert "Running in MOCK mode" in set_result.output

        workspace_payload = json.loads((tmp_path / ".agentlab" / "workspace.json").read_text(encoding="utf-8"))
        assert workspace_payload["mode"] == "mock"

        show_result = runner.invoke(cli, ["mode", "show"])
        assert show_result.exit_code == 0, show_result.output
        assert "Current mode: MOCK" in show_result.output
        assert "deterministic responses" in show_result.output

    def test_mode_set_live_requires_provider_credentials(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        runner = CliRunner()
        monkeypatch.chdir(tmp_path)
        env = {
            "OPENAI_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
            "GOOGLE_API_KEY": "",
        }

        result = runner.invoke(cli, ["mode", "set", "live"], env=env)

        assert result.exit_code != 0
        assert "Cannot enable live mode" in result.output

    def test_mode_set_live_succeeds_when_provider_credentials_exist(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        runner = CliRunner()
        monkeypatch.chdir(tmp_path)
        env = {"OPENAI_API_KEY": "sk-test"}

        result = runner.invoke(cli, ["mode", "set", "live"], env=env)

        assert result.exit_code == 0, result.output
        assert "Running in LIVE mode" in result.output

        show_result = runner.invoke(cli, ["mode", "show"], env=env)
        assert show_result.exit_code == 0, show_result.output
        assert "Current mode: LIVE" in show_result.output
        assert "OPENAI_API_KEY" in show_result.output

    def test_doctor_reports_workspace_mode_and_provider_configuration(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        runner = CliRunner()
        monkeypatch.chdir(tmp_path)
        config_path = tmp_path / "agentlab.yaml"
        config_path.write_text("optimizer:\n  use_mock: false\n", encoding="utf-8")

        set_result = runner.invoke(cli, ["mode", "set", "mock"])
        assert set_result.exit_code == 0, set_result.output

        doctor_result = runner.invoke(
            cli,
            ["doctor", "--config", str(config_path)],
            env={"OPENAI_API_KEY": ""},
        )

        assert doctor_result.exit_code == 0, doctor_result.output
        assert "Running in MOCK mode" in doctor_result.output
        assert "workspace preference" in doctor_result.output.lower()

    def test_provider_commands_use_runtime_configured_providers_without_registry(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Provider CLI status should agree with doctor/live-mode runtime readiness."""
        runner = CliRunner()
        workspace = tmp_path / "runtime-provider"
        env = {
            "OPENAI_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
            "GOOGLE_API_KEY": "g-test-key",
        }
        init_result = runner.invoke(
            cli,
            ["init", "--dir", str(workspace), "--mode", "live"],
            env=env,
        )
        assert init_result.exit_code == 0, init_result.output
        assert not (workspace / ".agentlab" / "providers.json").exists()

        monkeypatch.chdir(workspace)

        list_result = runner.invoke(cli, ["provider", "list"], env=env)
        assert list_result.exit_code == 0, list_result.output
        assert "google" in list_result.output.lower()
        assert "gemini-2.5-pro" in list_result.output
        assert "runtime config" in list_result.output.lower()

        test_result = runner.invoke(cli, ["provider", "test"], env=env)
        assert test_result.exit_code == 0, test_result.output
        assert "google:gemini-2.5-pro has credentials configured" in test_result.output
        assert "live probe not run" in test_result.output

    def test_provider_live_probe_redacts_rejected_provider_errors(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Live provider probes should expose access failures without leaking keys."""
        from optimizer import providers as optimizer_providers

        runner = CliRunner()
        workspace = tmp_path / "runtime-provider-live-probe"
        secret = "g-test-secret-1234567890"
        env = {
            "OPENAI_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
            "GOOGLE_API_KEY": secret,
        }
        init_result = runner.invoke(
            cli,
            ["init", "--dir", str(workspace), "--mode", "live"],
            env=env,
        )
        assert init_result.exit_code == 0, init_result.output

        def fail_generate(self: SimpleNamespace, request: object) -> object:
            raise RuntimeError(f"HTTP Error 403: {secret}")

        monkeypatch.setattr(optimizer_providers.LLMRouter, "generate", fail_generate)
        monkeypatch.chdir(workspace)

        result = runner.invoke(cli, ["provider", "test", "--live"], env=env)

        assert result.exit_code != 0, result.output
        assert "rejected the live probe" in result.output
        assert "Gemini API is enabled" in result.output
        assert secret not in result.output
        assert "[redacted]" in result.output
