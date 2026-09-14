"""Feedback persistence is append-only and produces measured rescue statistics."""

from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from pantrypulse.persistence.feedback import FeedbackRepository
from pantrypulse.persistence.inventory import InventoryPersistenceError, _serialize_map
from pantrypulse.schemas import FeedbackResponse, GetRescueStatsRequest, RecordFeedbackRequest


def _event(event_id: str, response: FeedbackResponse, value: float, timestamp: str) -> dict:
    return _serialize_map({
        "household_id": "h", "event_id": event_id, "item_id": "item-1",
        "response": response.value, "estimated_value": value, "timestamp": timestamp,
    })


def test_record_feedback_writes_one_conditional_event():
    client = Mock()
    result = FeedbackRepository(client).record_feedback(
        RecordFeedbackRequest(household_id="h", item_id="item-1", response=FeedbackResponse.USED, estimated_value=4.5)
    )
    assert result.confirmation.success
    call = client.put_item.call_args.kwargs
    assert call["TableName"] == "pantrypulse-uat-feedback-log"
    assert call["ConditionExpression"]


def test_stats_paginate_filter_period_and_sum_used_values():
    client = Mock()
    client.query.side_effect = [
        {"Items": [_event("1", FeedbackResponse.USED, 4.5, "2026-09-02T10:00:00+00:00")], "LastEvaluatedKey": {"x": {"S": "1"}}},
        {"Items": [
            _event("2", FeedbackResponse.TOSSED, 2, "2026-09-03T10:00:00+00:00"),
            _event("3", FeedbackResponse.USED, 8, "2026-08-30T10:00:00+00:00"),
        ]},
    ]
    result = FeedbackRepository(client).get_rescue_stats(GetRescueStatsRequest(household_id="h", period="2026-09"))
    assert result.stats.rescued_count == 1
    assert result.stats.tossed_count == 1
    assert result.stats.estimated_value_saved == 4.5
    assert client.query.call_count == 2


def test_feedback_write_and_malformed_records_are_safe_errors():
    client = Mock()
    client.put_item.side_effect = ClientError({"Error": {"Code": "AccessDeniedException"}}, "PutItem")
    with pytest.raises(InventoryPersistenceError, match="Feedback could not be saved"):
        FeedbackRepository(client).record_feedback(
            RecordFeedbackRequest(household_id="h", item_id="item-1", response=FeedbackResponse.USED)
        )
    client = Mock()
    client.query.return_value = {"Items": [{"bad": {"S": "record"}}]}
    with pytest.raises(InventoryPersistenceError, match="Stored feedback could not be read"):
        FeedbackRepository(client).get_rescue_stats(GetRescueStatsRequest(household_id="h", period="2026-09"))
