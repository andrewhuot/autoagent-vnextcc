"""Tests for notification system — manager, channels, subscriptions."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from notifications.manager import NotificationManager, Subscription, VALID_EVENT_TYPES
from notifications.channels import WebhookChannel, SlackChannel, EmailChannel


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
        db_path = f.name
    yield db_path
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def notification_manager(temp_db):
    """Create a NotificationManager for testing."""
    return NotificationManager(db_path=temp_db)


class TestNotificationManager:
    """Test NotificationManager class."""

    def test_init_creates_db(self, temp_db):
        """Test that initialization creates the database."""
        manager = NotificationManager(db_path=temp_db)
        assert Path(temp_db).exists()

    def test_register_webhook(self, notification_manager):
        """Test webhook registration."""
        subscription_id = notification_manager.register_webhook(
            url="https://example.com/webhook",
            events=["health_drop", "deployment"],
            filters={"severity": "warning"},
        )

        assert subscription_id.startswith("webhook_")

        # Verify subscription was saved
        subscriptions = notification_manager.list_subscriptions()
        assert len(subscriptions) == 1
        assert subscriptions[0].id == subscription_id
        assert subscriptions[0].channel_type == "webhook"
        assert subscriptions[0].config["url"] == "https://example.com/webhook"
        assert set(subscriptions[0].events) == {"health_drop", "deployment"}
        assert subscriptions[0].filters["severity"] == "warning"

    def test_register_slack(self, notification_manager):
        """Test Slack registration."""
        subscription_id = notification_manager.register_slack(
            webhook_url="https://hooks.slack.com/services/xxx",
            events=["safety_violation"],
        )

        assert subscription_id.startswith("slack_")

        subscriptions = notification_manager.list_subscriptions()
        assert len(subscriptions) == 1
        assert subscriptions[0].channel_type == "slack"
        assert subscriptions[0].config["webhook_url"] == "https://hooks.slack.com/services/xxx"

    def test_register_email(self, notification_manager):
        """Test email registration."""
        subscription_id = notification_manager.register_email(
            address="test@example.com",
            events=["daily_summary"],
            smtp_config={"smtp_host": "localhost", "smtp_port": "25"},
        )

        assert subscription_id.startswith("email_")

        subscriptions = notification_manager.list_subscriptions()
        assert len(subscriptions) == 1
        assert subscriptions[0].channel_type == "email"
        assert subscriptions[0].config["address"] == "test@example.com"
        assert subscriptions[0].config["smtp_host"] == "localhost"

    def test_delete_subscription(self, notification_manager):
        """Test subscription deletion."""
        subscription_id = notification_manager.register_webhook(
            url="https://example.com/webhook",
            events=["health_drop"],
        )

        assert len(notification_manager.list_subscriptions()) == 1

        success = notification_manager.delete_subscription(subscription_id)
        assert success is True
        assert len(notification_manager.list_subscriptions()) == 0

    def test_delete_nonexistent_subscription(self, notification_manager):
        """Test deleting a non-existent subscription."""
        success = notification_manager.delete_subscription("nonexistent_id")
        assert success is False

    def test_get_subscription(self, notification_manager):
        """Test getting a specific subscription."""
        subscription_id = notification_manager.register_webhook(
            url="https://example.com/webhook",
            events=["health_drop"],
        )

        subscription = notification_manager.get_subscription(subscription_id)
        assert subscription is not None
        assert subscription.id == subscription_id
        assert subscription.channel_type == "webhook"

    def test_get_nonexistent_subscription(self, notification_manager):
        """Test getting a non-existent subscription."""
        subscription = notification_manager.get_subscription("nonexistent_id")
        assert subscription is None

    @patch.object(WebhookChannel, 'send')
    def test_send_webhook_notification(self, mock_send, notification_manager):
        """Test sending a webhook notification."""
        subscription_id = notification_manager.register_webhook(
            url="https://example.com/webhook",
            events=["health_drop"],
        )

        payload = {"metric": "success_rate", "old_value": 0.9, "new_value": 0.7}
        notification_manager.send("health_drop", payload)

        mock_send.assert_called_once()
        assert mock_send.call_args[0][0]["url"] == "https://example.com/webhook"
        assert mock_send.call_args[0][1] == "health_drop"
        assert mock_send.call_args[0][2] == payload

    @patch.object(SlackChannel, 'send')
    def test_send_slack_notification(self, mock_send, notification_manager):
        """Test sending a Slack notification."""
        notification_manager.register_slack(
            webhook_url="https://hooks.slack.com/services/xxx",
            events=["safety_violation"],
        )

        payload = {"violation_type": "unauthorized_access", "details": "User tried to access admin API"}
        notification_manager.send("safety_violation", payload)

        mock_send.assert_called_once()

    def test_send_invalid_event_type(self, notification_manager):
        """Test sending with an invalid event type."""
        with pytest.raises(ValueError, match="Invalid event type"):
            notification_manager.send("invalid_event", {})

    def test_send_respects_event_filter(self, notification_manager):
        """Test that notifications respect event filters."""
        # Register subscription for deployment events only
        notification_manager.register_webhook(
            url="https://example.com/webhook",
            events=["deployment"],
        )

        with patch.object(WebhookChannel, 'send') as mock_send:
            # Send health_drop event — should not trigger
            notification_manager.send("health_drop", {})
            mock_send.assert_not_called()

            # Send deployment event — should trigger
            notification_manager.send("deployment", {})
            mock_send.assert_called_once()

    def test_send_respects_severity_filter(self, notification_manager):
        """Test that notifications respect severity filters."""
        notification_manager.register_webhook(
            url="https://example.com/webhook",
            events=["health_drop"],
            filters={"severity": "error"},
        )

        with patch.object(WebhookChannel, 'send') as mock_send:
            # Send info-level event — should not trigger
            notification_manager.send("health_drop", {"severity": "info"})
            mock_send.assert_not_called()

            # Send error-level event — should trigger
            notification_manager.send("health_drop", {"severity": "error"})
            assert mock_send.call_count == 1

            # Send critical-level event — should trigger
            notification_manager.send("health_drop", {"severity": "critical"})
            assert mock_send.call_count == 2

    def test_disabled_subscription_does_not_send(self, notification_manager):
        """Test that disabled subscriptions do not send notifications."""
        subscription_id = notification_manager.register_webhook(
            url="https://example.com/webhook",
            events=["health_drop"],
        )

        # Disable the subscription
        subscription = notification_manager.get_subscription(subscription_id)
        assert subscription is not None
        subscription.enabled = False
        notification_manager._save_subscription(subscription)

        with patch.object(WebhookChannel, 'send') as mock_send:
            notification_manager.send("health_drop", {})
            mock_send.assert_not_called()

    def test_notification_history_logged(self, notification_manager):
        """Test that notification attempts are logged."""
        notification_manager.register_webhook(
            url="https://example.com/webhook",
            events=["health_drop"],
        )

        with patch.object(WebhookChannel, 'send'):
            notification_manager.send("health_drop", {"message": "Test message"})

        history = notification_manager.get_notification_history(limit=10)
        assert len(history) == 1
        assert history[0]["event_type"] == "health_drop"
        assert history[0]["success"] is True
        assert "message" in history[0]["payload"]

    def test_notification_failure_logged(self, notification_manager):
        """Test that notification failures are logged."""
        notification_manager.register_webhook(
            url="https://example.com/webhook",
            events=["health_drop"],
        )

        with patch.object(WebhookChannel, 'send', side_effect=Exception("Connection error")):
            notification_manager.send("health_drop", {"message": "Test message"})

        history = notification_manager.get_notification_history(limit=10)
        assert len(history) == 1
        assert history[0]["success"] is False
        assert history[0]["error"] == "Connection error"

    def test_test_subscription_success(self, notification_manager):
        """Test sending a test notification."""
        subscription_id = notification_manager.register_webhook(
            url="https://example.com/webhook",
            events=["health_drop"],
        )

        with patch.object(WebhookChannel, 'send'):
            success, error = notification_manager.test_subscription(subscription_id)
            assert success is True
            assert error is None

    def test_test_subscription_failure(self, notification_manager):
        """Test test notification failure."""
        subscription_id = notification_manager.register_webhook(
            url="https://example.com/webhook",
            events=["health_drop"],
        )

        with patch.object(WebhookChannel, 'send', side_effect=Exception("Test error")):
            success, error = notification_manager.test_subscription(subscription_id)
            assert success is False
            assert error == "Test error"

    def test_test_nonexistent_subscription(self, notification_manager):
        """Test testing a non-existent subscription."""
        success, error = notification_manager.test_subscription("nonexistent_id")
        assert success is False
        assert error == "Subscription not found"


class TestWebhookChannel:
    """Test WebhookChannel class."""

    @patch('notifications.channels.requests')
    def test_send_webhook(self, mock_requests):
        """Test sending a webhook notification."""
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_requests.post.return_value = mock_response

        channel = WebhookChannel()
        config = {"url": "https://example.com/webhook"}
        payload = {"message": "Test notification"}

        channel.send(config, "health_drop", payload)

        mock_requests.post.assert_called_once()
        call_args = mock_requests.post.call_args
        assert call_args[0][0] == "https://example.com/webhook"
        assert call_args[1]["json"]["event_type"] == "health_drop"
        assert call_args[1]["json"]["payload"] == payload


class TestSlackChannel:
    """Test SlackChannel class."""

    @patch('notifications.channels.requests')
    def test_send_slack(self, mock_requests):
        """Test sending a Slack notification."""
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_requests.post.return_value = mock_response

        channel = SlackChannel()
        config = {"webhook_url": "https://hooks.slack.com/services/xxx"}
        payload = {"message": "Test notification"}

        channel.send(config, "health_drop", payload)

        mock_requests.post.assert_called_once()
        call_args = mock_requests.post.call_args
        assert call_args[0][0] == "https://hooks.slack.com/services/xxx"
        assert "blocks" in call_args[1]["json"]

    def test_format_slack_blocks(self):
        """Test Slack block formatting."""
        channel = SlackChannel()
        payload = {
            "message": "Health drop detected",
            "metric": "success_rate",
            "old_value": 0.9,
            "new_value": 0.7,
        }

        blocks = channel._format_slack_blocks("health_drop", payload)

        assert len(blocks) > 0
        assert blocks[0]["type"] == "header"
        assert "Health Drop" in blocks[0]["text"]["text"]


class TestEmailChannel:
    """Test EmailChannel class."""

    @patch('notifications.channels.smtplib.SMTP')
    def test_send_email(self, mock_smtp):
        """Test sending an email notification."""
        mock_smtp_instance = Mock()
        mock_smtp.return_value.__enter__.return_value = mock_smtp_instance

        channel = EmailChannel()
        config = {
            "address": "test@example.com",
            "from_address": "autoagent@localhost",
        }
        payload = {"message": "Test notification"}

        channel.send(config, "health_drop", payload)

        mock_smtp_instance.send_message.assert_called_once()

    def test_format_email_body(self):
        """Test email body formatting."""
        channel = EmailChannel()
        payload = {
            "message": "Health drop detected",
            "metric": "success_rate",
            "old_value": 0.9,
        }

        body = channel._format_email_body("health_drop", payload)

        assert "Health Drop" in body
        assert "Health drop detected" in body
        assert "success_rate" in body
