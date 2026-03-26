"""Notification channel implementations — webhook, Slack, email."""

from __future__ import annotations

import json
import smtplib
from email.message import EmailMessage
from typing import Any

try:
    import requests
except ImportError:
    requests = None  # type: ignore


class WebhookChannel:
    """Webhook notification channel — POSTs JSON to a URL."""

    def send(self, config: dict[str, Any], event_type: str, payload: dict[str, Any]) -> None:
        """Send webhook notification."""
        if requests is None:
            raise RuntimeError("requests library not installed. Install with: pip install requests")

        url = config["url"]
        data = {
            "event_type": event_type,
            "payload": payload,
            "source": "autoagent",
        }

        response = requests.post(
            url,
            json=data,
            headers={"Content-Type": "application/json", "User-Agent": "AutoAgent/1.0"},
            timeout=10,
        )
        response.raise_for_status()


class SlackChannel:
    """Slack notification channel — posts formatted blocks to Slack webhook."""

    def send(self, config: dict[str, Any], event_type: str, payload: dict[str, Any]) -> None:
        """Send Slack notification with formatted blocks."""
        if requests is None:
            raise RuntimeError("requests library not installed. Install with: pip install requests")

        webhook_url = config["webhook_url"]
        blocks = self._format_slack_blocks(event_type, payload)

        response = requests.post(
            webhook_url,
            json={"blocks": blocks},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        response.raise_for_status()

    def _format_slack_blocks(self, event_type: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Format payload as Slack blocks."""
        icon_map = {
            "health_drop": ":chart_with_downwards_trend:",
            "optimization_complete": ":white_check_mark:",
            "deployment": ":rocket:",
            "safety_violation": ":warning:",
            "daily_summary": ":bar_chart:",
            "weekly_summary": ":calendar:",
            "new_opportunity": ":bulb:",
            "gate_failure": ":x:",
            "test": ":test_tube:",
        }

        icon = icon_map.get(event_type, ":bell:")
        title = event_type.replace("_", " ").title()

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"{icon} AutoAgent: {title}"},
            },
            {"type": "divider"},
        ]

        # Add payload fields
        fields = []
        for key, value in payload.items():
            if key == "message":
                # Message gets its own section
                blocks.append(
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f"*Message:*\n{value}"},
                    }
                )
            elif isinstance(value, (str, int, float, bool)):
                fields.append({"type": "mrkdwn", "text": f"*{key.replace('_', ' ').title()}:*\n{value}"})

        if fields:
            # Slack blocks support max 10 fields, split if needed
            for i in range(0, len(fields), 10):
                blocks.append({"type": "section", "fields": fields[i : i + 10]})

        return blocks


class EmailChannel:
    """Email notification channel — sends emails via SMTP."""

    def send(self, config: dict[str, Any], event_type: str, payload: dict[str, Any]) -> None:
        """Send email notification."""
        to_address = config["address"]
        subject = f"AutoAgent Alert: {event_type.replace('_', ' ').title()}"
        body = self._format_email_body(event_type, payload)

        # SMTP configuration (defaults to localhost for testing)
        smtp_host = config.get("smtp_host", "localhost")
        smtp_port = config.get("smtp_port", 25)
        smtp_user = config.get("smtp_user")
        smtp_password = config.get("smtp_password")
        from_address = config.get("from_address", "autoagent@localhost")

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = from_address
        msg["To"] = to_address
        msg.set_content(body)

        # Send email
        with smtplib.SMTP(smtp_host, smtp_port) as smtp:
            if smtp_user and smtp_password:
                smtp.login(smtp_user, smtp_password)
            smtp.send_message(msg)

    def _format_email_body(self, event_type: str, payload: dict[str, Any]) -> str:
        """Format payload as email body."""
        lines = [
            f"AutoAgent Alert: {event_type.replace('_', ' ').title()}",
            "=" * 60,
            "",
        ]

        if "message" in payload:
            lines.append(payload["message"])
            lines.append("")

        lines.append("Details:")
        for key, value in payload.items():
            if key != "message":
                lines.append(f"  {key.replace('_', ' ').title()}: {value}")

        lines.append("")
        lines.append("--")
        lines.append("Sent by AutoAgent")

        return "\n".join(lines)
