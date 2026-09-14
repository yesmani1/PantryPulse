"""Ordered-shopping receipt flow tests; all DynamoDB boundaries are mocked."""

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from pantrypulse.interface.handlers.order_actions import (
    ORDER_BULK_RECEIVE_CALLBACK, ORDER_EXCLUDE_CALLBACK, ORDER_MARK_CALLBACK,
    ORDER_RECEIVE_CALLBACK, _new_ordered_item, order_action, ordered_receipt_date,
)
from pantrypulse.persistence.sessions import InteractionSessionRepository, StoredInteraction
from pantrypulse.schemas import (
    Category, DateType, ExpirySource, ItemStatus, PantryItem, ShoppingList,
    ShoppingListItem,
)
from pantrypulse.tools.orders import infer_order_category, normalise_item_name

NOW = datetime(2026, 9, 13, tzinfo=timezone.utc)


def _item(name="Milk", item_id="active-1", status=ItemStatus.ACTIVE):
    return PantryItem(
        household_id="telegram:99", item_id=item_id, name=name, category=Category.DAIRY,
        quantity=1, unit="carton", purchase_date=date(2026, 9, 13), expiry_date=None,
        date_type=DateType.NONE, expiry_source=ExpirySource.SHELF_LIFE_TABLE,
        confidence=0.45, sealed=False, high_risk=False, status=status,
        needs_confirmation=status is ItemStatus.ORDERED, created_at=NOW, updated_at=NOW,
    )


def _update(callback_data=None, text=None):
    update = MagicMock()
    update.effective_chat.id = 99
    update.effective_chat.send_message = AsyncMock()
    update.callback_query = MagicMock() if callback_data else None
    if callback_data:
        update.callback_query.data = callback_data
        update.callback_query.answer = AsyncMock()
    update.message = MagicMock() if text else None
    if text:
        update.message.text = text
    return update


def _context(items=None, stored=None):
    repository = object.__new__(InteractionSessionRepository)
    repository.load = MagicMock(return_value=stored)
    repository.save = MagicMock()
    repository.delete = MagicMock()
    repository.set_cursor = MagicMock()
    repository.get_cursor = MagicMock(return_value=None)
    repository.clear_cursor = MagicMock()
    services = MagicMock()
    services.interactions = repository
    services.inventory.get_inventory.return_value.items = items or []
    context = MagicMock()
    context.user_data = {}
    context.application.bot_data = {"services": services}
    return context, services, repository


def test_order_name_matching_is_conservative_and_category_inference_is_opt_in():
    assert normalise_item_name("  Whole-Milk! ") == "whole milk"
    assert infer_order_category("Whole Milk") is Category.DAIRY
    assert infer_order_category("Family favourite") is None


def test_new_ordered_item_is_not_active_or_an_expiry_claim():
    ordered = _new_ordered_item("telegram:99", ShoppingListItem(name="milk"))
    assert ordered.status is ItemStatus.ORDERED
    assert ordered.expiry_date is None
    assert ordered.date_type is DateType.NONE
    assert ordered.needs_confirmation is True


@pytest.mark.asyncio
async def test_mark_ordered_persists_rows_and_removes_the_approved_plan():
    shopping = ShoppingList(items=[ShoppingListItem(name="milk")])
    stored = StoredInteraction("approved_shopping", {"shopping": shopping.model_dump(mode="json")})
    context, services, repository = _context(stored=stored)
    update = _update(f"{ORDER_MARK_CALLBACK}:approved-shopping")

    await order_action(update, context)

    request = services.inventory.add_inventory_items.call_args.args[0]
    assert request.items[0].status is ItemStatus.ORDERED
    assert request.items[0].name == "milk"
    repository.delete.assert_called_with("telegram:99", "approved-shopping")
    assert "Order recorded" in update.effective_chat.send_message.call_args.args[0]


@pytest.mark.asyncio
async def test_mark_ordered_warns_and_offers_remove_or_continue_for_a_duplicate():
    shopping = ShoppingList(items=[ShoppingListItem(name="milk"), ShoppingListItem(name="onions")])
    stored = StoredInteraction("approved_shopping", {"shopping": shopping.model_dump(mode="json")})
    context, services, repository = _context(items=[_item()], stored=stored)
    update = _update(f"{ORDER_MARK_CALLBACK}:approved-shopping")

    await order_action(update, context)

    services.inventory.add_inventory_items.assert_not_called()
    repository.save.assert_called_once()
    keyboard = update.effective_chat.send_message.call_args.kwargs["reply_markup"]
    assert [button.text for button in keyboard.inline_keyboard[0]] == ["Remove already present", "Order anyway"]


@pytest.mark.asyncio
async def test_remove_duplicates_orders_only_new_entries():
    shopping = ShoppingList(items=[ShoppingListItem(name="milk"), ShoppingListItem(name="onions")])
    stored = StoredInteraction("order_confirmation", {"shopping": shopping.model_dump(mode="json")})
    context, services, repository = _context(items=[_item()], stored=stored)
    update = _update(f"{ORDER_EXCLUDE_CALLBACK}:token")

    await order_action(update, context)

    request = services.inventory.add_inventory_items.call_args.args[0]
    assert [row.name for row in request.items] == ["onions"]
    repository.delete.assert_any_call("telegram:99", "approved-shopping")


@pytest.mark.asyncio
async def test_individual_receipt_uses_household_date_and_activates_item():
    ordered = _item(status=ItemStatus.ORDERED, item_id="order-1")
    context, services, repository = _context(items=[ordered])
    update = _update(f"{ORDER_RECEIVE_CALLBACK}:order-1")

    await order_action(update, context)
    assert "What expiry date" in update.effective_chat.send_message.call_args.args[0]

    date_update = _update(text="2027-04-16")
    await ordered_receipt_date(date_update, context)

    request = services.inventory.update_inventory_item.call_args.args[0]
    assert request.patch.status is ItemStatus.ACTIVE
    assert request.patch.expiry_date == date(2027, 4, 16)
    assert request.patch.expiry_source is ExpirySource.USER_CONFIRMED
    repository.clear_cursor.assert_called()


@pytest.mark.asyncio
async def test_bulk_receipt_activates_only_confident_categories():
    known = _item("Milk", "order-milk", ItemStatus.ORDERED)
    unknown = _item("Family favourite", "order-unknown", ItemStatus.ORDERED)
    context, services, _ = _context(items=[known, unknown])
    update = _update(ORDER_BULK_RECEIVE_CALLBACK)

    await order_action(update, context)

    assert services.inventory.update_inventory_item.call_count == 1
    request = services.inventory.update_inventory_item.call_args.args[0]
    assert request.item_id == "order-milk"
    assert request.patch.status is ItemStatus.ACTIVE
    assert request.patch.category is Category.DAIRY
    assert request.patch.date_type is DateType.ESTIMATED
    assert "Still awaiting" in update.effective_chat.send_message.call_args.args[0]
