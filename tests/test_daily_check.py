"""IF-7 — the one message a day.

The done-when is that the contrast is visible *in the message text*: firm on a
safety date, reassuring on a quality one, in the same message. That contrast is
the entire product thesis, since roughly a fifth of consumer food waste comes
from reading a Best Before as a deadline.
"""

from datetime import date

import pytest

from pantrypulse.interface.rendering import render_daily_expiry_check
from pantrypulse.schemas import DateType, ExpirySource, ExpiryRisk, RiskLevel
from pantrypulse.tools.decisions import combine_expiry_issues


def risk(
    name,
    date_type,
    risk_level,
    expiry=date(2026, 9, 7),
    guidance="Use promptly; this is a safety date.",
    source=ExpirySource.OCR,
):
    return ExpiryRisk(
        item_id=f"item-{name}",
        name=name,
        date_type=date_type,
        expiry_date=expiry,
        expiry_source=source,
        confidence=0.9,
        high_risk=date_type is DateType.USE_BY,
        risk_level=risk_level,
        days_from_expiry=1,
        guidance=guidance,
        explanation="rule applied",
    )


def test_a_quiet_day_produces_no_message_at_all():
    """Silence is a correct outcome, not a failure to render."""
    assert render_daily_expiry_check(combine_expiry_issues([])) is None


def test_suppressed_sell_by_items_never_reach_the_daily_message():
    sell_by = risk("Milk", DateType.SELL_BY, RiskLevel.NONE)

    assert render_daily_expiry_check(combine_expiry_issues([sell_by])) is None


def test_safety_and_quality_items_are_contrasted_in_one_message():
    """The demo beat: reassure about the yogurt and hold firm on the deli
    item, in the same message."""
    turkey = risk("Deli turkey", DateType.USE_BY, RiskLevel.HIGH)
    yogurt = risk(
        "Greek yogurt",
        DateType.BEST_BY,
        RiskLevel.LOW,
        expiry=date(2026, 9, 3),
        guidance="Past its Best Before date: check quality before using; it is not automatically unsafe.",
    )

    rendered = render_daily_expiry_check(combine_expiry_issues([turkey, yogurt]))

    # One message, not one per item.
    assert rendered.count("PantryPulse") == 1
    assert "Deli turkey" in rendered and "Greek yogurt" in rendered
    # The headings carry the contrast.
    assert "Use these first" in rendered
    assert "not a bin" in rendered
    # And the quality half explicitly refuses the safety reading.
    assert "quality, not safety" in rendered
    # The safety item comes first; what to act on should not be buried.
    assert rendered.index("Deli turkey") < rendered.index("Greek yogurt")


def test_every_row_states_its_date_and_where_that_date_came_from():
    """CLAUDE.md: expiry_source is shown on every row, without exception. An
    estimate must never be able to pass for a date someone actually read."""
    estimated = risk(
        "Bellwether Farms Yogurt",
        DateType.ESTIMATED,
        RiskLevel.MEDIUM,
        expiry=date(2026, 9, 20),
        source=ExpirySource.SHELF_LIFE_TABLE,
        guidance="This is a low-confidence estimate; inspect before using.",
    )

    rendered = render_daily_expiry_check(combine_expiry_issues([estimated]))

    assert "estimated from category" in rendered
    assert "Est. 20 Sep 2026" in rendered


def test_the_year_is_never_dropped_from_a_date():
    """A missing year hid a two-year misread in live testing."""
    rendered = render_daily_expiry_check(
        combine_expiry_issues([risk("Chicken stock", DateType.USE_BY, RiskLevel.HIGH,
                                    expiry=date(2027, 4, 16))])
    )

    assert "Use By 16 Apr 2027" in rendered


def test_each_item_carries_its_own_guidance_rather_than_one_blanket_line():
    firm = risk("Deli turkey", DateType.USE_BY, RiskLevel.HIGH,
                guidance="Use promptly; this is a safety date.")
    gentle = risk("Greek yogurt", DateType.BEST_BY, RiskLevel.LOW,
                  expiry=date(2026, 9, 3),
                  guidance="Past its Best Before date: check quality before using; it is not automatically unsafe.")

    rendered = render_daily_expiry_check(combine_expiry_issues([firm, gentle]))

    assert "Use promptly; this is a safety date." in rendered
    assert "not automatically unsafe" in rendered


