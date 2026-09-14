"""DynamoDB persistence for expiry feedback and measured rescue statistics."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from botocore.exceptions import ClientError
from pydantic import ValidationError

from pantrypulse.persistence.inventory import InventoryPersistenceError, _deserialize_map, _serialize, _serialize_map
from pantrypulse.schemas import (
    Confirmation, FeedbackEvent, FeedbackResponse, GetRescueStatsRequest,
    GetRescueStatsResponse, RecordFeedbackRequest, RecordFeedbackResponse, RescueStats,
)


FEEDBACK_LOG_TABLE = "pantrypulse-uat-feedback-log"


class FeedbackRepository:
    """Store feedback events and calculate stats from the append-only log."""

    def __init__(self, dynamodb_client: Any, *, table_name: str = FEEDBACK_LOG_TABLE) -> None:
        self._client = dynamodb_client
        self._table_name = table_name

    def record_feedback(self, request: RecordFeedbackRequest) -> RecordFeedbackResponse:
        event = FeedbackEvent(household_id=request.household_id, event_id=str(uuid4()), item_id=request.item_id, response=request.response, estimated_value=request.estimated_value, timestamp=datetime.now(timezone.utc))
        try:
            self._client.put_item(TableName=self._table_name, Item=_serialize_map(event.model_dump(mode="json")), ConditionExpression="attribute_not_exists(household_id) AND attribute_not_exists(event_id)")
        except ClientError as error:
            raise InventoryPersistenceError("Feedback could not be saved.") from error
        return RecordFeedbackResponse(confirmation=Confirmation(success=True, message="Feedback saved."), event=event)

    def get_rescue_stats(self, request: GetRescueStatsRequest) -> GetRescueStatsResponse:
        entries: list[FeedbackEvent] = []
        start_key = None
        while True:
            query: dict[str, Any] = {"TableName": self._table_name, "KeyConditionExpression": "household_id = :household_id", "ExpressionAttributeValues": {":household_id": _serialize(request.household_id)}}
            if start_key:
                query["ExclusiveStartKey"] = start_key
            response = self._client.query(**query)
            try:
                entries.extend(
                    FeedbackEvent.model_validate(_deserialize_map(raw))
                    for raw in response.get("Items", [])
                )
            except ValidationError as error:
                raise InventoryPersistenceError("Stored feedback could not be read.") from error
            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                break
        entries = [entry for entry in entries if entry.timestamp.strftime("%Y-%m") == request.period]
        used = [entry for entry in entries if entry.response is FeedbackResponse.USED]
        tossed = [entry for entry in entries if entry.response is FeedbackResponse.TOSSED]
        return GetRescueStatsResponse(stats=RescueStats(household_id=request.household_id, period=request.period, rescued_count=len(used), tossed_count=len(tossed), estimated_value_saved=sum(entry.estimated_value for entry in used)))
