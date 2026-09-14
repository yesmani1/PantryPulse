"""Start, stop, or inspect the UAT PantryPulse deployed demo safely."""

from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass
from typing import Any

import boto3
from dotenv import load_dotenv


@dataclass(frozen=True)
class AppResources:
    function_name: str
    schedule_rule: str
    webhook_url: str
    token: str
    webhook_secret: str
    region: str = "us-west-2"


def resources() -> AppResources:
    load_dotenv()
    values = AppResources(
        function_name=os.getenv("PANTRYPULSE_LAMBDA_NAME", "pantrypulse-uat-bot"),
        schedule_rule=os.getenv("PANTRYPULSE_SCHEDULE_NAME", "pantrypulse-uat-daily"),
        webhook_url=os.getenv("PANTRYPULSE_WEBHOOK_URL", "").strip(),
        token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        webhook_secret=os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip(),
    )
    if not values.webhook_url or not values.token or not values.webhook_secret:
        raise RuntimeError("PANTRYPULSE_WEBHOOK_URL, TELEGRAM_BOT_TOKEN, and TELEGRAM_WEBHOOK_SECRET must be set in ignored .env.")
    return values


def status(lambda_client: Any, events_client: Any, cfg: AppResources) -> None:
    concurrency = lambda_client.get_function_concurrency(FunctionName=cfg.function_name).get("ReservedConcurrentExecutions", "unreserved")
    rule = events_client.describe_rule(Name=cfg.schedule_rule)
    print(f"lambda_concurrency={concurrency}")
    print(f"schedule_state={rule['State']}")


async def start(lambda_client: Any, events_client: Any, telegram: Any, cfg: AppResources) -> None:
    events_client.enable_rule(Name=cfg.schedule_rule)
    await telegram.set_webhook(url=cfg.webhook_url, drop_pending_updates=True, secret_token=cfg.webhook_secret)
    print("UAT app started: schedule enabled and webhook configured.")


async def stop(lambda_client: Any, events_client: Any, telegram: Any, cfg: AppResources) -> None:
    events_client.disable_rule(Name=cfg.schedule_rule)
    await telegram.delete_webhook(drop_pending_updates=False)
    print("UAT app stopped: schedule disabled and webhook removed. DynamoDB data remains.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--start", action="store_true")
    action.add_argument("--stop", action="store_true")
    action.add_argument("--status", action="store_true")
    parser.add_argument("--apply", action="store_true", help="perform the requested start/stop action")
    args = parser.parse_args()
    cfg = resources()
    if not args.apply and not args.status:
        print(f"Dry run: would {'start' if args.start else 'stop'} {cfg.function_name}; pass --apply to change AWS resources.")
        return
    session = boto3.Session(region_name=cfg.region)
    lambda_client, events_client = session.client("lambda"), session.client("events")
    from telegram import Bot
    telegram = Bot(token=cfg.token)
    if args.status:
        status(lambda_client, events_client, cfg)
    elif args.start:
        asyncio.run(start(lambda_client, events_client, telegram, cfg))
    else:
        asyncio.run(stop(lambda_client, events_client, telegram, cfg))


if __name__ == "__main__":
    main()
