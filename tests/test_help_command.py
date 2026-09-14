"""IF-6 (the /help third of it) -- lists commands and is honest about
demo-vs-real status."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from pantrypulse.interface.handlers.commands import help_command


@pytest.mark.asyncio
async def test_help_lists_every_registered_command():
    update = MagicMock()
    update.effective_chat.send_message = AsyncMock()

    await help_command(update, context=MagicMock())

    sent = update.effective_chat.send_message.call_args[0][0]
    for command in ("/pantry", "/expiring", "/recipe", "/help"):
        assert command in sent


@pytest.mark.asyncio
async def test_help_is_honest_about_where_dates_come_from():
    """/help used to warn that the pantry was demo data; it now reads real
    inventory, so the honest disclosure that matters is a different one. Dates
    are the claim this product lives or dies on, so /help has to say plainly
    that an unverified date is an estimate and can be corrected."""
    update = MagicMock()
    update.effective_chat.send_message = AsyncMock()

    await help_command(update, context=MagicMock())

    sent = update.effective_chat.send_message.call_args[0][0]
    assert "only if both agree" in sent
    assert "estimate" in sent
    assert "Set date" in sent


@pytest.mark.asyncio
async def test_missing_chat_does_not_raise():
    update = MagicMock()
    update.effective_chat = None
    await help_command(update, context=MagicMock())  # must not raise
