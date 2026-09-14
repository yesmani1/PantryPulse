"""Photo upload handler (IF-2).

Temp storage, not permanent: the file exists on disk only long enough to
report its size back to the user. IF-4 replaces the delete-on-finally below
with a call into analyze_grocery_image() — the download and cleanup shape
here does not otherwise change.
"""

import logging
import hashlib
import os
import tempfile
import asyncio
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from pantrypulse.interface import messages
from pantrypulse.interface.handlers.commands import DEMO_MODE, MAIN_KEYBOARD
from pantrypulse.interface.rate_limit import check_photo_allowance
from pantrypulse.interface.rendering import render_item
from pantrypulse.interface.services import household_for_chat
from pantrypulse.persistence.sessions import DuplicatePhotoError, IngestionSessionRepository, InteractionSessionRepository
from pantrypulse.schemas import AnalyzeGroceryImageRequest, DateType, ExpirySource, ImageMode
from pantrypulse.tools.ingestion import downscale_image

# Accepted date spellings, most explicit first. Day-first before month-first
# because "06/09/2027" is ambiguous and this bot is not US-only; the confirming
# message echoes the parsed date back so a misread is visible immediately.
_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y")


def parse_date(text: str) -> date | None:
    """Read a household-typed date, or None if it is not a date at all."""
    cleaned = " ".join(text.strip().replace(",", " ").split())
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None

logger = logging.getLogger(__name__)

INGESTION_CALLBACK_PREFIX = "ingest:"
_PENDING_INGESTIONS = "pending_ingestions"
_AWAITING_DATE = "awaiting_date"

# The reply keyboard offers one edit button per item, so the preview stays a
# readable message rather than a wall of buttons.
MAX_PREVIEW_ITEMS = 5

_MAIN_KEYBOARD_LABELS = {
    button.text for row in MAIN_KEYBOARD.keyboard for button in row
}


def preview_text(items: list) -> str:
    """The preview body: every item with its date, source, and any warning."""
    shown = items[:MAX_PREVIEW_ITEMS]
    text = "\n\n".join(render_item(item) for item in shown)
    if len(items) > len(shown):
        text += f"\n\n...and {len(items) - len(shown)} more"
    return text


def preview_markup(token: str, items: list) -> InlineKeyboardMarkup:
    """Confirm/discard, plus a date-correction button for each shown item.

    A wrong date must be fixable on its own. Accept-everything or
    discard-everything forces someone to re-send the photo over one bad digit.
    """
    rows = []
    for index, item in enumerate(items[:MAX_PREVIEW_ITEMS]):
        flag = "⚠ " if item.needs_confirmation else ""
        label = f"{flag}Set date: {item.name[:24]}"
        rows.append([
            InlineKeyboardButton(
                label, callback_data=f"{INGESTION_CALLBACK_PREFIX}setdate:{token}:{index}"
            )
        ])
    rows.append([
        InlineKeyboardButton(
            "Add to pantry", callback_data=f"{INGESTION_CALLBACK_PREFIX}confirm:{token}"
        ),
        InlineKeyboardButton(
            "Discard", callback_data=f"{INGESTION_CALLBACK_PREFIX}cancel:{token}"
        ),
    ])
    return InlineKeyboardMarkup(rows)


async def _pending_preview(context, household_id: str, token: str, services) -> tuple[list, str | None]:
    """Load a preview from memory locally or DynamoDB in stateless Lambda."""
    pending = context.user_data.setdefault(_PENDING_INGESTIONS, {})
    items = pending.get(token)
    fingerprints = context.user_data.setdefault("pending_ingestion_fingerprints", {})
    if items is not None:
        return items, fingerprints.get(token)
    repository = getattr(services, "ingestion_sessions", None)
    if not isinstance(repository, IngestionSessionRepository):
        return [], None
    stored = await asyncio.to_thread(repository.load, household_id, token)
    if stored is None:
        return [], None
    items = list(stored.items)
    pending[token] = items
    fingerprints[token] = stored.fingerprint
    return items, stored.fingerprint


async def _delete_durable_preview(services, household_id: str, token: str) -> None:
    repository = getattr(services, "ingestion_sessions", None)
    if isinstance(repository, IngestionSessionRepository):
        await asyncio.to_thread(repository.delete, household_id, token)


