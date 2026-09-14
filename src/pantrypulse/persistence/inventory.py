"""DynamoDB-backed inventory operations for PantryPulse."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import ClientError
from pydantic import ValidationError

from pantrypulse.schemas import (
    AddInventoryItemsRequest,
    AddInventoryItemsResponse,
    Confirmation,
    GetInventoryRequest,
    GetInventoryResponse,
    PantryItem,
    UpdateInventoryItemRequest,
    UpdateInventoryItemResponse,
)


PANTRY_ITEMS_TABLE = "pantrypulse-uat-pantry-items"
HOUSEHOLDS_TABLE = "pantrypulse-uat-households"
MAX_ADD_ITEMS = 99
_IDEMPOTENCY_PREFIX = "__idempotency__#"
_serializer = TypeSerializer()
_deserializer = TypeDeserializer()


class InventoryPersistenceError(RuntimeError):
    """Base error for a storage failure safe to show to the application."""


class InventoryItemConflictError(InventoryPersistenceError):
    """An item ID already exists or an idempotency key was reused differently."""


class InventoryItemNotFoundError(InventoryPersistenceError):
    """The requested household/item key does not exist."""


class InventoryUpdateConflictError(InventoryPersistenceError):
    """Another writer changed an item before this update could complete."""


def _decimalize(value: Any) -> Any:
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {key: _decimalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_decimalize(item) for item in value]
    return value


def _serialize(value: Any) -> dict[str, Any]:
    return _serializer.serialize(_decimalize(value))


def _serialize_map(value: dict[str, Any]) -> dict[str, Any]:
    return {key: _serialize(item) for key, item in value.items()}


def _deserialize_map(value: dict[str, Any]) -> dict[str, Any]:
    return {key: _deserializer.deserialize(item) for key, item in value.items()}


class InventoryRepository:
    """Persistence adapter for the three BE-8 inventory contracts."""

    def __init__(
        self,
        dynamodb_client: Any,
        *,
        pantry_items_table: str = PANTRY_ITEMS_TABLE,
        households_table: str = HOUSEHOLDS_TABLE,
    ) -> None:
        self._client = dynamodb_client
        self._pantry_items_table = pantry_items_table
        self._households_table = households_table

    def add_inventory_items(
        self, request: AddInventoryItemsRequest
    ) -> AddInventoryItemsResponse:
        """Atomically add a household's items and durable idempotency receipt."""
        items = request.items
        if len(items) > MAX_ADD_ITEMS:
            raise InventoryPersistenceError(
                f"An inventory add supports at most {MAX_ADD_ITEMS} items."
            )
        household_id = items[0].household_id
        if any(item.household_id != household_id for item in items):
            raise InventoryPersistenceError("All added items must belong to one household.")
        if len({item.item_id for item in items}) != len(items):
            raise InventoryItemConflictError(
                "An inventory add cannot contain duplicate item IDs."
            )

        fingerprint = self._fingerprint(items)
        marker_key = self._marker_key(household_id, request.idempotency_key)
        marker = {
            "household_id": marker_key,
            "record_type": "idempotency",
            "source_household_id": household_id,
            "idempotency_key": request.idempotency_key,
            "request_fingerprint": fingerprint,
            "item_ids": [item.item_id for item in items],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        transaction_items = [
            {
                "Put": {
                    "TableName": self._households_table,
                    "Item": _serialize_map(marker),
                    "ConditionExpression": "attribute_not_exists(household_id)",
                }
            }
        ]
        transaction_items.extend(
            {
                "Put": {
                    "TableName": self._pantry_items_table,
                    "Item": _serialize_map(item.model_dump(mode="json")),
                    "ConditionExpression": "attribute_not_exists(household_id) AND attribute_not_exists(item_id)",
                }
            }
            for item in items
        )
        try:
            self._client.transact_write_items(
                TransactItems=transaction_items,
            )
        except ClientError as error:
            if error.response["Error"].get("Code") != "TransactionCanceledException":
                raise InventoryPersistenceError("Inventory could not be saved.") from error
            receipt = self._get_receipt(marker_key)
            if receipt and receipt.get("request_fingerprint") == fingerprint:
                return AddInventoryItemsResponse(
                    confirmation=Confirmation(success=True, message="Items already added."),
                    item_ids=receipt["item_ids"],
                )
            raise InventoryItemConflictError(
                "The idempotency key or an inventory item ID conflicts with existing data."
            ) from error

        return AddInventoryItemsResponse(
            confirmation=Confirmation(success=True, message="Items added."),
            item_ids=[item.item_id for item in items],
        )

    def get_inventory(self, request: GetInventoryRequest) -> GetInventoryResponse:
        """Return one household's inventory, with optional local filters."""
        values = {":household_id": _serialize(request.household_id)}
        items: list[PantryItem] = []
        start_key: dict[str, Any] | None = None
        while True:
            query: dict[str, Any] = {
                "TableName": self._pantry_items_table,
                "KeyConditionExpression": "household_id = :household_id",
                "ExpressionAttributeValues": values,
            }
            if start_key:
                query["ExclusiveStartKey"] = start_key
            response = self._client.query(**query)
            items.extend(self._as_pantry_item(raw) for raw in response.get("Items", []))
            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                break

        if request.categories is not None:
            categories = set(request.categories)
            items = [item for item in items if item.category in categories]
        if request.statuses is not None:
            statuses = set(request.statuses)
            items = [item for item in items if item.status in statuses]
        return GetInventoryResponse(items=sorted(items, key=lambda item: item.item_id))

    def update_inventory_item(
        self, request: UpdateInventoryItemRequest
    ) -> UpdateInventoryItemResponse:
        """Apply an exact patch with optimistic concurrency protection."""
        key = _serialize_map(
            {"household_id": request.household_id, "item_id": request.item_id}
        )
        response = self._client.get_item(
            TableName=self._pantry_items_table,
            Key=key,
            ConsistentRead=True,
        )
        if "Item" not in response:
            raise InventoryItemNotFoundError("Inventory item was not found.")
        stored = _deserialize_map(response["Item"])
        existing = self._as_pantry_item(response["Item"])
        previous_updated_at = stored.get("updated_at")
        if not isinstance(previous_updated_at, str):
            raise InventoryPersistenceError("Stored inventory data is invalid.")
        updated = existing.model_copy(
            update={
                **request.patch.model_dump(exclude_unset=True),
                "updated_at": datetime.now(timezone.utc),
            }
        )
        try:
            updated = PantryItem.model_validate(updated.model_dump())
        except ValidationError as error:
            raise InventoryPersistenceError("Inventory patch would create an invalid item.") from error

        try:
            self._client.put_item(
                TableName=self._pantry_items_table,
                Item=_serialize_map(updated.model_dump(mode="json")),
                ConditionExpression="#updated_at = :previous_updated_at",
                ExpressionAttributeNames={"#updated_at": "updated_at"},
                ExpressionAttributeValues={
                    ":previous_updated_at": _serialize(previous_updated_at)
                },
            )
        except ClientError as error:
            if error.response["Error"].get("Code") == "ConditionalCheckFailedException":
                raise InventoryUpdateConflictError(
                    "Inventory item changed before this update could be saved."
                ) from error
            raise InventoryPersistenceError("Inventory item could not be updated.") from error
        return UpdateInventoryItemResponse(item=updated)

    def _get_receipt(self, marker_key: str) -> dict[str, Any] | None:
        response = self._client.get_item(
            TableName=self._households_table,
            Key=_serialize_map({"household_id": marker_key}),
            ConsistentRead=True,
        )
        return _deserialize_map(response["Item"]) if "Item" in response else None

    @staticmethod
    def _marker_key(household_id: str, idempotency_key: str) -> str:
        return f"{_IDEMPOTENCY_PREFIX}{household_id}#{idempotency_key}"

    @staticmethod
    def _fingerprint(items: list[PantryItem]) -> str:
        payload = [item.model_dump(mode="json") for item in sorted(items, key=lambda item: item.item_id)]
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _as_pantry_item(raw: dict[str, Any]) -> PantryItem:
        try:
            return PantryItem.model_validate(_deserialize_map(raw))
        except ValidationError as error:
            raise InventoryPersistenceError("Stored inventory data is invalid.") from error
