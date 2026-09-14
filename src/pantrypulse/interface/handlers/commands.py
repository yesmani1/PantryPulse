"""Command handlers."""

import asyncio
import logging
from uuid import uuid4
from datetime import date, timedelta

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import ContextTypes

from pantrypulse.fixtures import load_expiry_risks, load_pantry_items, load_recipe_suggestion, load_rescue_stats
from pantrypulse.agents.pantry import SpecialistTask
from pantrypulse.interface import messages
from pantrypulse.persistence.sessions import InteractionSessionRepository
from pantrypulse.interface.rendering import (
    is_actionable,
    render_daily_expiry_check,
    render_expiry_risk,
    render_pantry,
    render_ordered_items,
    render_recipe,
    render_shopping_list,
    render_combined_decision,
    render_rescue_stats,
    render_rescue_stats_if_measured,
)
from pantrypulse.schemas import (
    CheckDonationEligibilityRequest,
    CheckExpiringItemsRequest,
    CreateShoppingListRequest,
    FeedbackResponse,
    FindRecipeRequest,
    GetInventoryRequest,
    GetRescueStatsRequest,
    ItemStatus,
    PredictConsumptionRequest,
    ShoppingList,
)
from pantrypulse.tools.decisions import build_combined_decision, combine_expiry_issues
from pantrypulse.tools.domain import (
    check_donation_eligibility,
    check_expiring_items,
    create_shopping_list,
    find_recipe,
    predict_consumption,
)

logger = logging.getLogger(__name__)

# Callback data namespace for the two recipe-card buttons (handlers/recipe_actions.py).
RECIPE_COOK_CALLBACK = "recipe:cook"
RECIPE_ANOTHER_CALLBACK = "recipe:another"
SHOPPING_APPROVE_CALLBACK = "shopping:approve"
SHOPPING_EDIT_CALLBACK = "shopping:edit"
SHOPPING_IGNORE_CALLBACK = "shopping:ignore"
SHOPPING_ADD_CALLBACK = "shopping:add"
SHOPPING_NEW_CALLBACK = "shopping:new"
SHOPPING_READY_CALLBACK = "shopping:ready"
SHOPPING_MARK_ORDERED_CALLBACK = "order:mark"
DECISION_COOK_CALLBACK = "decision:cook"
DECISION_SHOP_CALLBACK = "decision:shop"
DECISION_DONATE_CALLBACK = "decision:donate"
DECISION_IGNORE_CALLBACK = "decision:ignore"

# Callback data prefix for feedback buttons (handlers/feedback_actions.py). Suffix
# is "{FeedbackResponse.value}:{item_id}" -- reuses the real enum values so BE-22
# can parse callback_data straight into FeedbackResponse with no translation.
FEEDBACK_CALLBACK_PREFIX = "feedback:"

# Persistent reply keyboard, replacing the phone's normal keyboard with a
# fixed button row. The label strings double as routing keys: handlers/
# __init__.register_handlers matches a tap's text against these exact
# strings and dispatches to the same function the equivalent /command uses.
# Plain text, no emoji -- matches every other message in this bot.
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [["Today", "Expiring"], ["Pantry", "Recipe"], ["Remove", "Decision"], ["Shopping"]],
    resize_keyboard=True,
)


# Set per chat by /demo. Every read command already knows how to fall back to
# fixtures when no services are wired, so demo mode reuses that path rather
# than adding a second one.
DEMO_MODE = "demo_mode"


def _services(context: ContextTypes.DEFAULT_TYPE):
    """Return injected runtime services, or None to read the demo fixtures.

    A household in demo mode is deliberately routed down the fixture path: the
    fixtures re-anchor their dates to today on every load, so the Best Before /
    Use By contrast reads correctly on any day of a judging window that runs
    for three weeks. Seeded database rows would decay into "everything expired"
    within days of being written.
    """
    if getattr(context, "user_data", None) and context.user_data.get(DEMO_MODE):
        return None
    app = getattr(context, "application", None)
    data = getattr(app, "bot_data", None)
    return data.get("services") if isinstance(data, dict) else None


# How far ahead "likely to run out soon" reaches. A shopping list is only
# useful if it is about this week's shop.
REPLENISH_HORIZON_DAYS = 7
MAX_SHOPPING_SUGGESTIONS = 7