@pytest.mark.asyncio
async def test_today_command_answers_even_when_there_is_nothing_to_say():
    """A scheduled run stays silent, but someone who asks directly deserves an
    answer rather than nothing happening."""
    from unittest.mock import AsyncMock, MagicMock

    from pantrypulse.interface.handlers.commands import today

    from pantrypulse.schemas import RescueStats

    update = MagicMock()
    update.effective_chat.id = 1
    update.effective_chat.send_message = AsyncMock()
    services = MagicMock()
    services.inventory.get_inventory.return_value.items = []
    services.feedback.get_rescue_stats.return_value.stats = RescueStats(
        household_id="telegram:1", period="2026-09",
        rescued_count=0, tossed_count=0, estimated_value_saved=0.0,
    )
    context = MagicMock()
    # Both must be real dicts. _services ignores a non-dict bot_data, and reads
    # user_data for the demo flag -- a MagicMock answers truthily to both and
    # would silently route this down the fixture path instead.
    context.application.bot_data = {"services": services}
    context.user_data = {}

    await today(update, context)

    sent = update.effective_chat.send_message.call_args[0][0]
    assert "Nothing needs your attention" in sent
    # Nothing measured yet, so nothing is claimed. "0 rescued, ~$0 saved"
    # would be asserting a result rather than reporting one.
    assert "rescued" not in sent


def test_today_is_registered_as_both_a_command_and_a_button():
    from telegram.ext import Application, CommandHandler

    from pantrypulse.interface.config import Settings
    from pantrypulse.interface.handlers import _KEYBOARD_ROUTES, register_handlers
    from pantrypulse.interface.handlers.commands import today

    app = Application.builder().token(
        Settings(telegram_bot_token="123456789:AAfaketokenfortestingonly").telegram_bot_token
    ).build()
    register_handlers(app)

    commands = {
        cmd
        for group in app.handlers.values()
        for h in group
        if isinstance(h, CommandHandler)
        for cmd in h.commands
    }
    assert "today" in commands
    assert _KEYBOARD_ROUTES["Today"] is today


# --- IF-14: the rescue counter -------------------------------------------


def stats_for(rescued, tossed, saved):
    from pantrypulse.schemas import RescueStats

    return RescueStats(
        household_id="telegram:1", period="2026-09",
        rescued_count=rescued, tossed_count=tossed, estimated_value_saved=saved,
    )


def test_the_counter_reports_the_month_in_the_daily_message():
    """IF-14's done-when: the line renders in the daily message. It closes the
    loop the Used it / Still good / Tossed it buttons opened."""
    rendered = render_daily_expiry_check(
        combine_expiry_issues([risk("Deli turkey", DateType.USE_BY, RiskLevel.HIGH)]),
        stats_for(7, 2, 31.4),
    )

    assert "This month: 7 rescued, 2 tossed. ~$31 saved." in rendered


def test_nothing_measured_means_nothing_claimed():
    """Impact is measured rather than asserted (CLAUDE.md), which cuts both
    ways: a household that has pressed no buttons has no impact to report, and
    "0 rescued, ~$0 saved" would be a claim rather than a measurement."""
    from pantrypulse.interface.rendering import render_rescue_stats_if_measured

    assert render_rescue_stats_if_measured(stats_for(0, 0, 0.0)) is None
    assert render_rescue_stats_if_measured(None) is None


def test_a_month_with_only_losses_is_still_reported_honestly():
    """Tossing things is the outcome the counter exists to make visible. It
    must not hide a bad month by only rendering when something was rescued."""
    from pantrypulse.interface.rendering import render_rescue_stats_if_measured

    assert render_rescue_stats_if_measured(stats_for(0, 3, 0.0)) == (
        "This month: 0 rescued, 3 tossed. ~$0 saved."
    )


def test_the_counter_never_appears_without_a_daily_message():
    """Silence on a quiet day stays silent for the scheduled run; the counter
    does not become a reason to send an unprompted message."""
    assert render_daily_expiry_check(combine_expiry_issues([]), stats_for(7, 2, 31.4)) is None
