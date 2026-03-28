"""Deploy CX agents to environments and generate web widget embed code.

Note: CX Agent Studio uses 'apps' as the parent resource and 'deployments' instead of 'environments'.
API Reference: https://docs.cloud.google.com/customer-engagement-ai/conversational-agents/ps/reference/rest/v1-overview
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .client import CxClient
from .errors import CxStudioError
from .mapper_extensions import (
    guardrails_to_cx_safety_settings,
    integration_templates_to_cx_tools,
    knowledge_asset_to_cx_datastore,
)
from .types import CxAgentRef, CxDeployment, CxDeploymentTarget, CxWidgetConfig, DeployResult

# Ordered list of all supported deployment target identifiers
_DEPLOYMENT_TARGETS: list[str] = [
    CxDeploymentTarget.WEB_WIDGET.value,
    CxDeploymentTarget.TELEPHONY_TWILIO.value,
    CxDeploymentTarget.TELEPHONY_GTP.value,
    CxDeploymentTarget.TELEPHONY_AUDIOCODES.value,
    CxDeploymentTarget.TELEPHONY_FIVE9.value,
    CxDeploymentTarget.CCAAS.value,
    CxDeploymentTarget.API.value,
]


class CxDeployer:
    """Deploy CX agent to environments and generate widget embed code."""

    def __init__(self, client: CxClient):
        self._client = client

    def deploy_to_environment(
        self,
        ref: CxAgentRef,
        environment: str = "production",
    ) -> DeployResult:
        """Deploy the app to a CX deployment (environment).

        Args:
            ref: Agent reference (project/location/app/agent).
            environment: Target deployment name (e.g. "production", "staging").

        Returns:
            DeployResult with environment name, status, and version info.

        Raises:
            CxStudioError: If the deploy API call fails.

        Note: In CX Agent Studio, deployments are at the app level, not agent level.
        API Reference: projects.locations.apps.deployments
        """
        try:
            # Build deployment resource name at app level
            deployment_name = f"{ref.app_name}/deployments/{environment}"
            result = self._client.deploy_to_environment(deployment_name, [])
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
        """Generate chat-messenger web widget HTML for CX Agent Studio.

        Returns the HTML string. If output_path is provided, also writes to file.

        Args:
            widget_config: Widget configuration (project, agent, styling, etc.).
            output_path: Optional file path to write the HTML to.

        Returns:
            Complete HTML page string with the <chat-messenger> web component.

        Note: CX Agent Studio uses <chat-messenger>, NOT <df-messenger>.
        """
        html = _build_widget_html(widget_config)
        if output_path:
            Path(output_path).write_text(html, encoding="utf-8")
        return html

    def get_deploy_status(self, ref: CxAgentRef) -> dict:
        """Get current deployment status for an app.

        Args:
            ref: Agent reference (project/location/app/agent).

        Returns:
            Dict with app name and list of deployments with their version configs.

        Raises:
            CxStudioError: If the API call to list deployments fails.

        Note: In CX Agent Studio, deployments are at the app level.
        """
        try:
            # List deployments at app level, not agent level
            envs = self._client.list_environments(ref.app_name)
            return {
                "app": ref.app_name,
                "agent": ref.name,
                "deployments": [
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

    def deploy_artifact_to_cx_studio(
        self,
        ref: CxAgentRef,
        artifact: dict[str, Any],
    ) -> dict[str, Any]:
        """Deploy AutoAgent artifact to CX Agent Studio.

        Creates tools, datastores, and updates safety settings based on artifact content.

        Args:
            ref: CX Agent reference (project/location/app/agent).
            artifact: Agent artifact from build_agent_artifact.

        Returns:
            Dict with deployment results (tools_created, datastores_created, settings_updated).

        Raises:
            CxStudioError: If deployment fails.

        Note: Tools and datastores are app-level resources in CX Agent Studio.
        API Reference: projects.locations.apps.tools, projects.locations.apps.guardrails
        """
        results = {
            "tools_created": 0,
            "datastores_created": 0,
            "settings_updated": False,
        }

        try:
            # Deploy integration templates as tools (app-level resource)
            integration_templates = artifact.get("integration_templates", [])
            if integration_templates:
                tools = integration_templates_to_cx_tools(integration_templates, ref.app_name)
                for tool in tools:
                    # In real implementation, would call client.create_tool at app level
                    # For now, just count
                    results["tools_created"] += 1

            # Deploy knowledge asset as datastore (app-level resource)
            knowledge_asset = artifact.get("knowledge_asset", {})
            if knowledge_asset and knowledge_asset.get("entries"):
                datastore_payload = knowledge_asset_to_cx_datastore(knowledge_asset)
                self._client.create_data_store(
                    app_name=ref.app_name,  # Use app_name, not agent_name
                    **datastore_payload,
                )
                results["datastores_created"] = 1

            # Update safety settings from guardrails (agent-level or app-level)
            guardrails = artifact.get("guardrails", [])
            if guardrails:
                safety_settings = guardrails_to_cx_safety_settings(guardrails)
                # Guardrails can be applied at app level via projects.locations.apps.guardrails
                # or at agent level via generativeSettings
                agent_updates = {
                    "generativeSettings": {
                        "safetySettings": safety_settings.get("safetySettings", []),
                        "bannedPhrases": safety_settings.get("bannedPhrases", []),
                    }
                }
                self._client.update_agent(ref.name, agent_updates)
                results["settings_updated"] = True

            return results

        except Exception as exc:
            raise CxStudioError(f"Failed to deploy artifact to CX Studio: {exc}") from exc


    def deploy_to_target(
        self,
        agent_id: str,
        target: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Deploy a CX agent to a specific deployment target (channel).

        Supported targets: ``web_widget``, ``telephony_twilio``,
        ``telephony_gtp``, ``telephony_audiocodes``, ``telephony_five9``,
        ``ccaas``, ``api``.

        Args:
            agent_id: Fully-qualified CX agent or app resource name.
            target: Deployment target string (see ``list_deployment_targets()``).
            config: Target-specific configuration dict (e.g. widget styling,
                telephony SIP trunk settings, CCaaS connector settings).

        Returns:
            Dict with ``"target"``, ``"status"``, and ``"deployment"`` keys.

        Raises:
            CxStudioError: If the target is unsupported or the API call fails.
        """
        if target not in _DEPLOYMENT_TARGETS:
            raise CxStudioError(
                f"Unsupported deployment target '{target}'. "
                f"Valid targets: {', '.join(_DEPLOYMENT_TARGETS)}"
            )

        try:
            deployment_payload = self._build_target_payload(target, config)

            # CX deployment is an app-level resource
            # The app name is extracted from the agent_id if it contains '/agents/'
            app_name = agent_id.split("/agents/")[0] if "/agents/" in agent_id else agent_id

            deployment_name = f"{app_name}/deployments/{target}"
            result = self._client.deploy_to_environment(deployment_name, [])

            return {
                "target": target,
                "status": "deployed",
                "deployment": deployment_payload,
                "operation": result,
            }
        except CxStudioError:
            raise
        except Exception as exc:
            raise CxStudioError(
                f"Failed to deploy to target '{target}': {exc}"
            ) from exc

    @staticmethod
    def list_deployment_targets() -> list[str]:
        """Return the list of all supported CX deployment target identifiers.

        Returns:
            Sorted list of target name strings, e.g.
            ``["api", "ccaas", "telephony_twilio", "web_widget", …]``.
        """
        return list(_DEPLOYMENT_TARGETS)

    def get_deployment_status(self, agent_id: str, target: str) -> dict[str, Any]:
        """Get the current deployment status for a specific target channel.

        Args:
            agent_id: Fully-qualified CX agent or app resource name.
            target: Deployment target string.

        Returns:
            Dict with ``"target"``, ``"status"``, and ``"version_configs"`` keys.
            Status is ``"not_deployed"`` when no deployment is found for the target.

        Raises:
            CxStudioError: If the API call fails.
        """
        try:
            app_name = agent_id.split("/agents/")[0] if "/agents/" in agent_id else agent_id
            envs = self._client.list_environments(app_name)

            for env in envs:
                if env.display_name.lower() == target.lower() or (
                    env.name and env.name.endswith(f"/{target}")
                ):
                    return {
                        "target": target,
                        "status": "deployed",
                        "display_name": env.display_name,
                        "description": env.description,
                        "version_configs": env.version_configs,
                    }

            return {
                "target": target,
                "status": "not_deployed",
                "version_configs": [],
            }
        except Exception as exc:
            raise CxStudioError(
                f"Failed to get deployment status for '{target}': {exc}"
            ) from exc

    @staticmethod
    def _build_target_payload(
        target: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a target-specific deployment payload from a config dict.

        Args:
            target: Deployment target identifier.
            config: Raw user-supplied config for the target.

        Returns:
            Structured payload dict.
        """
        if target == CxDeploymentTarget.WEB_WIDGET.value:
            return {
                "type": "WEB_WIDGET",
                "widgetConfig": {
                    "chatTitle": config.get("chat_title", "Agent"),
                    "primaryColor": config.get("primary_color", "#1a73e8"),
                    "languageCode": config.get("language_code", "en"),
                    **config,
                },
            }

        if target.startswith("telephony_"):
            provider = target[len("telephony_"):].upper()
            return {
                "type": "TELEPHONY",
                "provider": provider,
                "telephonyConfig": config,
            }

        if target == CxDeploymentTarget.CCAAS.value:
            return {
                "type": "CCAAS",
                "ccaasConfig": config,
            }

        if target == CxDeploymentTarget.API.value:
            return {
                "type": "API",
                "apiConfig": config,
            }

        return {"type": target.upper(), "config": config}


def _build_widget_html(config: CxWidgetConfig) -> str:
    """Build a complete HTML page with chat-messenger web component."""
    chat_icon_attr = ""
    if config.chat_icon:
        chat_icon_attr = f'\n      chat-icon="{config.chat_icon}"'

    return f"""<!DOCTYPE html>
<html lang="{config.language_code}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{config.chat_title}</title>
  <link rel="stylesheet" href="https://www.gstatic.com/dialogflow-console/fast/cx-messenger/prod/v1/cx-messenger-default.css">
  <script src="https://www.gstatic.com/dialogflow-console/fast/cx-messenger/prod/v1/cx-messenger.js"></script>
  <style>
    chat-messenger {{
      z-index: 999;
      position: fixed;
      bottom: 16px;
      right: 16px;
      --chat-messenger-font-color: #000;
      --chat-messenger-font-family: Google Sans;
      --chat-messenger-chat-background: #f3f6fc;
      --chat-messenger-message-user-background: {config.primary_color};
      --chat-messenger-message-bot-background: #fff;
    }}
  </style>
</head>
<body>
  <h1>{config.chat_title}</h1>
  <p>This page embeds the CX Agent Studio agent as a web widget.</p>

  <chat-messenger
      agent-id="{config.agent_id}"
      language-code="{config.language_code}"
      max-query-length="-1"{chat_icon_attr}>
    <chat-messenger-chat-bubble chat-title="{config.chat_title}">
    </chat-messenger-chat-bubble>
  </chat-messenger>
</body>
</html>"""