def _running_out_soon(forecasts):
    """Only the forecasts worth putting on a shopping list.

    create_shopping_list adds every forecast it is handed, so passing all of
    them listed the entire perishable pantry -- seventeen rows, each saying
    "likely to run out soon", including items whose forecast depletion date was
    years away. Choosing which forecasts count belongs to the caller.
    """
    cutoff = date.today() + timedelta(days=REPLENISH_HORIZON_DAYS)
    eligible = [f for f in forecasts if f.estimated_depletion_date <= cutoff]
    return sorted(eligible, key=lambda forecast: (forecast.estimated_depletion_date, forecast.name.lower()))[
        :MAX_SHOPPING_SUGGESTIONS
    ]


def _active_inventory(services, household_id: str):
    """Everything still actually in the pantry.

    Without the status filter a household keeps seeing items it has used,
    binned, donated or struck out as misread: the row is still stored, and
    storage is the record, not the pantry.
    """
    return services.inventory.get_inventory(
        GetInventoryRequest(household_id=household_id, statuses=[ItemStatus.ACTIVE])
    ).items


def _ordered_inventory(services, household_id: str):
    """Orders the household has placed but has not received yet."""
    return services.inventory.get_inventory(
        GetInventoryRequest(household_id=household_id, statuses=[ItemStatus.ORDERED])
    ).items


async def _specialist_note(services, task: SpecialistTask, prompt: str, label: str) -> str:
    """Request optional agent wording without letting it change a decision."""
    if services is None or not callable(getattr(services, "optional_specialist_copy", None)):
        return ""
    note = await asyncio.to_thread(services.optional_specialist_copy, task, prompt)
    if not isinstance(note, str) or not note.strip():
        return ""
    return f"\n\nAI assist ({label}): {note.strip()}"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Greet the user and explain what the bot does. Entry point for /start."""
    chat = update.effective_chat
    if chat is None:  # channel posts and edits can arrive without a chat
        return

    logger.info("/start from chat_id=%s", chat.id)
    await chat.send_message(messages.START, reply_markup=MAIN_KEYBOARD)


async def pantry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List everything in the pantry. Entry point for /pantry.

    Shows active food separately from external orders awaiting receipt. Fixtures
    remain the intentional isolated-handler fallback.
    """
    chat = update.effective_chat
    if chat is None:
        return

    logger.info("/pantry from chat_id=%s", chat.id)
    services = _services(context)
    items = (
        _active_inventory(services, f"telegram:{chat.id}")
        if services is not None
        else load_pantry_items()
    )
    ordered = _ordered_inventory(services, f"telegram:{chat.id}") if services is not None else []
    markup = MAIN_KEYBOARD
    if ordered:
        from pantrypulse.interface.handlers.order_actions import ORDER_BULK_RECEIVE_CALLBACK, ORDER_RECEIVE_CALLBACK
        rows = [[InlineKeyboardButton(f"Confirm received: {item.name[:28]}", callback_data=f"{ORDER_RECEIVE_CALLBACK}:{item.item_id}")] for item in ordered[:6]]
        rows.append([InlineKeyboardButton("Bulk order received", callback_data=ORDER_BULK_RECEIVE_CALLBACK)])
        markup = InlineKeyboardMarkup(rows)
    await chat.send_message(render_pantry(items, ordered), reply_markup=markup)


