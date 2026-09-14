"""Correcting a date before it is stored.

The guarantee that no wrong date reaches the database comes from this flow, not
from the models: it is the only step that does not depend on a model being
right. So a wrong date must be fixable on its own, without discarding the whole
photo, and an unverified item must not be saved as though it were read.
"""

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from pantrypulse.interface.handlers.photos import (
    INGESTION_CALLBACK_PREFIX,
    parse_date,
    preview_markup,
    receive_date,
    request_date,
)
from pantrypulse.schemas import Category, DateType, ExpirySource, ItemStatus, PantryItem

NOW = datetime(2026, 9, 6, tzinfo=timezone.utc)


def stored(name="Organic Chicken Stock", needs_confirmation=True, expiry=date(2026, 9, 20)):
    return PantryItem(
        household_id="telegram:1",
        item_id="item-1",
        name=name,
        category=Category.PANTRY,
        quantity=1.0,
        unit="carton",
        purchase_date=date(2026, 9, 6),
        expiry_date=expiry,
        date_type=DateType.ESTIMATED,
        expiry_source=ExpirySource.SHELF_LIFE_TABLE,
        confidence=0.4,
        sealed=True,
        high_risk=False,
        status=ItemStatus.ACTIVE,
        needs_confirmation=needs_confirmation,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.parametrize(
    "text,expected",
    [
        ("2027-04-16", date(2027, 4, 16)),
        ("16/04/2027", date(2027, 4, 16)),
        ("16 Apr 2027", date(2027, 4, 16)),
        ("Apr 16 2027", date(2027, 4, 16)),
        ("  2027-04-16  ", date(2027, 4, 16)),
        ("next tuesday", None),
        ("", None),
        ("16/04", None),
    ],
)
def test_household_typed_dates_are_read_or_refused(text, expected):
    assert parse_date(text) == expected


def test_every_shown_item_gets_its_own_correction_button():
    """Accept-all or discard-all forces a re-send over one wrong digit."""
    items = [stored(name="A"), stored(name="B", needs_confirmation=False)]

    rows = preview_markup("tok", items).inline_keyboard

    setdate = [
        button
        for row in rows
        for button in row
        if button.callback_data.startswith(f"{INGESTION_CALLBACK_PREFIX}setdate:")
    ]
    assert len(setdate) == 2
    # The unverified item is the one carrying the warning marker.
    assert setdate[0].text.startswith("⚠")
    assert not setdate[1].text.startswith("⚠")


@pytest.mark.asyncio
async def test_a_typed_date_replaces_the_estimate_and_clears_the_flag():
    items = [stored()]
    update = MagicMock()
    update.message.text = "2027-04-16"
    update.effective_chat.send_message = AsyncMock()
    context = MagicMock()
    context.user_data = {
        "pending_ingestions": {"tok": items},
        "awaiting_date": {"token": "tok", "index": 0},
    }

    await receive_date(update, context)

    corrected = context.user_data["pending_ingestions"]["tok"][0]
    assert corrected.expiry_date == date(2027, 4, 16)
    assert corrected.needs_confirmation is False
    # A date a person supplied is the most reliable source there is; showing it
    # as "estimated from category" would be a lie about where it came from.
    assert corrected.expiry_source is ExpirySource.USER_CONFIRMED
    assert corrected.confidence == 1.0
    assert "awaiting_date" not in context.user_data


@pytest.mark.asyncio
async def test_a_typed_date_replaces_a_none_date_type_with_estimated():
    items = [stored(expiry=None)]
    items[0] = items[0].model_copy(update={"date_type": DateType.NONE})
    update = MagicMock()
    update.message.text = "2026-10-09"
    update.effective_chat.send_message = AsyncMock()
    context = MagicMock()
    context.user_data = {"pending_ingestions": {"tok": items}, "awaiting_date": {"token": "tok", "index": 0}}

    await receive_date(update, context)

    corrected = context.user_data["pending_ingestions"]["tok"][0]
    assert corrected.expiry_date == date(2026, 10, 9)
    assert corrected.date_type is DateType.ESTIMATED


@pytest.mark.asyncio
async def test_an_unreadable_reply_keeps_asking_rather_than_dropping_the_edit():
    items = [stored()]
    update = MagicMock()
    update.message.text = "sometime next spring"
    update.effective_chat.send_message = AsyncMock()
    context = MagicMock()
    context.user_data = {
        "pending_ingestions": {"tok": items},
        "awaiting_date": {"token": "tok", "index": 0},
    }

    await receive_date(update, context)

    assert context.user_data["awaiting_date"] == {"token": "tok", "index": 0}
    assert items[0].expiry_date == date(2026, 9, 20)


@pytest.mark.asyncio
async def test_tapping_a_menu_button_abandons_the_question_silently():
    """"Pantry" is navigation, not a malformed date, and must not be scolded."""
    update = MagicMock()
    update.message.text = "Pantry"
    update.effective_chat.send_message = AsyncMock()
    context = MagicMock()
    context.user_data = {
        "pending_ingestions": {"tok": [stored()]},
        "awaiting_date": {"token": "tok", "index": 0},
    }

    await receive_date(update, context)

    assert "awaiting_date" not in context.user_data
    update.effective_chat.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_text_is_ignored_when_no_date_was_asked_for():
    update = MagicMock()
    update.message.text = "2027-04-16"
    update.effective_chat.send_message = AsyncMock()
    context = MagicMock()
    context.user_data = {}

    await receive_date(update, context)

    update.effective_chat.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_asking_for_a_date_records_which_item_is_being_corrected():
    items = [stored(name="A"), stored(name="B")]
    update = MagicMock()
    update.callback_query.data = f"{INGESTION_CALLBACK_PREFIX}setdate:tok:1"
    update.callback_query.answer = AsyncMock()
    update.effective_chat.send_message = AsyncMock()
    context = MagicMock()
    context.user_data = {"pending_ingestions": {"tok": items}}

    await request_date(update, context)

    assert context.user_data["awaiting_date"] == {"token": "tok", "index": 1}
    assert "B" in update.effective_chat.send_message.call_args.args[0]
