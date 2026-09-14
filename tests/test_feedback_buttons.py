"""IF-13 -- expiry-risk rendering, the sell_by suppression rule, and the
three feedback-button callbacks."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from pantrypulse.fixtures import load_expiry_risks
from pantrypulse.interface.handlers.commands import FEEDBACK_CALLBACK_PREFIX, expiring
from pantrypulse.interface.handlers.feedback_actions import feedback_action
from pantrypulse.interface.rendering import is_actionable, render_expiry_risk
from pantrypulse.schemas import DateType, FeedbackResponse


@pytest.fixture
def risks():
    return load_expiry_risks()


def test_sell_by_risk_is_never_actionable(risks):
    """CLAUDE.md: a sell_by date is never a consumer deadline. Suppress
    entirely, not just soften the wording."""
    sell_by = next(r for r in risks if r.date_type is DateType.SELL_BY)
    assert is_actionable(sell_by) is False


def test_the_other_three_risk_types_are_actionable(risks):
    actionable_types = {r.date_type for r in risks if is_actionable(r)}
    assert actionable_types == {DateType.BEST_BY, DateType.USE_BY, DateType.ESTIMATED}


def test_render_shows_guidance_not_just_the_date(risks):
    turkey = next(r for r in risks if r.date_type is DateType.USE_BY)
    card = render_expiry_risk(turkey)
    assert "Use By" in card
    assert turkey.guidance in card


def _make_command_update():
    update = MagicMock()
    update.effective_chat.id = 12345
    update.effective_chat.send_message = AsyncMock()
    return update


@pytest.mark.asyncio
async def test_expiring_command_never_sends_the_suppressed_sell_by_item(risks):
    update = _make_command_update()
    await expiring(update, context=MagicMock())

    sent_texts = [call.args[0] for call in update.effective_chat.send_message.call_args_list]
    sell_by = next(r for r in risks if r.date_type is DateType.SELL_BY)
    assert not any(sell_by.name in text for text in sent_texts)


@pytest.mark.asyncio
async def test_expiring_command_sends_one_message_per_actionable_risk(risks):
    update = _make_command_update()
    await expiring(update, context=MagicMock())

    expected = len([r for r in risks if is_actionable(r)])
    assert update.effective_chat.send_message.call_count == expected


def _make_callback_update(data: str):
    update = MagicMock()
    update.effective_chat.id = 12345
    update.callback_query.data = data
    update.callback_query.answer = AsyncMock()
    update.effective_chat.send_message = AsyncMock()
    return update


@pytest.mark.asyncio
async def test_each_feedback_response_acknowledges_honestly(risks):
    turkey = next(r for r in risks if r.date_type is DateType.USE_BY)
    for response in (
        FeedbackResponse.USED.value,
        FeedbackResponse.STILL_GOOD.value,
        FeedbackResponse.TOSSED.value,
    ):
        update = _make_callback_update(f"{FEEDBACK_CALLBACK_PREFIX}{response}:{turkey.item_id}")
        await feedback_action(update, context=MagicMock())

        update.callback_query.answer.assert_awaited_once()
        sent = update.effective_chat.send_message.call_args[0][0]
        assert turkey.name in sent
        assert "isn't saved anywhere yet" in sent


@pytest.mark.asyncio
async def test_unknown_item_id_still_acknowledges_generically():
    update = _make_callback_update(f"{FEEDBACK_CALLBACK_PREFIX}used:not_a_real_id")
    await feedback_action(update, context=MagicMock())
    sent = update.effective_chat.send_message.call_args[0][0]
    assert "that item" in sent


@pytest.mark.asyncio
async def test_live_service_feedback_is_persisted_without_loading_a_fixture(monkeypatch):
    update = _make_callback_update(f"{FEEDBACK_CALLBACK_PREFIX}used:itm_001")
    services = MagicMock()
    stored = MagicMock(item_id="itm_001", name="Deli Turkey")
    services.inventory.get_inventory.return_value.items = [stored]
    context = MagicMock()
    context.application.bot_data = {"services": services}
    # Real dict: _services reads user_data for the demo flag, and a MagicMock
    # answers .get() truthily, which would route this to the sample pantry.
    context.user_data = {}
    monkeypatch.setattr(
        "pantrypulse.interface.handlers.feedback_actions.load_expiry_risks",
        lambda: (_ for _ in ()).throw(AssertionError("live feedback must not load fixtures")),
    )

    await feedback_action(update, context)

    saved = services.feedback.record_feedback.call_args.args[0]
    assert saved.household_id == "telegram:12345"
    assert saved.item_id == "itm_001"
    assert saved.response is FeedbackResponse.USED
    update_request = services.inventory.update_inventory_item.call_args.args[0]
    assert update_request.item_id == "itm_001"
    assert update_request.patch.status.value == "used"
    assert "updates your rescue history" in update.effective_chat.send_message.call_args.args[0]


@pytest.mark.asyncio
async def test_still_good_keeps_live_item_active():
    update = _make_callback_update(f"{FEEDBACK_CALLBACK_PREFIX}still_good:itm_001")
    services = MagicMock()
    services.inventory.get_inventory.return_value.items = [MagicMock(item_id="itm_001", name="Deli Turkey")]
    context = MagicMock()
    context.application.bot_data = {"services": services}
    context.user_data = {}

    await feedback_action(update, context)

    services.inventory.update_inventory_item.assert_not_called()


@pytest.mark.asyncio
async def test_malformed_callback_data_is_ignored():
    update = _make_callback_update(f"{FEEDBACK_CALLBACK_PREFIX}not_a_valid_response:itm_001")
    await feedback_action(update, context=MagicMock())
    update.callback_query.answer.assert_not_awaited()
    update.effective_chat.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_unrelated_callback_data_is_ignored():
    update = _make_callback_update("recipe:cook")
    await feedback_action(update, context=MagicMock())
    update.callback_query.answer.assert_not_awaited()


@pytest.mark.asyncio
async def test_feedback_on_a_sample_item_is_never_written_to_the_real_log():
    """Found by driving every button against the live bot: this handler read
    bot_data["services"] directly instead of going through _services, so it
    never saw the demo flag. Tapping Used it on a sample item wrote a real
    feedback event against a fixture id that is in nobody's pantry -- three
    taps while smoke-testing inflated a live household's rescue counter with
    interactions that never involved any food.
    """
    from pantrypulse.interface.handlers.commands import DEMO_MODE

    update = _make_callback_update(f"{FEEDBACK_CALLBACK_PREFIX}used:itm_yogurt_001")
    services = MagicMock()
    context = MagicMock()
    context.application.bot_data = {"services": services}
    context.user_data = {DEMO_MODE: True}

    await feedback_action(update, context)

    services.feedback.record_feedback.assert_not_called()
    services.inventory.get_inventory.assert_not_called()
    # And it says plainly that nothing was stored, rather than claiming a save.
    sent = update.effective_chat.send_message.call_args.args[0]
    assert "isn't saved anywhere yet" in sent