async def recipe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the rescue recipe. Entry point for /recipe.

    Uses the household's live inventory when services are configured; fixtures
    remain the deliberate fallback for isolated local interface runs.
    """
    chat = update.effective_chat
    if chat is None:
        return

    logger.info("/recipe from chat_id=%s", chat.id)
    services = _services(context)
    if services is None:
        suggestion = load_recipe_suggestion()
    else:
        household_id = f"telegram:{chat.id}"
        items = _active_inventory(services, household_id)
        risks = check_expiring_items(items, CheckExpiringItemsRequest(household_id=household_id)).risks
        suggestion = find_recipe(FindRecipeRequest(at_risk_items=risks, pantry=items)).suggestion
        if suggestion is None:
            await chat.send_message("No pantry items need rescuing right now.", reply_markup=MAIN_KEYBOARD)
            return
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Cook This", callback_data=RECIPE_COOK_CALLBACK),
        InlineKeyboardButton("Another Recipe", callback_data=RECIPE_ANOTHER_CALLBACK),
    ]])
    context.user_data["recipe_suggestion"] = suggestion
    if services is not None and isinstance(getattr(services, "interactions", None), InteractionSessionRepository):
        token = uuid4().hex[:16]
        await asyncio.to_thread(
            services.interactions.save, household_id, token, "recipe",
            {"suggestion": suggestion.model_dump(mode="json")},
        )
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Cook This", callback_data=f"{RECIPE_COOK_CALLBACK}:{token}"),
            InlineKeyboardButton("Another Recipe", callback_data=f"{RECIPE_ANOTHER_CALLBACK}:{token}"),
        ]])
    generated = None
    if services is not None and callable(getattr(services, "generate_grounded_recipe", None)):
        generated = await asyncio.to_thread(services.generate_grounded_recipe, suggestion)
        if generated is not None:
            suggestion = generated
            context.user_data["recipe_suggestion"] = suggestion
            if services is not None and isinstance(getattr(services, "interactions", None), InteractionSessionRepository):
                await asyncio.to_thread(
                    services.interactions.save, household_id, token, "recipe",
                    {"suggestion": suggestion.model_dump(mode="json")},
                )
    rendered = render_recipe(suggestion)
    if generated is not None:
        rendered += "\n\nAI assist (Recipe Agent): Grounded recipe generated from your confirmed rescue items."
    await chat.send_message(rendered, reply_markup=keyboard)


async def expiring(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show every at-risk item with feedback buttons. Entry point for /expiring.

    Uses live inventory and deterministic date rules when services are
    configured; fixtures remain the deliberate fallback for isolated local
    interface runs. A sell_by (risk_level=none) item is never shown at all --
    it is not a consumer deadline.
    """
    chat = update.effective_chat
    if chat is None:
        return

    logger.info("/expiring from chat_id=%s", chat.id)
    services = _services(context)
    if services is None:
        risks = load_expiry_risks()
    else:
        household_id = f"telegram:{chat.id}"
        items = _active_inventory(services, household_id)
        risks = check_expiring_items(items, CheckExpiringItemsRequest(household_id=household_id)).risks
    risks = [risk for risk in risks if is_actionable(risk)]
    if not risks:
        await chat.send_message("Nothing needs your attention right now.")
        return

    for risk in risks:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "Used it",
                callback_data=f"{FEEDBACK_CALLBACK_PREFIX}{FeedbackResponse.USED.value}:{risk.item_id}",
            ),
            InlineKeyboardButton(
                "Still good",
                callback_data=f"{FEEDBACK_CALLBACK_PREFIX}{FeedbackResponse.STILL_GOOD.value}:{risk.item_id}",
            ),
            InlineKeyboardButton(
                "Tossed it",
                callback_data=f"{FEEDBACK_CALLBACK_PREFIX}{FeedbackResponse.TOSSED.value}:{risk.item_id}",
            ),
        ]])
        await chat.send_message(render_expiry_risk(risk), reply_markup=keyboard)


