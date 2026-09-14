"""Persistent reply-keyboard button row -- same destination as the
equivalent /command, not a second thing to keep in sync."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from pantrypulse.interface.handlers import _KEYBOARD_ROUTES, register_handlers
from pantrypulse.interface.handlers.commands import (
    MAIN_KEYBOARD,
    expiring,
    help_command,
    pantry,
    recipe,
    today,
    shopping,
    decision,
    start,
)
from pantrypulse.interface.handlers.inventory_actions import remove


def test_keyboard_is_a_plain_text_grid():
    rows = MAIN_KEYBOARD.keyboard
    labels = [button.text for row in rows for button in row]
    # Urgent review leads; less-frequent removal sits below pantry actions.
    assert labels == [
        "Today", "Expiring", "Pantry", "Recipe", "Remove", "Decision", "Shopping",
    ]
    # No emoji anywhere else in this bot's copy; the buttons shouldn't be the exception.
    assert all(label.isascii() and label.isalpha() for label in labels)


def test_keyboard_resizes_rather_than_taking_the_full_screen():
    assert MAIN_KEYBOARD.resize_keyboard is True


@pytest.mark.asyncio
async def test_start_attaches_the_keyboard():
    update = MagicMock()
    update.effective_chat.send_message = AsyncMock()
    await start(update, context=MagicMock())
    assert update.effective_chat.send_message.call_args.kwargs["reply_markup"] is MAIN_KEYBOARD


@pytest.mark.asyncio
async def test_help_attaches_the_keyboard():
    update = MagicMock()
    update.effective_chat.send_message = AsyncMock()
    await help_command(update, context=MagicMock())
    assert update.effective_chat.send_message.call_args.kwargs["reply_markup"] is MAIN_KEYBOARD


@pytest.mark.asyncio
async def test_pantry_attaches_the_keyboard():
    """Someone can reach /pantry without ever having seen /start or /help --
    the button row must not depend on having used either first."""
    update = MagicMock()
    update.effective_chat.send_message = AsyncMock()
    await pantry(update, context=MagicMock())
    assert update.effective_chat.send_message.call_args.kwargs["reply_markup"] is MAIN_KEYBOARD


def test_every_button_label_routes_to_its_matching_command_function():
    assert _KEYBOARD_ROUTES == {
        "Today": today,
        "Pantry": pantry,
        "Expiring": expiring,
        "Recipe": recipe,
        "Shopping": shopping,
        "Decision": decision,
        "Remove": remove,
    }


def test_registered_app_has_one_message_handler_per_keyboard_button():
    from telegram.ext import Application, MessageHandler

    from pantrypulse.interface.config import Settings

    app = Application.builder().token(
        Settings(telegram_bot_token="123456789:AAfaketokenfortestingonly").telegram_bot_token
    ).build()
    register_handlers(app)

    text_handlers = [
        h
        for group in app.handlers.values()
        for h in group
        if isinstance(h, MessageHandler) and h.callback in _KEYBOARD_ROUTES.values()
    ]
    assert len(text_handlers) == len(_KEYBOARD_ROUTES)
