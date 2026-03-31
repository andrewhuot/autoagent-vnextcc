"""Generic HTTP webhook adapter for external agent endpoints."""

from __future__ import annotations

from urllib.parse import urlparse

from .base import AgentAdapter, ImportedAgentSpec


class HttpWebhookAdapter(AgentAdapter):
    """Wrap an arbitrary HTTP endpoint as an AutoAgent import source."""

    adapter_name = "http"
    platform_name = "HTTP Webhook"

    def discover(self) -> ImportedAgentSpec:
        """Return a minimal live-runtime spec for the webhook endpoint."""

        parsed = urlparse(self.source)
        agent_name = parsed.netloc or "http-agent"
        spec = ImportedAgentSpec(
            adapter=self.adapter_name,
            source=self.source,
            agent_name=agent_name,
            platform=self.platform_name,
            adapter_config={
                "adapter": self.adapter_name,
                "base_url": self.source,
                "transport": "http",
            },
            metadata={"hostname": parsed.netloc, "path": parsed.path},
        )
        spec.ensure_defaults()
        spec.config["adapter"] = {"type": self.adapter_name, "base_url": self.source}
        return spec

    def import_traces(self) -> list[dict]:
        """HTTP webhooks do not provide transcript history by default."""

        return []

    def import_tools(self) -> list[dict]:
        """HTTP webhooks do not expose tools by default."""

        return []

    def import_guardrails(self) -> list[dict]:
        """HTTP webhooks do not expose guardrails by default."""

        return []