async def shopping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Build a transparent household shopping list from consumption forecasts."""
    chat = update.effective_chat
    if chat is None:
        return
    services = _services(context)
    household_id = f"telegram:{chat.id}"
    repository = getattr(services, "interactions", None)
    if isinstance(repository, InteractionSessionRepository):
        approved = await asyncio.to_thread(repository.load, household_id, "approved-shopping", kind="approved_shopping")
        if approved:
            current = ShoppingList.model_validate(approved.payload["shopping"])
            waiting = render_ordered_items(_ordered_inventory(services, household_id))
            assist = await _specialist_note(
                services, SpecialistTask.REPLENISHMENT,
                "Write one friendly sentence about following this already-approved shopping list. "
                "Do not add items, dates, prices, forecasts, or safety advice. Items: "
                + ", ".join(item.name for item in current.items),
                "Replenishment Agent",
            )
            await chat.send_message(
                "Approved shopping list for today:\n\n" + render_shopping_list(current) + (f"\n\n{waiting}" if waiting else "") + assist,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Add items", callback_data=f"{SHOPPING_ADD_CALLBACK}:approved-shopping"),
                    InlineKeyboardButton("Create new list", callback_data=f"{SHOPPING_NEW_CALLBACK}:approved-shopping"),
                ], [
                    InlineKeyboardButton("Mark ordered", callback_data=f"{SHOPPING_MARK_ORDERED_CALLBACK}:approved-shopping"),
                    InlineKeyboardButton("Ready to shop", callback_data=f"{SHOPPING_READY_CALLBACK}:approved-shopping"),
                ]]),
            )
            return
    items = (
        _active_inventory(services, household_id)
        if services is not None
        else load_pantry_items()
    )
    forecasts = predict_consumption(
        items, PredictConsumptionRequest(household_id=household_id)
    ).forecasts
    shopping_list = create_shopping_list(
        CreateShoppingListRequest(depleted_items=_running_out_soon(forecasts))
    ).shopping_list
    context.user_data["shopping_list"] = shopping_list
    token = None
    if services is not None and isinstance(getattr(services, "interactions", None), InteractionSessionRepository):
        token = uuid4().hex[:16]
        await asyncio.to_thread(
            services.interactions.save, household_id, token, "shopping",
            {"shopping": shopping_list.model_dump(mode="json")},
        )
    suffix = f":{token}" if token else ""
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Approve", callback_data=f"{SHOPPING_APPROVE_CALLBACK}{suffix}"),
        InlineKeyboardButton("Edit", callback_data=f"{SHOPPING_EDIT_CALLBACK}{suffix}"),
        InlineKeyboardButton("Ignore", callback_data=f"{SHOPPING_IGNORE_CALLBACK}{suffix}"),
    ]])
    waiting = render_ordered_items(_ordered_inventory(services, household_id)) if services is not None else ""
    assist = await _specialist_note(
        services, SpecialistTask.REPLENISHMENT,
        "Write one friendly sentence about this already-calculated shopping plan. "
        "Do not add items, dates, prices, forecasts, or safety advice. Items: "
        + ", ".join(item.name for item in shopping_list.items),
        "Replenishment Agent",
    )
    await chat.send_message(render_shopping_list(shopping_list) + (f"\n\n{waiting}" if waiting else "") + assist, reply_markup=keyboard)


async def decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Present one combined household plan with only applicable actions."""
    chat = update.effective_chat
    if chat is None:
        return
    services = _services(context)
    household_id = f"telegram:{chat.id}"
    items = (
        _active_inventory(services, household_id)
        if services is not None
        else load_pantry_items()
    )
    risks = (
        check_expiring_items(items, CheckExpiringItemsRequest(household_id=household_id)).risks
        if services is not None
        else load_expiry_risks()
    )
    suggestion = find_recipe(FindRecipeRequest(at_risk_items=risks, pantry=items)).suggestion
    shopping_list = create_shopping_list(CreateShoppingListRequest(
        depleted_items=_running_out_soon(
            predict_consumption(items, PredictConsumptionRequest(household_id=household_id)).forecasts
        )
    )).shopping_list
    # An approved household edit is the current list for the day.  Replacing it
    # with a fresh forecast here made Decision -> Shop appear to discard a
    # deliberate edit made moments earlier.
    repository = getattr(services, "interactions", None)
    if isinstance(repository, InteractionSessionRepository):
        approved = await asyncio.to_thread(repository.load, household_id, "approved-shopping", kind="approved_shopping")
        if approved:
            shopping_list = ShoppingList.model_validate(approved.payload["shopping"])
    ordered = _ordered_inventory(services, household_id) if services is not None else []
    candidates = check_donation_eligibility(CheckDonationEligibilityRequest(items=items)).candidates
    combined = build_combined_decision(
        risks, recipe=suggestion, shopping_list=shopping_list, donation_candidates=candidates
    )
    rendered = render_combined_decision(combined)
    if rendered is None:
        return
    if ordered:
        rendered += "\n\n" + render_ordered_items(ordered)
    stats = (
        services.feedback.get_rescue_stats(GetRescueStatsRequest(
            household_id=household_id, period=date.today().strftime("%Y-%m")
        )).stats
        if services is not None
        else load_rescue_stats()[-1]
    )
    rendered += "\n\n" + render_rescue_stats(
        stats.rescued_count, stats.tossed_count, stats.estimated_value_saved
    )
    context.user_data["combined_decision"] = combined
    session_id = None
    if services is not None:
        session_id = uuid4().hex[:16]
        services.sessions.save(household_id, session_id, combined)
    callback_by_action = {
        "cook": ("Cook", DECISION_COOK_CALLBACK),
        "shop": ("Shop", DECISION_SHOP_CALLBACK),
        "donate": ("Donate Eligible Food", DECISION_DONATE_CALLBACK),
        "ignore": ("Ignore", DECISION_IGNORE_CALLBACK),
    }
    # callback_data by keyword, never positionally: InlineKeyboardButton's
    # second positional parameter is url, so InlineKeyboardButton(text, data)
    # silently builds a link button and Telegram rejects the whole message.
    buttons = [
        InlineKeyboardButton(label, callback_data=f"{data}:{session_id}" if session_id else data)
        for label, data in (callback_by_action[action] for action in combined.actions)
    ]
    await chat.send_message(rendered, reply_markup=InlineKeyboardMarkup([buttons]))


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """The daily check for this household (IF-7).

    One message, never one per item, and nothing at all when nothing needs
    attention -- silence on a quiet day is a correct outcome, not a failure.
    BE-13's scheduler will call this same renderer; the command exists so the
    message is demonstrable, and reviewable, before the schedule is wired.
    """
    chat = update.effective_chat
    if chat is None:
        return

    logger.info("/today from chat_id=%s", chat.id)
    services = _services(context)
    household_id = f"telegram:{chat.id}"
    if services is None:
        risks = load_expiry_risks()
        stats = load_rescue_stats()[-1]
    else:
        items = _active_inventory(services, household_id)
        risks = check_expiring_items(
            items, CheckExpiringItemsRequest(household_id=household_id)
        ).risks
        stats = services.feedback.get_rescue_stats(
            GetRescueStatsRequest(
                household_id=household_id, period=date.today().strftime("%Y-%m")
            )
        ).stats

    rendered = render_daily_expiry_check(combine_expiry_issues(risks), stats)
    if rendered is None:
        # Even on a quiet day the month's impact is worth having, for someone
        # who asked. The scheduled run still sends nothing at all.
        impact = render_rescue_stats_if_measured(stats)
        quiet = messages.NOTHING_TODAY + (f"\n\n{impact}" if impact else "")
        await chat.send_message(quiet, reply_markup=MAIN_KEYBOARD)
        return
    await chat.send_message(rendered, reply_markup=MAIN_KEYBOARD)


