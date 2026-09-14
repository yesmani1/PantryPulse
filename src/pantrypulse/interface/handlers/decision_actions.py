"""Actions from the single combined household decision (IF-12)."""

from datetime import datetime, timedelta, timezone
import asyncio
from uuid import uuid4

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from pantrypulse.agents.pantry import SpecialistTask
from pantrypulse.interface.handlers.commands import (
    DECISION_COOK_CALLBACK,
    DECISION_DONATE_CALLBACK,
    DECISION_IGNORE_CALLBACK,
    DECISION_SHOP_CALLBACK,
    MAIN_KEYBOARD,
    _ordered_inventory,
)
from pantrypulse.interface.rendering import render_ordered_items, render_recipe, render_shopping_list
from pantrypulse.persistence.sessions import InteractionSessionRepository
from pantrypulse.schemas import DonationRequest, DonationStatus, RequestDonationRequest
from pantrypulse.tools.domain import request_donation

DONATION_ACCEPT_CALLBACK = "donation:accept"
DONATION_REJECT_CALLBACK = "donation:reject"


async def decision_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Resolve one action from the current, short-lived combined decision."""
    query = update.callback_query
    chat = update.effective_chat
    if query is None or chat is None or not query.data:
        return
    parts = query.data.split(":", 2)
    action = ":".join(parts[:2])
    session_id = parts[2] if len(parts) == 3 else None
    if action not in {DECISION_COOK_CALLBACK, DECISION_SHOP_CALLBACK, DECISION_DONATE_CALLBACK, DECISION_IGNORE_CALLBACK}:
        return
    await query.answer()
    decision = context.user_data.get("combined_decision")
    bot_data = getattr(getattr(context, "application", None), "bot_data", {})
    services = bot_data.get("services") if isinstance(bot_data, dict) else None
    if decision is None and session_id and services is not None:
        decision = services.sessions.load(f"telegram:{chat.id}", session_id)
    if decision is None:
        await chat.send_message("That decision has expired. Ask for /decision again.", reply_markup=MAIN_KEYBOARD)
        return
    if action == DECISION_COOK_CALLBACK and decision.recipe is not None:
        await chat.send_message(render_recipe(decision.recipe), reply_markup=MAIN_KEYBOARD)
    elif action == DECISION_SHOP_CALLBACK:
        context.user_data["shopping_list"] = decision.shopping_list
        token = None
        repository = getattr(services, "interactions", None)
        if isinstance(repository, InteractionSessionRepository):
            token = uuid4().hex[:16]
            await asyncio.to_thread(repository.save, f"telegram:{chat.id}", token, "shopping", {"shopping": decision.shopping_list.model_dump(mode="json")})
        suffix = f":{token}" if token else ""
        waiting = render_ordered_items(_ordered_inventory(services, f"telegram:{chat.id}")) if services is not None else ""
        await chat.send_message(
            render_shopping_list(decision.shopping_list) + (f"\n\n{waiting}" if waiting else ""),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Approve", callback_data=f"shopping:approve{suffix}"),
                InlineKeyboardButton("Edit", callback_data=f"shopping:edit{suffix}"),
                InlineKeyboardButton("Ignore", callback_data=f"shopping:ignore{suffix}"),
            ]]),
        )
    elif action == DECISION_DONATE_CALLBACK:
        now = datetime.now(timezone.utc)
        request = request_donation(RequestDonationRequest(
            household_id=f"telegram:{chat.id}", candidates=list(decision.donation_candidates),
            pickup_window_start=now + timedelta(hours=1), pickup_window_end=now + timedelta(hours=3),
        )).donation_request
        context.user_data["mock_donation_request"] = request
        token = None
        repository = getattr(services, "interactions", None)
        if isinstance(repository, InteractionSessionRepository):
            token = uuid4().hex[:16]
            await asyncio.to_thread(repository.save, f"telegram:{chat.id}", token, "donation", {"request": request.model_dump(mode="json")})
        suffix = f":{token}" if token else ""
        assist = ""
        if services is not None and callable(getattr(services, "optional_specialist_copy", None)):
            note = await asyncio.to_thread(
                services.optional_specialist_copy, SpecialistTask.DONATION_COMMUNICATION,
                "Write one friendly sentence about this already-approved mock donation handoff. "
                "Do not claim a recipient accepted it, change eligibility, or add safety advice.",
            )
            if isinstance(note, str) and note.strip():
                assist = f"AI assist (Donation Agent): {note.strip()}"
        if assist:
            await chat.send_message(assist)
        await chat.send_message(
            f"Mock recipient view: {len(request.candidate_item_ids)} item(s) available for pickup from {request.pickup_window_start:%H:%M}–{request.pickup_window_end:%H:%M}.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("Accept Pickup", callback_data=f"{DONATION_ACCEPT_CALLBACK}{suffix}"),
                InlineKeyboardButton("Reject", callback_data=f"{DONATION_REJECT_CALLBACK}{suffix}"),
            ]]),
        )
    else:
        await chat.send_message("Okay — no action was taken.", reply_markup=MAIN_KEYBOARD)
    context.user_data.pop("combined_decision", None)
    if action == DECISION_IGNORE_CALLBACK and session_id and services is not None:
        services.sessions.delete(f"telegram:{chat.id}", session_id)


async def donation_recipient_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Simulate an authorized local recipient accepting or rejecting pickup."""
    query = update.callback_query
    chat = update.effective_chat
    if query is None or chat is None or not query.data:
        return
    parts = query.data.split(":", 2)
    action = ":".join(parts[:2])
    token = parts[2] if len(parts) == 3 else None
    if action not in {DONATION_ACCEPT_CALLBACK, DONATION_REJECT_CALLBACK}:
        return
    await query.answer()
    request = context.user_data.get("mock_donation_request")
    bot_data = getattr(getattr(context, "application", None), "bot_data", {})
    services = bot_data.get("services") if isinstance(bot_data, dict) else None
    repository = getattr(services, "interactions", None)
    if request is None and token and isinstance(repository, InteractionSessionRepository):
        stored = await asyncio.to_thread(repository.load, f"telegram:{chat.id}", token, kind="donation")
        request = DonationRequest.model_validate(stored.payload["request"]) if stored else None
    if request is None:
        await chat.send_message("That mock donation request has expired.", reply_markup=MAIN_KEYBOARD)
        return
    status = DonationStatus.ACCEPTED if action == DONATION_ACCEPT_CALLBACK else DonationStatus.REJECTED
    request = request.model_copy(update={"status": status})
    context.user_data["mock_donation_request"] = request
    if token and isinstance(repository, InteractionSessionRepository):
        await asyncio.to_thread(repository.delete, f"telegram:{chat.id}", token)
    result = "accepted" if status is DonationStatus.ACCEPTED else "rejected"
    await chat.send_message(
        f"Mock recipient {result} pickup. Household notification: donation request is {result}.",
        reply_markup=MAIN_KEYBOARD,
    )
