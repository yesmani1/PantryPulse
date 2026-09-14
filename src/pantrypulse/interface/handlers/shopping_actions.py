"""Shopping-list approval and small text-edit interactions (IF-9)."""

import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from pantrypulse.interface.handlers.commands import (
    MAIN_KEYBOARD,
    SHOPPING_APPROVE_CALLBACK,
    SHOPPING_ADD_CALLBACK,
    SHOPPING_EDIT_CALLBACK,
    SHOPPING_IGNORE_CALLBACK,
    SHOPPING_NEW_CALLBACK,
    SHOPPING_READY_CALLBACK,
    shopping,
)
from pantrypulse.interface.rendering import render_shopping_list
from pantrypulse.interface.services import household_for_chat
from pantrypulse.persistence.sessions import InteractionSessionRepository
from pantrypulse.schemas import ShoppingList, ShoppingListItem


def _services(context):
    data = getattr(getattr(context, "application", None), "bot_data", {})
    return data.get("services") if isinstance(data, dict) else None


async def shopping_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Approve, edit, or ignore the current household-local list."""
    query = update.callback_query
    chat = update.effective_chat
    if query is None or chat is None or not query.data:
        return
    parts = query.data.split(":", 2)
    action = ":".join(parts[:2])
    token = parts[2] if len(parts) == 3 else None
    if action not in {SHOPPING_APPROVE_CALLBACK, SHOPPING_EDIT_CALLBACK, SHOPPING_IGNORE_CALLBACK, SHOPPING_ADD_CALLBACK, SHOPPING_NEW_CALLBACK, SHOPPING_READY_CALLBACK}:
        return
    await query.answer()
    services = _services(context)
    repository = getattr(services, "interactions", None)
    household_id = household_for_chat(chat.id)
    if action == SHOPPING_READY_CALLBACK:
        await chat.send_message("Your shopping list is ready to add to Amazon Fresh or Whole Foods. Review and place the order in your preferred shopping app.", reply_markup=MAIN_KEYBOARD)
        return
    if action == SHOPPING_NEW_CALLBACK:
        if isinstance(repository, InteractionSessionRepository):
            await asyncio.to_thread(repository.delete, household_id, "approved-shopping")
        await shopping(update, context)
        return
    if action == SHOPPING_ADD_CALLBACK:
        if token != "approved-shopping" or not isinstance(repository, InteractionSessionRepository):
            await chat.send_message("That shopping list has expired. Ask for /shopping again.", reply_markup=MAIN_KEYBOARD)
            return
        await asyncio.to_thread(repository.set_cursor, household_id, "shopping_add", token)
        await chat.send_message("Reply with items to add, separated by commas. For example: onions, bread.", reply_markup=MAIN_KEYBOARD)
        return
    shopping_list = context.user_data.get("shopping_list")
    if shopping_list is None and token and isinstance(repository, InteractionSessionRepository):
        stored = await asyncio.to_thread(repository.load, household_id, token, kind="shopping")
        if stored is None and token == "approved-shopping":
            stored = await asyncio.to_thread(repository.load, household_id, token, kind="approved_shopping")
        shopping_list = ShoppingList.model_validate(stored.payload["shopping"]) if stored else None
    if shopping_list is None:
        await chat.send_message("That shopping list has expired. Ask for /shopping again.", reply_markup=MAIN_KEYBOARD)
        return
    if action == SHOPPING_APPROVE_CALLBACK:
        context.user_data["approved_shopping_list"] = shopping_list
        context.user_data.pop("shopping_list", None)
        if token and isinstance(repository, InteractionSessionRepository):
            await asyncio.to_thread(
                repository.save, household_id, "approved-shopping", "approved_shopping",
                {"shopping": shopping_list.model_dump(mode="json")}, minutes=1440,
            )
            if token != "approved-shopping":
                await asyncio.to_thread(repository.delete, household_id, token)
        await chat.send_message(
            "Shopping list approved for today.\n\n"
            "Your shopping list is ready to add to Amazon Fresh or Whole Foods. "
            "Review and place the order in your preferred shopping app.",
            reply_markup=MAIN_KEYBOARD,
        )
    elif action == SHOPPING_IGNORE_CALLBACK:
        context.user_data.pop("shopping_list", None)
        context.user_data.pop("shopping_edit", None)
        if token and isinstance(repository, InteractionSessionRepository):
            await asyncio.to_thread(repository.delete, household_id, token)
        await chat.send_message("Okay — I left the shopping list unchanged.", reply_markup=MAIN_KEYBOARD)
    else:
        context.user_data["shopping_edit"] = shopping_list
        if token and isinstance(repository, InteractionSessionRepository):
            await asyncio.to_thread(repository.set_cursor, household_id, "shopping_edit", token)
        await chat.send_message(
            "Reply with the items you want instead, separated by commas. For example: milk, onions.",
            reply_markup=MAIN_KEYBOARD,
        )


async def shopping_edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Replace the pending list with a deliberate comma-separated household edit."""
    if update.message is None or not update.message.text or update.effective_chat is None:
        return
    services = _services(context)
    repository = getattr(services, "interactions", None)
    household_id = household_for_chat(update.effective_chat.id)
    token = None
    add_mode = False
    if "shopping_edit" not in context.user_data and isinstance(repository, InteractionSessionRepository):
        token = await asyncio.to_thread(repository.get_cursor, household_id, "shopping_edit")
        stored = await asyncio.to_thread(repository.load, household_id, token, kind="shopping") if token else None
        if stored is None and token == "approved-shopping":
            stored = await asyncio.to_thread(repository.load, household_id, token, kind="approved_shopping")
        if stored:
            context.user_data["shopping_edit"] = ShoppingList.model_validate(stored.payload["shopping"])
    if "shopping_edit" not in context.user_data and isinstance(repository, InteractionSessionRepository):
        token = await asyncio.to_thread(repository.get_cursor, household_id, "shopping_add")
        stored = await asyncio.to_thread(repository.load, household_id, token, kind="approved_shopping") if token else None
        if stored:
            context.user_data["shopping_edit"] = ShoppingList.model_validate(stored.payload["shopping"])
            add_mode = True
    if "shopping_edit" not in context.user_data:
        return
    names = [name.strip() for name in update.message.text.split(",") if name.strip()]
    if not names:
        await update.effective_chat.send_message("Please send one or more item names, separated by commas.")
        return
    if add_mode:
        existing = {item.name.casefold() for item in context.user_data["shopping_edit"].items}
        additions = [ShoppingListItem(name=name, reasons=["added by household"]) for name in names if name.casefold() not in existing]
        shopping_list = ShoppingList(items=[*context.user_data["shopping_edit"].items, *additions])
    else:
        shopping_list = ShoppingList(items=[ShoppingListItem(name=name, reasons=["edited by household"]) for name in names])
    context.user_data["shopping_list"] = shopping_list
    context.user_data.pop("shopping_edit", None)
    if token and isinstance(repository, InteractionSessionRepository):
        kind = "approved_shopping" if add_mode else "shopping"
        await asyncio.to_thread(repository.save, household_id, token, kind, {"shopping": shopping_list.model_dump(mode="json")})
        await asyncio.to_thread(repository.clear_cursor, household_id, "shopping_add" if add_mode else "shopping_edit")
    suffix = f":{token}" if token else ""
    await update.effective_chat.send_message(
        render_shopping_list(shopping_list) + "\n\nReview and approve this edited list.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("Approve", callback_data=f"{SHOPPING_APPROVE_CALLBACK}{suffix}"),
            InlineKeyboardButton("Edit", callback_data=f"{SHOPPING_EDIT_CALLBACK}{suffix}"),
            InlineKeyboardButton("Ignore", callback_data=f"{SHOPPING_IGNORE_CALLBACK}{suffix}"),
        ]]),
    )
