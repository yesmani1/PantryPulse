"""Callback handling for the expiry-item feedback buttons (IF-13)."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from pantrypulse.fixtures import load_expiry_risks
from pantrypulse.interface import messages
from pantrypulse.interface.handlers.commands import (
    FEEDBACK_CALLBACK_PREFIX,
    _active_inventory,
    _services,
)
from pantrypulse.interface.services import household_for_chat
from pantrypulse.schemas import FeedbackResponse, InventoryItemPatch, ItemStatus, RecordFeedbackRequest, UpdateInventoryItemRequest

logger = logging.getLogger(__name__)

_RESPONSE_LABEL = {
    FeedbackResponse.USED.value: "Used it",
    FeedbackResponse.STILL_GOOD.value: "Still good",
    FeedbackResponse.TOSSED.value: "Tossed it",
}


async def feedback_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Entry point for a tap on any expiry-item feedback button."""
    query = update.callback_query
    if query is None or not query.data or not query.data.startswith(FEEDBACK_CALLBACK_PREFIX):
        return

    payload = query.data[len(FEEDBACK_CALLBACK_PREFIX):]
    try:
        response, item_id = payload.split(":", 1)
    except ValueError:
        return
    if response not in _RESPONSE_LABEL:
        return

    # Clears the button's loading spinner in the Telegram client.
    await query.answer()

    chat = update.effective_chat
    if chat is None:
        return

    # Via _services, not bot_data directly: reading bot_data here skipped the
    # demo check, so a tap on a sample item wrote a real feedback event against
    # a fixture id that is in nobody's pantry, inflating the household's real
    # rescue counter with interactions that never involved food.
    services = _services(context)
    name = "that item"
    if services is None:
        risk = next((candidate for candidate in load_expiry_risks() if candidate.item_id == item_id), None)
        name = risk.name if risk is not None else name
    else:
        household_id = household_for_chat(chat.id)
        items = _active_inventory(services, household_id)
        item = next((stored for stored in items if stored.item_id == item_id), None)
        name = item.name if item is not None else name
        services.feedback.record_feedback(
            RecordFeedbackRequest(
                household_id=household_id,
                item_id=item_id,
                response=FeedbackResponse(response),
            )
        )
        # A used or tossed item is no longer pantry inventory and must not be
        # offered again by /expiring.  "Still good" is feedback only.
        terminal_status = {
            FeedbackResponse.USED: ItemStatus.USED,
            FeedbackResponse.TOSSED: ItemStatus.TOSSED,
        }.get(FeedbackResponse(response))
        if terminal_status is not None:
            services.inventory.update_inventory_item(
                UpdateInventoryItemRequest(
                    household_id=household_id,
                    item_id=item_id,
                    patch=InventoryItemPatch(status=terminal_status),
                )
            )

    logger.info(
        "feedback response=%s item_id=%s from chat_id=%s", response, item_id, chat.id
    )
    message = messages.FEEDBACK_SAVED_ACK if services is not None else messages.FEEDBACK_ACK
    await chat.send_message(message.format(name=name, response=_RESPONSE_LABEL[response]))
