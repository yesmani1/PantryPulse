"""Durable external-order and receipt actions for the shopping flow."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from uuid import uuid4

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from pantrypulse.interface.handlers.commands import MAIN_KEYBOARD, _services
from pantrypulse.interface.handlers.photos import parse_date
from pantrypulse.interface.services import household_for_chat
from pantrypulse.persistence.sessions import InteractionSessionRepository
from pantrypulse.schemas import (
    AddInventoryItemsRequest, Category, DateType, ExpirySource,
    GetInventoryRequest, InventoryItemPatch, ItemStatus, PantryItem,
    ShoppingList, UpdateInventoryItemRequest,
)
from pantrypulse.tools.domain import derive_high_risk
from pantrypulse.tools.orders import infer_order_category, normalise_item_name
from pantrypulse.tools.shelf_life import estimate_shelf_life

logger = logging.getLogger(__name__)

ORDER_MARK_CALLBACK = "order:mark"
ORDER_EXCLUDE_CALLBACK = "order:exclude"
ORDER_FORCE_CALLBACK = "order:force"
ORDER_RECEIVE_CALLBACK = "order:receive"
ORDER_BULK_RECEIVE_CALLBACK = "order:bulk"
_RECEIPT_CURSOR = "ordered_receipt"


def _ordered_items(services, household_id: str) -> list[PantryItem]:
    return services.inventory.get_inventory(
        GetInventoryRequest(household_id=household_id, statuses=[ItemStatus.ORDERED])
    ).items


def _new_ordered_item(household_id: str, entry) -> PantryItem:
    """Store a shopping entry safely until a receipt is confirmed."""
    now = datetime.now(timezone.utc)
    return PantryItem(
        household_id=household_id, item_id=f"order-{uuid4().hex}", name=entry.name,
        # A list name alone must not masquerade as a food classification.  The
        # specific category is inferred only at bulk receipt time.
        category=Category.PANTRY, quantity=entry.quantity or 1, unit=entry.unit or "item",
        purchase_date=date.today(), expiry_date=None, date_type=DateType.NONE,
        expiry_source=ExpirySource.SHELF_LIFE_TABLE, confidence=0.45,
        sealed=False, high_risk=False, status=ItemStatus.ORDERED,
        needs_confirmation=True, created_at=now, updated_at=now,
    )


def _existing_names(services, household_id: str) -> set[str]:
    items = services.inventory.get_inventory(GetInventoryRequest(household_id=household_id)).items
    return {
        normalise_item_name(item.name) for item in items
        if item.status in {ItemStatus.ACTIVE, ItemStatus.ORDERED}
    }


async def _save_order(services, repository, household_id: str, shopping_list: ShoppingList, *, include_duplicates: bool) -> tuple[int, list[str]]:
    existing = _existing_names(services, household_id)
    duplicates = [entry.name for entry in shopping_list.items if normalise_item_name(entry.name) in existing]
    entries = shopping_list.items if include_duplicates else [
        entry for entry in shopping_list.items if normalise_item_name(entry.name) not in existing
    ]
    if entries:
        items = [_new_ordered_item(household_id, entry) for entry in entries]
        await asyncio.to_thread(
            services.inventory.add_inventory_items,
            AddInventoryItemsRequest(items=items, idempotency_key=str(uuid4())),
        )
    if isinstance(repository, InteractionSessionRepository):
        await asyncio.to_thread(repository.delete, household_id, "approved-shopping")
    return len(entries), duplicates


async def order_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Record an external order, resolve duplicates, or start receipt handling."""
    query, chat = update.callback_query, update.effective_chat
    if query is None or chat is None or not query.data:
        return
    parts = query.data.split(":", 2)
    action = ":".join(parts[:2])
    token = parts[2] if len(parts) == 3 else None
    if action not in {ORDER_MARK_CALLBACK, ORDER_EXCLUDE_CALLBACK, ORDER_FORCE_CALLBACK, ORDER_RECEIVE_CALLBACK, ORDER_BULK_RECEIVE_CALLBACK}:
        return
    await query.answer()
    services = _services(context)
    if services is None:
        await chat.send_message("Orders are unavailable in demo mode.", reply_markup=MAIN_KEYBOARD)
        return
    household_id = household_for_chat(chat.id)
    repository = getattr(services, "interactions", None)

    if action == ORDER_RECEIVE_CALLBACK:
        item = next((row for row in _ordered_items(services, household_id) if row.item_id == token), None)
        if item is None:
            await chat.send_message("That ordered item is no longer awaiting receipt.", reply_markup=MAIN_KEYBOARD)
            return
        context.user_data[_RECEIPT_CURSOR] = item.item_id
        if isinstance(repository, InteractionSessionRepository):
            await asyncio.to_thread(repository.set_cursor, household_id, _RECEIPT_CURSOR, item.item_id)
        await chat.send_message(
            f"{item.name} received. What expiry date is printed on it? Send YYYY-MM-DD, for example 2027-04-16."
        )
        return

    if action == ORDER_BULK_RECEIVE_CALLBACK:
        ordered = _ordered_items(services, household_id)
        activated, pending = [], []
        for item in ordered:
            category = infer_order_category(item.name)
            if category is None:
                pending.append(item.name)
                continue
            estimate = estimate_shelf_life(category, date.today())
            try:
                await asyncio.to_thread(services.inventory.update_inventory_item, UpdateInventoryItemRequest(
                    household_id=household_id, item_id=item.item_id,
                    patch=InventoryItemPatch(
                        category=category, purchase_date=date.today(), expiry_date=estimate.expiry_date,
                        date_type=estimate.date_type, expiry_source=estimate.expiry_source,
                        confidence=estimate.confidence, high_risk=derive_high_risk(category, item.name),
                        status=ItemStatus.ACTIVE, needs_confirmation=False,
                    ),
                ))
                activated.append(item.name)
            except Exception:
                logger.warning("could not bulk receive ordered item_id=%s", item.item_id, exc_info=True)
                pending.append(item.name)
        body = f"Received {len(activated)} item(s) with clearly labelled shelf-life estimates."
        if pending:
            body += "\n\nStill awaiting an individual expiry date: " + ", ".join(pending) + "."
        await chat.send_message(body, reply_markup=MAIN_KEYBOARD)
        return

    shopping_list = None
    if action == ORDER_MARK_CALLBACK and token == "approved-shopping" and isinstance(repository, InteractionSessionRepository):
        stored = await asyncio.to_thread(repository.load, household_id, token, kind="approved_shopping")
        shopping_list = ShoppingList.model_validate(stored.payload["shopping"]) if stored else None
    elif action in {ORDER_EXCLUDE_CALLBACK, ORDER_FORCE_CALLBACK} and token and isinstance(repository, InteractionSessionRepository):
        stored = await asyncio.to_thread(repository.load, household_id, token, kind="order_confirmation")
        shopping_list = ShoppingList.model_validate(stored.payload["shopping"]) if stored else None
    if shopping_list is None:
        await chat.send_message("That shopping list has expired. Ask for /shopping again.", reply_markup=MAIN_KEYBOARD)
        return

    if action == ORDER_MARK_CALLBACK:
        duplicates = [entry.name for entry in shopping_list.items if normalise_item_name(entry.name) in _existing_names(services, household_id)]
        if duplicates:
            confirmation = uuid4().hex[:16]
            await asyncio.to_thread(repository.save, household_id, confirmation, "order_confirmation", {"shopping": shopping_list.model_dump(mode="json")})
            await chat.send_message(
                "Already in your pantry or awaiting receipt: " + ", ".join(duplicates) + ".\n\nWhat would you like to do?",
                reply_markup=InlineKeyboardMarkup([[ 
                    InlineKeyboardButton("Remove already present", callback_data=f"{ORDER_EXCLUDE_CALLBACK}:{confirmation}"),
                    InlineKeyboardButton("Order anyway", callback_data=f"{ORDER_FORCE_CALLBACK}:{confirmation}"),
                ]]),
            )
            return

    try:
        count, _ = await _save_order(
            services, repository, household_id, shopping_list,
            include_duplicates=action == ORDER_FORCE_CALLBACK,
        )
        if action in {ORDER_EXCLUDE_CALLBACK, ORDER_FORCE_CALLBACK} and isinstance(repository, InteractionSessionRepository):
            await asyncio.to_thread(repository.delete, household_id, token)
    except Exception:
        logger.warning("could not save external order", exc_info=True)
        await chat.send_message("I couldn't record that order. Nothing was changed; please try again.", reply_markup=MAIN_KEYBOARD)
        return
    await chat.send_message(
        f"Order recorded for {count} item(s). They are now marked Ordered — awaiting receipt in Pantry. "
        "PantryPulse does not place the grocery order itself.", reply_markup=MAIN_KEYBOARD,
    )


