"""A shopping list has to be about this week's shop.

Found by reading what the bot actually sends rather than whether it crashed:
/shopping listed seventeen rows -- every perishable in the pantry -- each
saying "likely to run out soon", including Ground Beef whose forecast
depletion date was in 2035.
"""

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from pantrypulse.interface.handlers.commands import (
    DEMO_MODE,
    REPLENISH_HORIZON_DAYS,
    _running_out_soon,
    shopping,
)
from pantrypulse.schemas import DepletionForecast


def forecast(name, days_away):
    return DepletionForecast(
        item_id=f"item-{name}", name=name,
        estimated_daily_consumption=0.2,
        estimated_depletion_date=date.today() + timedelta(days=days_away),
        confidence=0.5, explanation="category default",
    )


def test_only_forecasts_inside_the_horizon_survive():
    kept = _running_out_soon([
        forecast("Sourdough Loaf", 5),
        forecast("Bananas", 30),
        forecast("Ground Beef", 3333),
    ])

    assert [f.name for f in kept] == ["Sourdough Loaf"]


def test_the_boundary_is_inclusive_so_nothing_falls_through_a_crack():
    edge = forecast("Milk", REPLENISH_HORIZON_DAYS)
    just_past = forecast("Butter", REPLENISH_HORIZON_DAYS + 1)

    kept = {f.name for f in _running_out_soon([edge, just_past])}

    assert kept == {"Milk"}


def test_something_already_out_is_still_worth_buying():
    assert [f.name for f in _running_out_soon([forecast("Eggs", -2)])] == ["Eggs"]


@pytest.mark.asyncio
async def test_the_rendered_list_is_a_shop_not_the_whole_pantry():
    update = MagicMock()
    update.effective_chat.id = 1
    update.effective_chat.send_message = AsyncMock()
    context = MagicMock()
    context.user_data = {DEMO_MODE: True}
    context.application.bot_data = {}

    await shopping(update, context)

    sent = update.effective_chat.send_message.call_args.args[0]
    rows = [line for line in sent.splitlines() if line.startswith("- ")]
    assert 0 < len(rows) < 8, f"a weekly shop should be short, got {len(rows)} rows"
    # The 30-item demo pantry must not arrive wholesale.
    assert "Ground Beef" not in sent


def test_weekly_list_keeps_the_seven_soonest_items_when_many_are_due():
    kept = _running_out_soon([forecast(f"Item {index}", 1) for index in range(10)])
    assert len(kept) == 7
    assert [item.name for item in kept] == [f"Item {index}" for index in range(7)]
