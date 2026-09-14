"""/demo — making the product visible to someone opening it for the first time.

Households are keyed by Telegram chat ID, so a new chat is genuinely empty: no
pantry, nothing expiring, nothing to say. Anyone evaluating the bot from a cold
start sees an empty app rather than the behaviour worth looking at. /demo puts
the sample household from build-spec 7.3 in front of them instead.

It routes through the fixtures rather than seeding the database on purpose.
Fixture dates re-anchor to today on every load, so the Best Before / Use By
contrast reads correctly on any day; rows written into DynamoDB would be stale
within days and would read as "everything expired" across a judging window that
runs for three weeks.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from pantrypulse.interface.handlers.commands import DEMO_MODE, _services, demo, pantry


def _update():
    update = MagicMock()
    update.effective_chat.id = 99
    update.effective_chat.send_message = AsyncMock()
    return update


def _context(services=None, user_data=None):
    context = MagicMock()
    context.user_data = {} if user_data is None else user_data
    context.application.bot_data = {"services": services} if services else {}
    return context


@pytest.mark.asyncio
async def test_demo_turns_on_and_says_what_to_look_at():
    update, context = _update(), _context()

    await demo(update, context)

    assert context.user_data[DEMO_MODE] is True
    sent = update.effective_chat.send_message.call_args[0][0]
    # It must be unmistakable that this is not their food.
    assert "not your groceries" in sent
    # And it should point at the beat that makes the product make sense.
    assert "Best Before" in sent and "Use By" in sent


@pytest.mark.asyncio
async def test_demo_is_a_toggle_rather_than_a_one_way_door():
    update, context = _update(), _context(user_data={DEMO_MODE: True})

    await demo(update, context)

    assert DEMO_MODE not in context.user_data
    assert "your own pantry" in update.effective_chat.send_message.call_args[0][0]


def test_demo_mode_routes_reads_to_fixtures_even_when_services_exist():
    """The whole mechanism: demo mode makes _services return None, so every
    read command takes the fixture branch it already had."""
    services = MagicMock()

    assert _services(_context(services=services)) is services
    assert _services(_context(services=services, user_data={DEMO_MODE: True})) is None


@pytest.mark.asyncio
async def test_pantry_shows_the_sample_household_in_demo_mode():
    update = _update()
    services = MagicMock()
    services.inventory.get_inventory.return_value.items = []
    context = _context(services=services, user_data={DEMO_MODE: True})

    await pantry(update, context)

    sent = update.effective_chat.send_message.call_args[0][0]
    assert "Your pantry — 30 items" in sent
    # The real inventory was never consulted.
    services.inventory.get_inventory.assert_not_called()


@pytest.mark.asyncio
async def test_an_empty_real_household_is_still_empty_outside_demo_mode():
    """The problem /demo exists to solve, kept visible: without it, a new chat
    genuinely has nothing to show."""
    update = _update()
    services = MagicMock()
    services.inventory.get_inventory.return_value.items = []
    context = _context(services=services)

    await pantry(update, context)

    assert "empty" in update.effective_chat.send_message.call_args[0][0]


@pytest.mark.asyncio
async def test_sending_a_photo_leaves_demo_mode():
    """Two sets of groceries in play at once, with no way to tell which a row
    belongs to, would be worse than either alone."""
    from pantrypulse.interface.handlers.photos import photo
    from tests.test_photo_handler import _make_update

    update = _make_update()
    context = _context(user_data={DEMO_MODE: True})

    await photo(update, context)

    assert DEMO_MODE not in context.user_data
    said = [call[0][0] for call in update.effective_chat.send_message.call_args_list]
    assert any("switched out of the demo pantry" in text for text in said)


@pytest.mark.asyncio
async def test_a_message_that_is_not_a_photo_leaves_demo_mode_alone():
    """Only a real photo means real groceries. Anything else must not silently
    drop someone out of the sample pantry mid-look."""
    from pantrypulse.interface.handlers.photos import photo
    from tests.test_photo_handler import _make_update

    update = _make_update(has_photo=False)
    context = _context(user_data={DEMO_MODE: True})

    await photo(update, context)

    assert context.user_data[DEMO_MODE] is True
