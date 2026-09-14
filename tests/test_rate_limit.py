"""Bounding what photo ingestion can cost while the bot stays public.

The hackathon rules require the project to remain reachable for testing through
the judging window, so the endpoint cannot be closed. Photo ingestion is the
only expensive path -- two Bedrock vision calls each -- which makes an open
endpoint a way to spend the project's credits.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from pantrypulse.interface.rate_limit import (
    GLOBAL_PHOTOS_PER_HOUR,
    PER_CHAT_PHOTOS_PER_HOUR,
    check_photo_allowance,
)

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


def test_normal_use_is_never_interrupted():
    """A judge sending a receipt, a package, and a couple of retries must not
    meet a limit -- a guard that blocks evaluation is worse than none."""
    user, bot = {}, {}
    for _ in range(4):
        assert check_photo_allowance(user, bot, now=NOW) is None


def test_one_chat_is_capped_without_stopping_everyone_else():
    noisy, bot = {}, {}
    for _ in range(PER_CHAT_PHOTOS_PER_HOUR):
        assert check_photo_allowance(noisy, bot, now=NOW) is None
    assert check_photo_allowance(noisy, bot, now=NOW) == "chat"

    # Someone else's conversation is unaffected.
    assert check_photo_allowance({}, bot, now=NOW) is None


def test_the_global_cap_is_what_actually_protects_the_budget():
    """A per-chat cap alone bounds nothing: anyone can open more Telegram
    accounts. The global window is the real circuit breaker."""
    bot = {}
    for _ in range(GLOBAL_PHOTOS_PER_HOUR):
        # A fresh chat each time, as a determined sender would.
        assert check_photo_allowance({}, bot, now=NOW) is None

    assert check_photo_allowance({}, bot, now=NOW) == "global"


def test_a_refused_photo_does_not_extend_the_window():
    """Otherwise hammering the bot pushes the sender's own recovery further
    out, which punishes impatience rather than protecting anything."""
    user, bot = {}, {}
    for _ in range(PER_CHAT_PHOTOS_PER_HOUR):
        check_photo_allowance(user, bot, now=NOW)
    for _ in range(5):
        check_photo_allowance(user, bot, now=NOW + timedelta(minutes=1))

    # The window still clears one hour after the last *accepted* photo.
    assert check_photo_allowance(user, bot, now=NOW + timedelta(hours=1, seconds=1)) is None


def test_the_window_slides_rather_than_resetting_on_the_hour():
    user, bot = {}, {}
    for _ in range(PER_CHAT_PHOTOS_PER_HOUR):
        check_photo_allowance(user, bot, now=NOW)

    assert check_photo_allowance(user, bot, now=NOW + timedelta(minutes=59)) == "chat"
    assert check_photo_allowance(user, bot, now=NOW + timedelta(hours=1, seconds=1)) is None


def test_a_missing_store_allows_rather_than_raises():
    """bot_data is only a real dict inside a running Application. Refusing to
    rate limit is safer here than raising inside the one handler that spends
    money."""
    assert check_photo_allowance(None, None, now=NOW) is None
    assert check_photo_allowance(MagicMock(), MagicMock(), now=NOW) is None


@pytest.mark.asyncio
async def test_a_limited_photo_is_never_downloaded_or_sent_to_a_model():
    """The point is to not spend the money, not to spend it and apologise."""
    from tests.test_photo_handler import _make_update
    from pantrypulse.interface.handlers.photos import photo

    update = _make_update()
    services = MagicMock()
    context = MagicMock()
    context.user_data = {}
    context.application.bot_data = {"services": services}

    for _ in range(PER_CHAT_PHOTOS_PER_HOUR):
        check_photo_allowance(context.user_data, context.application.bot_data)

    await photo(update, context)

    services.analyze_photo.assert_not_called()
    update.message.photo[-1].get_file.assert_not_awaited()
    assert "paused" in update.effective_chat.send_message.call_args.args[0]
