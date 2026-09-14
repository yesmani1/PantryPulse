"""IF-12 turns the combined decision into one Telegram action card."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from pantrypulse.interface.handlers.commands import (
    DECISION_COOK_CALLBACK,
    DECISION_DONATE_CALLBACK,
    decision,
)
from pantrypulse.interface.handlers.decision_actions import decision_action
from pantrypulse.interface.handlers.decision_actions import donation_recipient_action
from pantrypulse.interface.handlers.decision_actions import DONATION_ACCEPT_CALLBACK
from pantrypulse.agents.pantry import SpecialistTask


def _update() -> MagicMock:
    update = MagicMock()
    update.effective_chat.id = 12345
    update.effective_chat.send_message = AsyncMock()
    return update


@pytest.mark.asyncio
async def test_decision_command_renders_one_card_with_actions():
    update = _update()
    context = MagicMock()
    context.user_data = {}
    await decision(update, context)
    assert "PantryPulse decision" in update.effective_chat.send_message.call_args.args[0]
    assert "rescued" in update.effective_chat.send_message.call_args.args[0]
    keyboard = update.effective_chat.send_message.call_args.kwargs["reply_markup"]
    assert {button.text for button in keyboard.inline_keyboard[0]} >= {"Cook", "Shop"}
    assert "combined_decision" in context.user_data


@pytest.mark.asyncio
async def test_cook_action_uses_saved_combined_decision():
    update = _update()
    update.callback_query.data = DECISION_COOK_CALLBACK
    update.callback_query.answer = AsyncMock()
    context = MagicMock()
    context.user_data = {}
    await decision(_update(), context)
    await decision_action(update, context)
    assert "rescues" in update.effective_chat.send_message.call_args.args[0]
    assert "combined_decision" not in context.user_data


@pytest.mark.asyncio
async def test_tokenized_action_recovers_a_durable_session_after_memory_loss():
    update = _update()
    update.callback_query.data = "decision:cook:session123"
    update.callback_query.answer = AsyncMock()
    persisted_context = MagicMock()
    persisted_context.user_data = {}
    await decision(_update(), persisted_context)
    stored = persisted_context.user_data["combined_decision"]
    services = MagicMock()
    services.sessions.load.return_value = stored
    context = MagicMock()
    context.user_data = {}
    context.application.bot_data = {"services": services}
    await decision_action(update, context)
    assert "rescues" in update.effective_chat.send_message.call_args.args[0]
    services.sessions.load.assert_called_once_with("telegram:12345", "session123")
    services.sessions.delete.assert_not_called()


@pytest.mark.asyncio
async def test_donation_action_creates_mock_request():
    update = _update()
    update.callback_query.data = DECISION_DONATE_CALLBACK
    update.callback_query.answer = AsyncMock()
    context = MagicMock()
    context.user_data = {}
    await decision(_update(), context)
    await decision_action(update, context)
    assert "Mock recipient view" in update.effective_chat.send_message.call_args.args[0]
    assert "mock_donation_request" in context.user_data


@pytest.mark.asyncio
async def test_donation_action_surfaces_bounded_donation_agent_copy():
    update = _update()
    update.callback_query.data = DECISION_DONATE_CALLBACK
    update.callback_query.answer = AsyncMock()
    context = MagicMock()
    context.user_data = {}
    await decision(_update(), context)
    services = MagicMock()
    services.optional_specialist_copy.return_value = "I have prepared the mock handoff."
    context.application.bot_data = {"services": services}

    await decision_action(update, context)

    sent = "\n".join(call.args[0] for call in update.effective_chat.send_message.call_args_list)
    assert "AI assist (Donation Agent)" in sent
    assert services.optional_specialist_copy.call_args.args[0] is SpecialistTask.DONATION_COMMUNICATION


@pytest.mark.asyncio
async def test_recipient_acceptance_round_trips_to_household():
    update = _update()
    update.callback_query.data = DECISION_DONATE_CALLBACK
    update.callback_query.answer = AsyncMock()
    context = MagicMock()
    context.user_data = {}
    await decision(_update(), context)
    await decision_action(update, context)
    recipient = _update()
    recipient.callback_query.data = DONATION_ACCEPT_CALLBACK
    recipient.callback_query.answer = AsyncMock()
    await donation_recipient_action(recipient, context)
    assert context.user_data["mock_donation_request"].status.value == "accepted"
    assert "accepted pickup" in recipient.effective_chat.send_message.call_args.args[0]


@pytest.mark.asyncio
async def test_every_action_button_carries_callback_data_and_no_url():
    """Regression: the card was built with InlineKeyboardButton(text, data).

    That second positional parameter is `url`, not `callback_data`, so every
    button became a link button carrying "decision:cook" as its URL. Telegram
    rejected the whole message with BadRequest and the household saw only the
    generic error -- /decision had never once worked in Telegram, while the
    tests passed because they only ever asserted button.text.
    """
    update = _update()
    context = MagicMock()
    context.user_data = {}

    await decision(update, context)

    keyboard = update.effective_chat.send_message.call_args.kwargs["reply_markup"]
    buttons = [button for row in keyboard.inline_keyboard for button in row]
    assert buttons, "the card must offer at least one action"
    for button in buttons:
        assert button.url is None, f"{button.text!r} became a link button"
        assert button.callback_data, f"{button.text!r} has no callback_data"
        assert button.callback_data.startswith("decision:")

    by_text = {button.text: button.callback_data for button in buttons}
    assert by_text["Cook"] == DECISION_COOK_CALLBACK
