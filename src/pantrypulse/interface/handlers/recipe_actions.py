"""Callback handling for the recipe card's useful local actions (IF-8)."""

import logging
import asyncio

from telegram import Update
from telegram.ext import ContextTypes

from pantrypulse.interface.handlers.commands import (
    MAIN_KEYBOARD,
    RECIPE_ANOTHER_CALLBACK,
    RECIPE_COOK_CALLBACK,
)
from pantrypulse.interface.rendering import render_recipe
from pantrypulse.interface.services import household_for_chat
from pantrypulse.persistence.sessions import InteractionSessionRepository
from pantrypulse.schemas import RecipeSuggestion

logger = logging.getLogger(__name__)


async def recipe_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Select the current recipe or render a distinct, safe variation."""
    query = update.callback_query
    if query is None or not query.data:
        return
    parts = query.data.split(":", 2)
    action = ":".join(parts[:2])
    token = parts[2] if len(parts) == 3 else None
    if action not in {RECIPE_COOK_CALLBACK, RECIPE_ANOTHER_CALLBACK}:
        return
    await query.answer()
    chat = update.effective_chat
    if chat is None:
        return
    suggestion = context.user_data.get("recipe_suggestion")
    data = getattr(getattr(context, "application", None), "bot_data", {})
    services = data.get("services") if isinstance(data, dict) else None
    repository = getattr(services, "interactions", None)
    if suggestion is None and token and isinstance(repository, InteractionSessionRepository):
        stored = await asyncio.to_thread(repository.load, household_for_chat(chat.id), token, kind="recipe")
        suggestion = RecipeSuggestion.model_validate(stored.payload["suggestion"]) if stored else None
    if suggestion is None:
        await chat.send_message("That recipe card has expired. Ask for /recipe again.", reply_markup=MAIN_KEYBOARD)
        return
    logger.info("recipe callback=%s from chat_id=%s", query.data, chat.id)
    if action == RECIPE_COOK_CALLBACK:
        context.user_data["selected_recipe"] = suggestion
        await chat.send_message(
            f"Great choice — {suggestion.name} is selected. When you're done, use the expiry feedback buttons to record what you used.",
            reply_markup=MAIN_KEYBOARD,
        )
        return
    generated = None
    if services is not None and callable(getattr(services, "generate_grounded_recipe", None)):
        generated = await asyncio.to_thread(services.generate_grounded_recipe, suggestion, alternative=True)
    if generated is not None:
        suggestion = generated
        rendered = render_recipe(suggestion) + "\n\nAI assist (Recipe Agent): Grounded recipe generated from your confirmed rescue items."
    else:
        suggestion = suggestion.model_copy(update={
            "name": f"{suggestion.name} — quick variation",
            "instructions": [*suggestion.instructions, "Use the same rescued ingredients in a different seasoning style."],
            "ranking_rationale": suggestion.ranking_rationale + " This is a simple alternate preparation.",
        })
        rendered = render_recipe(suggestion)
    context.user_data["recipe_suggestion"] = suggestion
    if token and isinstance(repository, InteractionSessionRepository):
        await asyncio.to_thread(repository.save, household_for_chat(chat.id), token, "recipe", {"suggestion": suggestion.model_dump(mode="json")})
    await chat.send_message(rendered, reply_markup=MAIN_KEYBOARD)
