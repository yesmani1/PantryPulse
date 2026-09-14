"""Cost-guarded provisioning for PantryPulse DynamoDB tables."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv


EXPECTED_ACCOUNT_ID = "470044069054"
PROJECT_BUDGET_USD = Decimal("100")
REQUIRED_ALERT_THRESHOLDS = {50, 80, 100}
REQUIRED_TAGS = {
    "Project": "pantrypulse",
    "Environment": "uat",
    "ManagedBy": "pantrypulse-boto3",
}


@dataclass(frozen=True)
class TableSpec:
    """The immutable key design for one PantryPulse DynamoDB table."""

    name: str
    keys: tuple[str, ...]


TABLE_SPECS = (
    TableSpec("pantrypulse-uat-pantry-items", ("household_id", "item_id")),
    TableSpec("pantrypulse-uat-households", ("household_id",)),
    TableSpec("pantrypulse-uat-feedback-log", ("household_id", "event_id")),
)


def create_aws_session(*, profile_name: str | None, region_name: str) -> boto3.Session:
    """Load local configuration and create a session without exposing secrets.

    With no profile, Boto3's normal credential chain reads AWS values loaded
    from the ignored .env file. A named profile remains available as an
    explicit operator override.
    """
    load_dotenv()
    session_args: dict[str, str] = {"region_name": region_name}
    if profile_name:
        session_args["profile_name"] = profile_name
    return boto3.Session(**session_args)


def table_names() -> tuple[str, ...]:
    """Return the UAT tables managed by this provisioner."""
    return tuple(spec.name for spec in TABLE_SPECS)


def verify_cost_guardrails(sts_client: Any, budgets_client: Any) -> str:
    """Require the expected account and existing $100/50-80-100 budget policy."""
    identity = sts_client.get_caller_identity()
    account_id = identity["Account"]
    if account_id != EXPECTED_ACCOUNT_ID:
        raise RuntimeError(
            f"Refusing to provision account {account_id}; expected {EXPECTED_ACCOUNT_ID}."
        )

    budgets = budgets_client.describe_budgets(AccountId=account_id).get("Budgets", [])
    budget = next(
        (
            candidate
            for candidate in budgets
            if Decimal(candidate.get("BudgetLimit", {}).get("Amount", "0"))
            == PROJECT_BUDGET_USD
            and "pantrypulse" in candidate["BudgetName"].lower()
        ),
        None,
    )
    if budget is None:
        raise RuntimeError("No PantryPulse $100 cost budget was found.")

    budget_name = budget["BudgetName"]
    notifications = budgets_client.describe_notifications_for_budget(
        AccountId=account_id, BudgetName=budget_name
    ).get("Notifications", [])
    thresholds = {
        int(notification["Threshold"])
        for notification in notifications
        if notification.get("NotificationType") == "ACTUAL"
    }
    if not REQUIRED_ALERT_THRESHOLDS.issubset(thresholds):
        raise RuntimeError(
            "PantryPulse budget must have actual-spend alerts at 50%, 80%, and 100%."
        )

    actions = budgets_client.describe_budget_actions_for_budget(
        AccountId=account_id, BudgetName=budget_name
    ).get("Actions", [])
    has_emergency_deny = any(
        action.get("ActionType") == "APPLY_IAM_POLICY"
        and action.get("ActionThreshold", {}).get("ActionThresholdType")
        == "PERCENTAGE"
        and Decimal(str(action.get("ActionThreshold", {}).get("ActionThresholdValue", 0)))
        == Decimal("80")
        for action in actions
    )
    if not has_emergency_deny:
        raise RuntimeError("PantryPulse budget needs an EmergencyDenyAll action at 80%.")

    return account_id


def _key_schema(spec: TableSpec) -> list[dict[str, str]]:
    return [
        {"AttributeName": key, "KeyType": "HASH" if index == 0 else "RANGE"}
        for index, key in enumerate(spec.keys)
    ]


def _create_request(spec: TableSpec) -> dict[str, Any]:
    return {
        "TableName": spec.name,
        "AttributeDefinitions": [
            {"AttributeName": key, "AttributeType": "S"} for key in spec.keys
        ],
        "KeySchema": _key_schema(spec),
        "BillingMode": "PAY_PER_REQUEST",
        "SSESpecification": {"Enabled": True},
        "Tags": [{"Key": key, "Value": value} for key, value in REQUIRED_TAGS.items()],
    }


def _matches_key_schema(table: dict[str, Any], spec: TableSpec) -> bool:
    return table.get("KeySchema") == _key_schema(spec)


def ensure_tables(dynamodb_client: Any, *, apply: bool) -> tuple[str, ...]:
    """Plan or idempotently provision the required DynamoDB UAT tables.

    Callers must verify account and budget guardrails before using ``apply=True``.
    """
    if not apply:
        return table_names()

    created: list[str] = []
    for spec in TABLE_SPECS:
        try:
            table = dynamodb_client.describe_table(TableName=spec.name)["Table"]
        except ClientError as error:
            if error.response["Error"].get("Code") != "ResourceNotFoundException":
                raise
            dynamodb_client.create_table(**_create_request(spec))
            dynamodb_client.get_waiter("table_exists").wait(TableName=spec.name)
            created.append(spec.name)
            continue

        if not _matches_key_schema(table, spec):
            raise RuntimeError(f"Existing table {spec.name} has an incompatible key schema.")

    return tuple(created)
