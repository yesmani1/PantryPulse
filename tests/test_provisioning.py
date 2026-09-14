"""Unit tests for BE-7 DynamoDB provisioning guardrails."""

from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from pantrypulse.persistence.provisioning import (
    EXPECTED_ACCOUNT_ID,
    REQUIRED_TAGS,
    TABLE_SPECS,
    create_aws_session,
    ensure_tables,
    table_names,
    verify_cost_guardrails,
)


def _not_found() -> ClientError:
    return ClientError(
        {"Error": {"Code": "ResourceNotFoundException", "Message": "missing"}},
        "DescribeTable",
    )


def _matching_table(spec):
    return {
        "Table": {
            "KeySchema": [
                {
                    "AttributeName": key,
                    "KeyType": "HASH" if index == 0 else "RANGE",
                }
                for index, key in enumerate(spec.keys)
            ]
        }
    }


def _budget_clients():
    sts = Mock()
    sts.get_caller_identity.return_value = {"Account": EXPECTED_ACCOUNT_ID}
    budgets = Mock()
    budgets.describe_budgets.return_value = {
        "Budgets": [
            {
                "BudgetName": "PantryPulse-Operating",
                "BudgetLimit": {"Amount": "100"},
            }
        ]
    }
    budgets.describe_notifications_for_budget.return_value = {
        "Notifications": [
            {"Threshold": threshold, "NotificationType": "ACTUAL"}
            for threshold in (50, 80, 100)
        ]
    }
    budgets.describe_budget_actions_for_budget.return_value = {
        "Actions": [
            {
                "ActionType": "APPLY_IAM_POLICY",
                "ActionThreshold": {
                    "ActionThresholdType": "PERCENTAGE",
                    "ActionThresholdValue": 80,
                },
            }
        ]
    }
    return sts, budgets


def test_dry_run_lists_every_table_without_calling_dynamodb():
    dynamodb = Mock()

    assert ensure_tables(dynamodb, apply=False) == table_names()
    dynamodb.describe_table.assert_not_called()


def test_environment_session_loads_dotenv_without_forcing_a_profile(monkeypatch):
    dotenv_loader = Mock()
    session_factory = Mock()
    monkeypatch.setattr("pantrypulse.persistence.provisioning.load_dotenv", dotenv_loader)
    monkeypatch.setattr("pantrypulse.persistence.provisioning.boto3.Session", session_factory)

    create_aws_session(profile_name=None, region_name="us-west-2")

    dotenv_loader.assert_called_once_with()
    session_factory.assert_called_once_with(region_name="us-west-2")


def test_named_profile_remains_an_explicit_override(monkeypatch):
    session_factory = Mock()
    monkeypatch.setattr("pantrypulse.persistence.provisioning.boto3.Session", session_factory)

    create_aws_session(profile_name="offhourlabs", region_name="us-west-2")

    session_factory.assert_called_once_with(
        profile_name="offhourlabs", region_name="us-west-2"
    )


def test_apply_creates_missing_tables_with_safe_configuration():
    dynamodb = Mock()
    dynamodb.describe_table.side_effect = [_not_found() for _ in TABLE_SPECS]
    waiter = Mock()
    dynamodb.get_waiter.return_value = waiter

    assert ensure_tables(dynamodb, apply=True) == table_names()
    assert dynamodb.create_table.call_count == 3
    for call, spec in zip(dynamodb.create_table.call_args_list, TABLE_SPECS):
        request = call.kwargs
        assert request["TableName"] == spec.name
        assert request["BillingMode"] == "PAY_PER_REQUEST"
        assert request["SSESpecification"] == {"Enabled": True}
        assert {tag["Key"]: tag["Value"] for tag in request["Tags"]} == REQUIRED_TAGS
    assert waiter.wait.call_count == 3


def test_apply_leaves_matching_tables_unchanged():
    dynamodb = Mock()
    dynamodb.describe_table.side_effect = [_matching_table(spec) for spec in TABLE_SPECS]

    assert ensure_tables(dynamodb, apply=True) == ()
    dynamodb.create_table.assert_not_called()


def test_apply_rejects_an_incompatible_existing_table():
    dynamodb = Mock()
    dynamodb.describe_table.return_value = {
        "Table": {"KeySchema": [{"AttributeName": "wrong", "KeyType": "HASH"}]}
    }

    with pytest.raises(RuntimeError, match="incompatible key schema"):
        ensure_tables(dynamodb, apply=True)
    dynamodb.create_table.assert_not_called()


def test_cost_guardrails_accept_the_expected_budget_policy():
    sts, budgets = _budget_clients()

    assert verify_cost_guardrails(sts, budgets) == EXPECTED_ACCOUNT_ID


def test_cost_guardrails_reject_missing_emergency_deny_action():
    sts, budgets = _budget_clients()
    budgets.describe_budget_actions_for_budget.return_value = {"Actions": []}

    with pytest.raises(RuntimeError, match="EmergencyDenyAll"):
        verify_cost_guardrails(sts, budgets)
