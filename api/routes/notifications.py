"""Notification subscription and management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class WebhookSubscriptionRequest(BaseModel):
    """Request to register a webhook subscription."""

    url: str
    events: list[str]
    filters: dict[str, str] | None = None


class SlackSubscriptionRequest(BaseModel):
    """Request to register a Slack subscription."""

    webhook_url: str
    events: list[str]
    filters: dict[str, str] | None = None


class EmailSubscriptionRequest(BaseModel):
    """Request to register an email subscription."""

    address: str
    events: list[str]
    filters: dict[str, str] | None = None
    smtp_config: dict[str, str] | None = None


@router.post("/webhook")
async def register_webhook(request: Request, body: WebhookSubscriptionRequest) -> dict:
    """Register a webhook subscription."""
    notification_manager = request.app.state.notification_manager
    subscription_id = notification_manager.register_webhook(
        url=body.url, events=body.events, filters=body.filters or {}
    )
    return {"subscription_id": subscription_id, "status": "registered"}


@router.post("/slack")
async def register_slack(request: Request, body: SlackSubscriptionRequest) -> dict:
    """Register a Slack subscription."""
    notification_manager = request.app.state.notification_manager
    subscription_id = notification_manager.register_slack(
        webhook_url=body.webhook_url, events=body.events, filters=body.filters or {}
    )
    return {"subscription_id": subscription_id, "status": "registered"}


@router.post("/email")
async def register_email(request: Request, body: EmailSubscriptionRequest) -> dict:
    """Register an email subscription."""
    notification_manager = request.app.state.notification_manager
    subscription_id = notification_manager.register_email(
        address=body.address,
        events=body.events,
        filters=body.filters or {},
        smtp_config=body.smtp_config or {},
    )
    return {"subscription_id": subscription_id, "status": "registered"}


@router.get("/subscriptions")
async def list_subscriptions(request: Request) -> dict:
    """List all notification subscriptions."""
    notification_manager = request.app.state.notification_manager
    subscriptions = notification_manager.list_subscriptions()

    return {
        "subscriptions": [
            {
                "id": sub.id,
                "channel_type": sub.channel_type,
                "config": sub.config,
                "events": sub.events,
                "filters": sub.filters,
                "enabled": sub.enabled,
                "created_at": sub.created_at,
            }
            for sub in subscriptions
        ]
    }


@router.delete("/subscriptions/{subscription_id}")
async def delete_subscription(request: Request, subscription_id: str) -> dict:
    """Delete a notification subscription."""
    notification_manager = request.app.state.notification_manager
    success = notification_manager.delete_subscription(subscription_id)

    if not success:
        raise HTTPException(status_code=404, detail="Subscription not found")

    return {"status": "deleted"}


@router.post("/test/{subscription_id}")
async def test_subscription(request: Request, subscription_id: str) -> dict:
    """Send a test notification to a subscription."""
    notification_manager = request.app.state.notification_manager
    success, error = notification_manager.test_subscription(subscription_id)

    if not success:
        raise HTTPException(status_code=400, detail=error or "Test failed")

    return {"status": "sent", "message": "Test notification sent successfully"}


@router.get("/history")
async def get_notification_history(
    request: Request, limit: int = Query(100, ge=1, le=1000)
) -> dict:
    """Get notification history."""
    notification_manager = request.app.state.notification_manager
    history = notification_manager.get_notification_history(limit=limit)
    return {"history": history}
