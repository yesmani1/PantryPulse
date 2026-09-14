"""Bounding what photo ingestion can cost.

Every photo is two Bedrock vision calls carrying a downscaled image, which is
the only expensive thing this bot does; every other command is deterministic
and free. The bot has to stay reachable by judges through the judging window,
so it cannot be locked down, which leaves a public endpoint where one scripted
sender could spend the project's credits in an afternoon.

Two windows, because they fail differently. The per-chat limit keeps any single
conversation polite and is generous enough that nobody evaluating the bot in
good faith will meet it. The global limit is the one that actually protects the
budget: a determined sender can open any number of Telegram accounts, so a
per-chat cap alone bounds nothing.

Both are in-process and reset when the bot restarts. That is the honest limit
of this: it is a cost circuit breaker, not a security control, and the thing
that actually stops a runaway spend is the budget action (BE-30).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

WINDOW = timedelta(hours=1)

# Comfortably above evaluating the bot properly -- a judge sending a receipt,
# a package, and a few retries is nowhere near this.
PER_CHAT_PHOTOS_PER_HOUR = 10

# Across everyone. At two vision calls each this caps the burn rate near 240
# model invocations an hour, which is affordable for the whole judging window.
GLOBAL_PHOTOS_PER_HOUR = 120

_CHAT_KEY = "photo_times"
_GLOBAL_KEY = "photo_times_global"


def _recent(stamps: list[datetime], now: datetime) -> list[datetime]:
    cutoff = now - WINDOW
    return [stamp for stamp in stamps if stamp > cutoff]


def check_photo_allowance(user_data, bot_data, *, now: datetime | None = None) -> str | None:
    """Record a photo and report which limit, if any, it exceeded.

    Returns None when the photo may be processed, otherwise "chat" or "global".
    Nothing is recorded when the photo is refused, so a sender who keeps
    hammering does not push their own window further out.
    """
    now = now or datetime.now(timezone.utc)

    # Either store may be absent or not a dict: bot_data is only a dict in a
    # running Application, and refusing to rate limit is safer than raising
    # inside the one handler that spends money.
    chat_store = user_data if isinstance(user_data, dict) else {}
    global_store = bot_data if isinstance(bot_data, dict) else {}

    chat_times = _recent(chat_store.get(_CHAT_KEY, []), now)
    if len(chat_times) >= PER_CHAT_PHOTOS_PER_HOUR:
        chat_store[_CHAT_KEY] = chat_times
        return "chat"

    global_times = _recent(global_store.get(_GLOBAL_KEY, []), now)
    if len(global_times) >= GLOBAL_PHOTOS_PER_HOUR:
        global_store[_GLOBAL_KEY] = global_times
        return "global"

    chat_store[_CHAT_KEY] = chat_times + [now]
    global_store[_GLOBAL_KEY] = global_times + [now]
    return None
