"""Striking out an item the agent got wrong.

Today's date gate stops a bad date being stored, but nothing stopped a bad
*item*: a hallucinated product name from a misread photo stayed in the pantry
permanently, showed in every listing, and led the daily check. An agent acting
on someone's behalf has to let them undo what it did.
"""

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from pantrypulse.interface.handlers.inventory_actions import (
    REMOVE_CALLBACK_PREFIX,
    remove,
    remove_action,
)
from pantrypulse.schemas import (
    Category,
    DateType,
    ExpirySource,
    ItemStatus,
    PantryItem,
)

NOW = datetime(2026, 9, 6, tzinfo=timezone.utc)


def item(name="PantryPulse", item_id="item-1"):
    return PantryItem(
        household_id="telegram:99", item_id=item_id, name=name,
        category=Category.PANTRY, quantity=1.0, unit="each",
        purchase_date=date(2026, 9, 1), expiry_date=date(2026, 8, 26),
        date_type=DateType.BEST_BY, expiry_source=ExpirySource.SHELF_LIFE_TABLE,
        confidence=1.0, sealed=True, high_risk=False, status=ItemStatus.ACTIVE,
        created_at=NOW, updated_at=NOW,
    )


def _update(callback_data=None):
    update = MagicMock()
    update.effective_chat.id = 99
    update.effective_chat.send_message = AsyncMock()
    if callback_data is None:
        update.callback_query = None
    else:
        update.callback_query.data = callback_data
        update.callback_query.answer = AsyncMock()
    return update


def _context(items=None):
    services = MagicMock()
    services.inventory.get_inventory.return_value.items = items or []
    context = MagicMock()
    context.user_data = {}
    context.application.bot_data = {"services": services}
    return context, services


@pytest.mark.asyncio
async def test_remove_offers_a_button_for_each_item():
    context, _ = _context([item(name="PantryPulse"), item(name="Milk", item_id="item-2")])

    update = _update()
    await remove(update, context)

    keyboard = update.effective_chat.send_message.call_args.kwargs["reply_markup"]
    buttons = [b for row in keyboard.inline_keyboard for b in row]
    assert [b.text for b in buttons] == ["PantryPulse", "Milk"]
    # Same defect that broke /decision: callback_data must not become a url.
    for button in buttons:
        assert button.url is None
        assert button.callback_data.startswith(REMOVE_CALLBACK_PREFIX)


@pytest.mark.asyncio
async def test_removing_marks_the_item_removed_and_never_tossed():
    """The distinction that matters: tossed means real food went in the bin and
    counts against the rescue figures. An item that never existed must not."""
    context, services = _context([item()])

    update = _update(callback_data=f"{REMOVE_CALLBACK_PREFIX}item-1")
    await remove_action(update, context)

    request = services.inventory.update_inventory_item.call_args.args[0]
    assert request.item_id == "item-1"
    assert request.patch.status is ItemStatus.REMOVED
    assert request.patch.status is not ItemStatus.TOSSED
    # And nothing was written to the feedback log, which is what feeds the counter.
    services.feedback.record_feedback.assert_not_called()


@pytest.mark.asyncio
async def test_the_confirmation_names_what_went_and_says_it_was_not_waste():
    context, _ = _context([item(name="PantryPulse")])

    update = _update(callback_data=f"{REMOVE_CALLBACK_PREFIX}item-1")
    await remove_action(update, context)

    sent = update.effective_chat.send_message.call_args.args[0]
    assert "PantryPulse" in sent
    assert "rescue figures" in sent


@pytest.mark.asyncio
async def test_an_empty_pantry_says_so_rather_than_offering_an_empty_keyboard():
    context, _ = _context([])

    update = _update()
    await remove(update, context)

    assert "nothing in your pantry" in update.effective_chat.send_message.call_args.args[0]
    assert "reply_markup" in update.effective_chat.send_message.call_args.kwargs


@pytest.mark.asyncio
async def test_the_sample_pantry_cannot_be_edited():
    """Demo mode reads fixtures, which are not this household's to change."""
    from pantrypulse.interface.handlers.commands import DEMO_MODE

    context, services = _context([item()])
    context.user_data[DEMO_MODE] = True

    update = _update()
    await remove(update, context)

    assert "sample pantry isn't yours to change" in update.effective_chat.send_message.call_args.args[0]
    services.inventory.update_inventory_item.assert_not_called()


@pytest.mark.asyncio
async def test_a_persistence_failure_apologises_rather_than_raising():
    context, services = _context([item()])
    services.inventory.update_inventory_item.side_effect = RuntimeError("dynamo is down")

    update = _update(callback_data=f"{REMOVE_CALLBACK_PREFIX}item-1")
    await remove_action(update, context)

    assert "couldn't remove that" in update.effective_chat.send_message.call_args.args[0]


def test_reads_ask_for_active_items_only():
    """A removed, used, binned or donated row is still stored -- storage is the
    record, not the pantry."""
    from pantrypulse.interface.handlers.commands import _active_inventory

    services = MagicMock()
    services.inventory.get_inventory.return_value.items = []

    _active_inventory(services, "telegram:99")

    request = services.inventory.get_inventory.call_args.args[0]
    assert request.statuses == [ItemStatus.ACTIVE]