async def photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Download the photo, confirm receipt, discard it. Entry point for any
    photo message."""
    chat = update.effective_chat
    message = update.message
    if chat is None or message is None or not message.photo:
        return

    # Checked before anything is downloaded or sent to a model, since the point
    # is to not spend the money rather than to spend it and then apologise.
    bot_data = getattr(getattr(context, "application", None), "bot_data", None)
    limit = check_photo_allowance(context.user_data, bot_data)
    if limit is not None:
        logger.warning("photo rate limit (%s) hit by chat_id=%s", limit, chat.id)
        await chat.send_message(
            messages.PHOTO_RATE_LIMITED_GLOBAL if limit == "global"
            else messages.PHOTO_RATE_LIMITED_CHAT,
            reply_markup=MAIN_KEYBOARD,
        )
        return

    # A real photo means there is real inventory to talk about. Staying in the
    # sample pantry from here would leave two sets of groceries in play with no
    # way to tell which a given row belongs to.
    if context.user_data.pop(DEMO_MODE, None):
        await chat.send_message(messages.DEMO_LEFT_BY_PHOTO)

    # Telegram sends several resolutions of the same photo; take the largest.
    largest = message.photo[-1]
    telegram_file = await largest.get_file()

    fd, tmp_path = tempfile.mkstemp(suffix=".jpg", prefix="pantrypulse_")
    os.close(fd)
    destination = Path(tmp_path)

    try:
        await telegram_file.download_to_drive(destination)
        size_kb = destination.stat().st_size / 1024
        logger.info(
            "photo from chat_id=%s file_id=%s size=%.0fKB",
            chat.id, largest.file_id, size_kb,
        )
        bot_data = getattr(getattr(context, "application", None), "bot_data", None)
        services = bot_data.get("services") if isinstance(bot_data, dict) else None
        if services is None:
            await chat.send_message(
                messages.PHOTO_RECEIVED.format(size_kb=size_kb), reply_markup=MAIN_KEYBOARD
            )
            return
        image_bytes = destination.read_bytes()
        items = await asyncio.to_thread(
            services.analyze_photo,
            AnalyzeGroceryImageRequest(
                image_bytes=image_bytes,
                mode=ImageMode.RECEIPT,
                household_id=household_for_chat(chat.id),
            ),
        )
        token = uuid4().hex[:16]
        context.user_data.setdefault(_PENDING_INGESTIONS, {})[token] = items
        normalized = downscale_image(image_bytes)
        fingerprint = hashlib.sha256(normalized).hexdigest()
        context.user_data.setdefault("pending_ingestion_fingerprints", {})[token] = fingerprint
        repository = getattr(services, "ingestion_sessions", None)
        if isinstance(repository, IngestionSessionRepository):
            await asyncio.to_thread(repository.save, household_for_chat(chat.id), token, items, fingerprint)
        unsure = sum(1 for item in items if item.needs_confirmation)
        body = messages.INGESTION_PREVIEW.format(
            count=len(items),
            plural="s" if len(items) != 1 else "",
            items=preview_text(items),
            pronoun="them" if len(items) != 1 else "it",
        )
        if unsure:
            body += "\n\n" + messages.INGESTION_UNVERIFIED.format(
                count=unsure, plural="s" if unsure != 1 else "", verb="are" if unsure != 1 else "is"
            )
        await chat.send_message(body, reply_markup=preview_markup(token, items))
    finally:
        destination.unlink(missing_ok=True)


async def ingestion_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Persist or discard the short-lived preview created for a photo upload."""
    query = update.callback_query
    chat = update.effective_chat
    if query is None or chat is None or not query.data:
        return
    parts = query.data.split(":", 2)
    if len(parts) != 3 or parts[0] != "ingest" or parts[1] not in {"confirm", "cancel", "force"}:
        return
    bot_data = getattr(getattr(context, "application", None), "bot_data", None)
    services = bot_data.get("services") if isinstance(bot_data, dict) else None
    items, fingerprint = await _pending_preview(context, household_for_chat(chat.id), parts[2], services)
    if parts[1] == "confirm":
        unsure = [
            item
            for item in items
            if item.needs_confirmation
        ]
        if unsure:
            # Saving now would store a category estimate for an item whose real
            # date is printed on the package. Make that an explicit choice.
            await query.answer()
            await chat.send_message(
                messages.INGESTION_STILL_UNVERIFIED.format(
                    names=", ".join(item.name for item in unsure)
                ),
                reply_markup=InlineKeyboardMarkup(
                    [[
                        InlineKeyboardButton(
                            "Save as estimates",
                            callback_data=f"{INGESTION_CALLBACK_PREFIX}force:{parts[2]}",
                        ),
                        InlineKeyboardButton(
                            "Discard",
                            callback_data=f"{INGESTION_CALLBACK_PREFIX}cancel:{parts[2]}",
                        ),
                    ]]
                ),
            )
            return
    context.user_data.get(_PENDING_INGESTIONS, {}).pop(parts[2], None)
    context.user_data.get("pending_ingestion_fingerprints", {}).pop(parts[2], None)
    await query.answer()
    if not items:
        await chat.send_message("That photo preview has expired. Please send it again.", reply_markup=MAIN_KEYBOARD)
        return
    if parts[1] == "cancel":
        await _delete_durable_preview(services, household_for_chat(chat.id), parts[2])
        await chat.send_message(messages.INGESTION_CANCELLED, reply_markup=MAIN_KEYBOARD)
        return
    if services is None:
        await chat.send_message("The pantry service is unavailable. Please try again.", reply_markup=MAIN_KEYBOARD)
        return
    try:
        await asyncio.to_thread(services.save_confirmed_items, items, fingerprint)
    except DuplicatePhotoError:
        await _delete_durable_preview(services, household_for_chat(chat.id), parts[2])
        await chat.send_message("That photo was already added to your pantry.", reply_markup=MAIN_KEYBOARD)
        return
    await _delete_durable_preview(services, household_for_chat(chat.id), parts[2])
    await chat.send_message(
        messages.INGESTION_CONFIRMED.format(
            count=len(items), plural="s" if len(items) != 1 else ""
        ),
        reply_markup=MAIN_KEYBOARD,
    )


