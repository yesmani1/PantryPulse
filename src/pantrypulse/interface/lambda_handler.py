"""AWS Lambda entry point for Telegram webhook and scheduled UAT events."""

from __future__ import annotations

import asyncio
import hmac
import json
import os
from typing import Any

import boto3
from telegram import Update

from pantrypulse.interface.bot import build_app
from pantrypulse.interface.config import ModelProvider, Settings


def _parameter_value(parameter: str) -> str:
    if not parameter:
        raise RuntimeError("A required SSM parameter ARN is missing in Lambda.")
    return boto3.client("ssm", region_name=os.getenv("BEDROCK_REGION", "us-west-2")).get_parameter(
        Name=parameter, WithDecryption=True
    )["Parameter"]["Value"]


def _settings() -> Settings:
    token = _parameter_value(os.getenv("TELEGRAM_TOKEN_PARAMETER_ARN", ""))
    return Settings(
        telegram_bot_token=token,
        model_provider=ModelProvider(os.getenv("MODEL_PROVIDER", "bedrock")),
        bedrock_region=os.getenv("BEDROCK_REGION", "us-west-2"),
        bedrock_text_model=os.getenv("BEDROCK_TEXT_MODEL", "us.anthropic.claude-sonnet-4-6"),
        bedrock_vision_model=os.getenv("BEDROCK_VISION_MODEL", "us.anthropic.claude-haiku-4-5-20251001-v1:0"),
    )


def _webhook_secret() -> str:
    return _parameter_value(os.getenv("TELEGRAM_WEBHOOK_SECRET_PARAMETER_ARN", ""))


def _is_authorized(event: dict[str, Any]) -> bool:
    headers = event.get("headers") or {}
    supplied = next(
        (str(value) for name, value in headers.items() if name.lower() == "x-telegram-bot-api-secret-token"),
        "",
    )
    return hmac.compare_digest(supplied, _webhook_secret())


async def _process_webhook(payload: dict[str, Any]) -> None:
    app = build_app(_settings())
    await app.initialize()
    try:
        await app.process_update(Update.de_json(payload, app.bot))
    finally:
        await app.shutdown()


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    """Return API Gateway-compatible acknowledgement without exposing failures."""
    if event.get("source") == "pantrypulse.schedule":
        # Household scheduling is enabled only after an operator adds the
        # recipient-discovery job; acknowledging prevents EventBridge retries.
        return {"statusCode": 202, "body": "scheduled check acknowledged"}
    if not _is_authorized(event):
        return {"statusCode": 401, "body": "unauthorized"}
    body = event.get("body", event)
    if isinstance(body, str):
        body = json.loads(body)
    asyncio.run(_process_webhook(body))
    return {"statusCode": 200, "body": "ok"}
