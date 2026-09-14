"""Striking out an item the agent should never have added.

The date-verification gate stops a bad *date* being stored. Nothing stopped a
bad *item*: a hallucinated product name from a misread photo stayed in the
pantry permanently, appeared in every listing, and turned up in the daily
check. An agent that acts on your behalf has to let you undo what it did.

Removal marks the row ItemStatus.REMOVED rather than deleting it, and REMOVED
is deliberately not TOSSED -- tossed means real food went in the bin and counts
against the rescue figures. Charging a household for wasting food that never
existed would corrupt the only number this product actually measures.
"""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from pantrypulse.interface import messages
from pantrypulse.interface.handlers.commands import (
    MAIN_KEYBOARD,
    _active_inventory,
    _services,
)
from pantrypulse.schemas import (
    InventoryItemPatch,
    ItemStatus,
    UpdateInventoryItemRequest,
)

logger = logging.getLogger(__name__)

REMOVE_CALLBACK_PREFIX = "remove:"

# One button per item, so the keyboard stays usable on a phone. A household
# with more than this many items removes them a screenful at a time.
MAX_REMOVABLE = 8


async def remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Offer to strike out any item currently in the pantry."""
    chat = update.effective_chat
    if chat is None:
        return

    logger.info("/remove from chat_id=%s", chat.id)
    services = _services(context)
    if services is None:
        # Demo mode reads fixtures, which are not this household's to change.
        await chat.send_message(messages.REMOVE_NOT_IN_DEMO, reply_markup=MAIN_KEYBOARD)
        return

    items = _active_inventory(services, f"telegram:{chat.id}")
    if not items:
        await chat.send_message(messages.REMOVE_NOTHING_TO_REMOVE, reply_markup=MAIN_KEYBOARD)
        return

    shown = items[:MAX_REMOVABLE]
    rows = [
        [
            InlineKeyboardButton(
                item.name[:48], callback_data=f"{REMOVE_CALLBACK_PREFIX}{item.item_id}"
            )
        ]
        for item in shown
    ]
    body = messages.REMOVE_PROMPT
    if len(items) > len(shown):
        body += f"\n\nShowing {len(shown)} of {len(items)}; run /remove again for the rest."
    await chat.send_message(body, reply_markup=InlineKeyboardMarkup(rows))


async def remove_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Mark one item as never having belonged in the pantry."""
    query = update.callback_query
    chat = update.effective_chat
    if query is None or chat is None or not query.data:
        return
    if not query.data.startswith(REMOVE_CALLBACK_PREFIX):
        return
    item_id = query.data[len(REMOVE_CALLBACK_PREFIX):]
    await query.answer()

    services = _services(context)
    if services is None:
        await chat.send_message(messages.REMOVE_NOT_IN_DEMO, reply_markup=MAIN_KEYBOARD)
        return

    household_id = f"telegram:{chat.id}"
    # Look the name up before the patch, so the confirmation can say what went.
    name = next(
        (item.name for item in _active_inventory(services, household_id)
         if item.item_id == item_id),
        None,
    )
    try:
        services.inventory.update_inventory_item(
            UpdateInventoryItemRequest(
                household_id=household_id,
                item_id=item_id,
                patch=InventoryItemPatch(status=ItemStatus.REMOVED),
            )
        )
    except Exception:
        logger.warning("could not remove item_id=%s", item_id, exc_info=True)
        await chat.send_message(messages.REMOVE_FAILED, reply_markup=MAIN_KEYBOARD)
        return

    logger.info("removed item_id=%s from chat_id=%s", item_id, chat.id)
    await chat.send_message(
        messages.REMOVE_CONFIRMED.format(name=name or "That item"),
        reply_markup=MAIN_KEYBOARD,
    )