async def request_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ask for the real date of one previewed item."""
    query = update.callback_query
    chat = update.effective_chat
    if query is None or chat is None or not query.data:
        return
    parts = query.data.split(":", 3)
    if len(parts) != 4 or parts[0] != "ingest" or parts[1] != "setdate":
        return
    token, raw_index = parts[2], parts[3]
    bot_data = getattr(getattr(context, "application", None), "bot_data", None)
    services = bot_data.get("services") if isinstance(bot_data, dict) else None
    items, _ = await _pending_preview(context, household_for_chat(chat.id), token, services)
    await query.answer()
    if items is None or not raw_index.isdigit() or int(raw_index) >= len(items):
        await chat.send_message(messages.INGESTION_EXPIRED, reply_markup=MAIN_KEYBOARD)
        return

    index = int(raw_index)
    context.user_data[_AWAITING_DATE] = {"token": token, "index": index}
    repository = getattr(services, "interactions", None)
    if isinstance(repository, InteractionSessionRepository):
        await asyncio.to_thread(repository.save, household_for_chat(chat.id), token, "ingestion_date", {"index": index})
        await asyncio.to_thread(repository.set_cursor, household_for_chat(chat.id), "ingestion_date", token)
    await chat.send_message(messages.ASK_FOR_DATE.format(name=items[index].name))


async def receive_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Apply a typed date to the item the household was asked about."""
    chat = update.effective_chat
    message = update.message
    awaiting = context.user_data.get(_AWAITING_DATE)
    if chat is None or message is None or not message.text:
        return
    bot_data = getattr(getattr(context, "application", None), "bot_data", None)
    services = bot_data.get("services") if isinstance(bot_data, dict) else None
    repository = getattr(services, "interactions", None)
    if awaiting is None and isinstance(repository, InteractionSessionRepository):
        token = await asyncio.to_thread(repository.get_cursor, household_for_chat(chat.id), "ingestion_date")
        stored = await asyncio.to_thread(repository.load, household_for_chat(chat.id), token, kind="ingestion_date") if token else None
        if stored:
            awaiting = {"token": token, "index": int(stored.payload["index"])}
            context.user_data[_AWAITING_DATE] = awaiting
    if awaiting is None:
        return
    if message.text in _MAIN_KEYBOARD_LABELS:
        # They reached for the menu instead of answering. That is a navigation
        # choice, not a malformed date, so drop the question silently.
        context.user_data.pop(_AWAITING_DATE, None)
        return

    items, fingerprint = await _pending_preview(context, household_for_chat(chat.id), awaiting["token"], services)
    if not items:
        context.user_data.pop(_AWAITING_DATE, None)
        await chat.send_message(messages.INGESTION_EXPIRED, reply_markup=MAIN_KEYBOARD)
        return

    parsed = parse_date(message.text)
    if parsed is None:
        # Keep waiting rather than dropping the correction on the floor.
        await chat.send_message(messages.DATE_NOT_UNDERSTOOD)
        return

    context.user_data.pop(_AWAITING_DATE, None)
    index = awaiting["index"]
    items[index] = items[index].model_copy(
        update={
            "expiry_date": parsed,
            "date_type": DateType.ESTIMATED if items[index].date_type is DateType.NONE else items[index].date_type,
            "expiry_source": ExpirySource.USER_CONFIRMED,
            "confidence": 1.0,
            "needs_confirmation": False,
            "updated_at": datetime.now(timezone.utc),
        }
    )
    ingestion_repository = getattr(services, "ingestion_sessions", None)
    if isinstance(ingestion_repository, IngestionSessionRepository) and fingerprint:
        await asyncio.to_thread(ingestion_repository.save, household_for_chat(chat.id), awaiting["token"], items, fingerprint)
    if isinstance(repository, InteractionSessionRepository):
        await asyncio.to_thread(repository.delete, household_for_chat(chat.id), awaiting["token"])
        await asyncio.to_thread(repository.clear_cursor, household_for_chat(chat.id), "ingestion_date")
    await chat.send_message(
        messages.INGESTION_PREVIEW.format(
            count=len(items),
            plural="s" if len(items) != 1 else "",
            items=preview_text(items),
            pronoun="them" if len(items) != 1 else "it",
        ),
        reply_markup=preview_markup(awaiting["token"], items),
    )