async def demo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fill this chat with the sample household, so the product can be seen.

    A new chat starts genuinely empty -- households are keyed by Telegram chat
    ID -- so anyone opening the bot for the first time, a judge included, sees
    "your pantry is empty" and none of the behaviour worth looking at. This
    switches the chat to the demo pantry from build-spec 7.3, whose dates
    re-anchor to today, so the Best Before / Use By contrast is visible
    immediately rather than only after someone photographs a receipt.

    Sending a photo leaves demo mode: at that point there is real inventory to
    talk about, and mixing the two would be dishonest about which is which.
    """
    chat = update.effective_chat
    if chat is None:
        return

    already_on = bool(context.user_data.get(DEMO_MODE))
    if already_on:
        context.user_data.pop(DEMO_MODE, None)
        logger.info("/demo off for chat_id=%s", chat.id)
        await chat.send_message(messages.DEMO_OFF, reply_markup=MAIN_KEYBOARD)
        return

    context.user_data[DEMO_MODE] = True
    logger.info("/demo on for chat_id=%s", chat.id)
    await chat.send_message(messages.DEMO_ON, reply_markup=MAIN_KEYBOARD)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List available commands. Entry point for /help. Named help_command,
    not help, to avoid shadowing the Python builtin."""
    chat = update.effective_chat
    if chat is None:
        return

    logger.info("/help from chat_id=%s", chat.id)
    await chat.send_message(messages.HELP, reply_markup=MAIN_KEYBOARD)
