"""Run a disposable BE-8 UAT DynamoDB round-trip and remove its records."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from uuid import uuid4

from pantrypulse.persistence.inventory import (
    HOUSEHOLDS_TABLE,
    PANTRY_ITEMS_TABLE,
    InventoryRepository,
    _serialize_map,
)
from pantrypulse.persistence.provisioning import create_aws_session
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


def _item(household_id: str, item_id: str) -> PantryItem:
    now = datetime.now(timezone.utc)
    return PantryItem(
        household_id=household_id,
        item_id=item_id,
        name="BE-8 disposable test milk",
        category=Category.DAIRY,
        quantity=1,
        unit="carton",
        purchase_date=date.today(),
        expiry_date=date.today(),
        date_type=DateType.ESTIMATED,
        expiry_source=ExpirySource.SHELF_LIFE_TABLE,
        confidence=0.45,
        sealed=True,
        high_risk=False,
        created_at=now,
        updated_at=now,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="perform the disposable live round-trip"
    )
    args = parser.parse_args()
    if not args.apply:
        print("Dry run: pass --apply to write and then clean up a disposable UAT record.")
        return

    session = create_aws_session(profile_name=None, region_name="us-west-2")
    client = session.client("dynamodb")
    repository = InventoryRepository(client)
    household_id = f"__be8_verify__#{uuid4()}"
    item_id = str(uuid4())
    idempotency_key = str(uuid4())
    inventory_item = _item(household_id, item_id)
    marker_key = repository._marker_key(household_id, idempotency_key)

    try:
        added = repository.add_inventory_items(
            AddInventoryItemsRequest(items=[inventory_item], idempotency_key=idempotency_key)
        )
        retried = repository.add_inventory_items(
            AddInventoryItemsRequest(items=[inventory_item], idempotency_key=idempotency_key)
        )
        filtered = repository.get_inventory(
            GetInventoryRequest(
                household_id=household_id,
                categories=[Category.DAIRY],
                statuses=[ItemStatus.ACTIVE],
            )
        )
        updated = repository.update_inventory_item(
            UpdateInventoryItemRequest(
                household_id=household_id,
                item_id=item_id,
                patch=InventoryItemPatch(quantity=2),
            )
        )
        read_back = repository.get_inventory(GetInventoryRequest(household_id=household_id))
        if not (
            added.item_ids == [item_id]
            and retried.item_ids == [item_id]
            and [stored.item_id for stored in filtered.items] == [item_id]
            and updated.item.quantity == 2
            and len(read_back.items) == 1
            and read_back.items[0].quantity == 2
        ):
            raise RuntimeError("BE-8 UAT verification returned unexpected results.")
        print("BE-8 UAT inventory round-trip passed; disposable records will be removed.")
    finally:
        client.delete_item(
            TableName=PANTRY_ITEMS_TABLE,
            Key=_serialize_map({"household_id": household_id, "item_id": item_id}),
        )
        client.delete_item(
            TableName=HOUSEHOLDS_TABLE,
            Key=_serialize_map({"household_id": marker_key}),
        )


if __name__ == "__main__":
    main()
