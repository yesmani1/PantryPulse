"""Unit tests for BE-8 DynamoDB inventory persistence."""

from datetime import date, datetime, timezone
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from pantrypulse.persistence.inventory import (
    InventoryItemConflictError,
    InventoryItemNotFoundError,
    InventoryPersistenceError,
    InventoryRepository,
    InventoryUpdateConflictError,
    MAX_ADD_ITEMS,
    _deserialize_map,
    _serialize_map,
)
from pantrypulse.schemas import (
    AddInventoryItemsRequest,
    Category,
    DateType,
    ExpirySource,
    GetInventoryRequest,
    InventoryItemPatch,
    ItemStatus,
    PantryItem,
    UpdateInventoryItemRequest,
)


NOW = datetime(2026, 9, 3, 12, tzinfo=timezone.utc)


def item(*, item_id="item-1", household_id="household-1", **overrides):
    values = {
        "household_id": household_id,
        "item_id": item_id,
        "name": "Greek Yogurt",
        "category": Category.DAIRY,
        "quantity": 500.0,
        "unit": "g",
        "purchase_date": date(2026, 9, 1),
        "expiry_date": date(2026, 9, 8),
        "date_type": DateType.BEST_BY,
        "expiry_source": ExpirySource.OCR,
        "confidence": 0.9,
        "sealed": True,
        "high_risk": False,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return PantryItem(**values)


def cancellation_error():
    return ClientError({"Error": {"Code": "TransactionCanceledException"}}, "TransactWriteItems")


def conditional_error():
    return ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")


def test_add_uses_one_transaction_and_private_idempotency_receipt():
    client = Mock()
    repository = InventoryRepository(client)
    request = AddInventoryItemsRequest(items=[item()], idempotency_key="request-1")

    response = repository.add_inventory_items(request)

    assert response.item_ids == ["item-1"]
    transaction = client.transact_write_items.call_args.kwargs["TransactItems"]
    assert len(transaction) == 2
    receipt = _deserialize_map(transaction[0]["Put"]["Item"])
    assert receipt["record_type"] == "idempotency"
    assert receipt["household_id"].startswith("__idempotency__#household-1#")
    assert transaction[1]["Put"]["ConditionExpression"]


def test_matching_idempotency_retry_returns_original_ids():
    client = Mock()
    repository = InventoryRepository(client)
    request = AddInventoryItemsRequest(items=[item()], idempotency_key="request-1")
    fingerprint = repository._fingerprint(request.items)
    client.transact_write_items.side_effect = cancellation_error()
    client.get_item.return_value = {"Item": _serialize_map({
        "request_fingerprint": fingerprint, "item_ids": ["item-1"]
    })}

    assert repository.add_inventory_items(request).item_ids == ["item-1"]


def test_conflicting_idempotency_key_raises_clear_error():
    client = Mock()
    repository = InventoryRepository(client)
    client.transact_write_items.side_effect = cancellation_error()
    client.get_item.return_value = {"Item": _serialize_map({
        "request_fingerprint": "different", "item_ids": ["other"]
    })}

    with pytest.raises(InventoryItemConflictError):
        repository.add_inventory_items(AddInventoryItemsRequest(items=[item()], idempotency_key="request-1"))


def test_add_rejects_more_than_transaction_limit():
    client = Mock()
    items = [item(item_id=f"item-{number}") for number in range(MAX_ADD_ITEMS + 1)]

    with pytest.raises(InventoryPersistenceError, match="at most"):
        InventoryRepository(client).add_inventory_items(
            AddInventoryItemsRequest(items=items, idempotency_key="large-request")
        )
    client.transact_write_items.assert_not_called()


def test_add_rejects_duplicate_item_ids_before_dynamodb():
    client = Mock()
    request = AddInventoryItemsRequest(
        items=[item(), item(name="Another item")], idempotency_key="duplicate-items"
    )

    with pytest.raises(InventoryItemConflictError, match="duplicate"):
        InventoryRepository(client).add_inventory_items(request)
    client.transact_write_items.assert_not_called()


def test_get_inventory_paginates_filters_and_sorts():
    client = Mock()
    first = item(item_id="item-2")
    second = item(item_id="item-1", category=Category.PRODUCE, status=ItemStatus.USED)
    client.query.side_effect = [
        {"Items": [_serialize_map(first.model_dump(mode="json"))], "LastEvaluatedKey": _serialize_map({"household_id": "household-1", "item_id": "item-2"})},
        {"Items": [_serialize_map(second.model_dump(mode="json"))]},
    ]

    response = InventoryRepository(client).get_inventory(
        GetInventoryRequest(
            household_id="household-1",
            categories=[Category.DAIRY],
            statuses=[ItemStatus.ACTIVE],
        )
    )

    assert [stored.item_id for stored in response.items] == ["item-2"]
    assert client.query.call_count == 2


def test_update_applies_only_supplied_fields_and_refreshes_timestamp():
    client = Mock()
    existing = item()
    client.get_item.return_value = {"Item": _serialize_map(existing.model_dump(mode="json"))}
    request = UpdateInventoryItemRequest(
        household_id="household-1", item_id="item-1", patch=InventoryItemPatch(quantity=250)
    )

    response = InventoryRepository(client).update_inventory_item(request)

    assert response.item.quantity == 250
    assert response.item.name == existing.name
    assert response.item.updated_at > existing.updated_at
    assert client.put_item.call_args.kwargs["ConditionExpression"]


def test_update_rejects_missing_item_and_concurrent_update():
    client = Mock()
    repository = InventoryRepository(client)
    request = UpdateInventoryItemRequest(
        household_id="household-1", item_id="item-1", patch=InventoryItemPatch(quantity=250)
    )
    client.get_item.return_value = {}
    with pytest.raises(InventoryItemNotFoundError):
        repository.update_inventory_item(request)

    client.get_item.return_value = {"Item": _serialize_map(item().model_dump(mode="json"))}
    client.put_item.side_effect = conditional_error()
    with pytest.raises(InventoryUpdateConflictError):
        repository.update_inventory_item(request)


def test_update_revalidates_date_rules_and_rejects_malformed_storage():
    client = Mock()
    repository = InventoryRepository(client)
    client.get_item.return_value = {"Item": _serialize_map(item().model_dump(mode="json"))}
    invalid_patch = UpdateInventoryItemRequest(
        household_id="household-1",
        item_id="item-1",
        patch=InventoryItemPatch(date_type=DateType.NONE),
    )

    with pytest.raises(InventoryPersistenceError, match="invalid item"):
        repository.update_inventory_item(invalid_patch)
    client.put_item.assert_not_called()

    client.query.return_value = {
        "Items": [_serialize_map({"household_id": "household-1"})]
    }
    with pytest.raises(InventoryPersistenceError, match="Stored inventory data"):
        repository.get_inventory(GetInventoryRequest(household_id="household-1"))