async def ordered_receipt_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Activate one received order after its household-entered expiry date."""
    chat, message = update.effective_chat, update.message
    if chat is None or message is None or not message.text:
        return
    services = _services(context)
    if services is None:
        return
    household_id = household_for_chat(chat.id)
    repository = getattr(services, "interactions", None)
    item_id = context.user_data.get(_RECEIPT_CURSOR)
    if item_id is None and isinstance(repository, InteractionSessionRepository):
        item_id = await asyncio.to_thread(repository.get_cursor, household_id, _RECEIPT_CURSOR)
    if not item_id:
        return
    parsed = parse_date(message.text)
    if parsed is None:
        await chat.send_message("I couldn't read that as a date. Try YYYY-MM-DD — for example 2027-04-16.")
        return
    item = next((row for row in _ordered_items(services, household_id) if row.item_id == item_id), None)
    if item is None:
        await chat.send_message("That ordered item is no longer awaiting receipt.", reply_markup=MAIN_KEYBOARD)
        return
    category = infer_order_category(item.name) or Category.PANTRY
    try:
        await asyncio.to_thread(services.inventory.update_inventory_item, UpdateInventoryItemRequest(
            household_id=household_id, item_id=item.item_id,
            patch=InventoryItemPatch(category=category, purchase_date=date.today(), expiry_date=parsed,
                date_type=DateType.ESTIMATED, expiry_source=ExpirySource.USER_CONFIRMED,
                confidence=1.0, high_risk=derive_high_risk(category, item.name),
                status=ItemStatus.ACTIVE, needs_confirmation=False),
        ))
    except Exception:
        logger.warning("could not receive ordered item_id=%s", item.item_id, exc_info=True)
        await chat.send_message("I couldn't update that item. Please try again.", reply_markup=MAIN_KEYBOARD)
        return
    context.user_data.pop(_RECEIPT_CURSOR, None)
    if isinstance(repository, InteractionSessionRepository):
        await asyncio.to_thread(repository.clear_cursor, household_id, _RECEIPT_CURSOR)
    await chat.send_message(f"Saved {item.name} to your active pantry with your confirmed expiry date.", reply_markup=MAIN_KEYBOARD)
