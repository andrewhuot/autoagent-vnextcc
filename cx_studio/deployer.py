"""Deploy CX agents to environments and generate web widget embed code."""
from __future__ import annotations

from pathlib import Path

from .client import CxClient
from .errors import CxStudioError
from .types import CxAgentRef, CxWidgetConfig, DeployResult


class CxDeployer:
    """Deploy CX agent to environments and generate widget embed code."""

    def __init__(self, client: CxClient):
        self._client = client

    def deploy_to_environment(
        self,
        ref: CxAgentRef,
        environment: str = "production",
    ) -> DeployResult:
        """Deploy the agent to a CX environment.

        Args:
            ref: Agent reference (project/location/agent).
            environment: Target environment name (e.g. "production", "staging").

        Returns:
            DeployResult with environment name, status, and version info.

        Raises:
            CxStudioError: If the deploy API call fails.
        """
        try:
            result = self._client.deploy_to_environment(ref, environment)
            return DeployResult(
                environment=environment,
                status="deployed",
                version_info=result,
            )
        except Exception as exc:
            raise CxStudioError(f"Deploy to {environment} failed: {exc}") from exc

    def generate_widget_html(
        self,
        widget_config: CxWidgetConfig,
        output_path: str | None = None,
    ) -> str:
        """Generate df-messenger web widget HTML.

        Returns the HTML string. If output_path is provided, also writes to file.

        Args:
            widget_config: Widget configuration (project, agent, styling, etc.).
            output_path: Optional file path to write the HTML to.

        Returns:
            Complete HTML page string with the df-messenger embed.
        """
        html = _build_widget_html(widget_config)
        if output_path:
            Path(output_path).write_text(html, encoding="utf-8")
        return html

    def get_deploy_status(self, ref: CxAgentRef) -> dict:
        """Get current deployment status for an agent.

        Args:
            ref: Agent reference (project/location/agent).

        Returns:
            Dict with agent name and list of environments with their version configs.

        Raises:
            CxStudioError: If the API call to list environments fails.
        """
        try:
            envs = self._client.list_environments(ref)
            return {
                "agent": ref.name,
                "environments": [
                    {
                        "name": env.display_name,
                        "description": env.description,
                        "versions": env.version_configs,
                    }
                    for env in envs
                ],
            }
        except Exception as exc:
            raise CxStudioError(f"Failed to get deploy status: {exc}") from exc


def _build_widget_html(config: CxWidgetConfig) -> str:
    """Build a complete HTML page with df-messenger web component."""
    chat_icon_attr = ""
    if config.chat_icon:
        chat_icon_attr = f'\n      chat-icon="{config.chat_icon}"'

    return f"""<!DOCTYPE html>
<html lang="{config.language_code}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{config.chat_title}</title>
  <link rel="stylesheet" href="https://www.gstatic.com/dialogflow-console/fast/df-messenger/prod/v1/themes/df-messenger-default.css">
  <script src="https://www.gstatic.com/dialogflow-console/fast/df-messenger/prod/v1/df-messenger.js"></script>
  <style>
    df-messenger {{
      z-index: 999;
      position: fixed;
      bottom: 16px;
      right: 16px;
      --df-messenger-font-color: #000;
      --df-messenger-font-family: Google Sans;
      --df-messenger-chat-background: #f3f6fc;
      --df-messenger-message-user-background: {config.primary_color};
      --df-messenger-message-bot-background: #fff;
    }}
  </style>
</head>
<body>
  <h1>{config.chat_title}</h1>
  <p>This page embeds the CX Agent Studio agent as a web widget.</p>

  <df-messenger
      project-id="{config.project_id}"
      agent-id="{config.agent_id}"
      language-code="{config.language_code}"
      max-query-length="-1"{chat_icon_attr}>
    <df-messenger-chat-bubble chat-title="{config.chat_title}">
    </df-messenger-chat-bubble>
  </df-messenger>
</body>
</html>"""
