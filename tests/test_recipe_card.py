"""IF-8 -- recipe card rendering and the two button callbacks."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from pantrypulse.fixtures import load_recipe_suggestion
from pantrypulse.interface.handlers.commands import (
    RECIPE_ANOTHER_CALLBACK,
    RECIPE_COOK_CALLBACK,
)
from pantrypulse.interface.handlers.recipe_actions import recipe_action
from pantrypulse.interface.rendering import render_recipe


@pytest.fixture
def recipe():
    return load_recipe_suggestion()


def test_card_leads_with_the_rescue_count(recipe):
    """CLAUDE.md convention, verbatim: "Shakshuka — rescues 3 expiring items,
    missing 1" must be the first line, not buried in the card."""
    card = render_recipe(recipe)
    first_line = card.splitlines()[0]
    assert first_line == "Shakshuka — rescues 3 expiring items, missing 1"


def test_every_ingredient_appears_and_missing_ones_are_marked(recipe):
    card = render_recipe(recipe)
    assert "[missing] Feta Cheese" in card
    assert "[have] Canned Tomatoes" in card
    assert "[have] Free Range Eggs" in card


def test_instructions_are_numbered_in_order(recipe):
    card = render_recipe(recipe)
    assert "1. Saute diced onion and garlic until soft." in card
    last_step_index = len(recipe.instructions)
    assert f"{last_step_index}. " in card


def _make_callback_update(data: str):
    update = MagicMock()
    update.callback_query.data = data
    update.callback_query.answer = AsyncMock()
    update.effective_chat.send_message = AsyncMock()
    return update


@pytest.mark.asyncio
async def test_cook_this_selects_the_current_recipe():
    update = _make_callback_update(RECIPE_COOK_CALLBACK)
    context = MagicMock()
    context.user_data = {"recipe_suggestion": load_recipe_suggestion()}
    await recipe_action(update, context=context)

    update.callback_query.answer.assert_awaited_once()
    sent = update.effective_chat.send_message.call_args[0][0]
    assert "is selected" in sent
    assert "selected_recipe" in context.user_data


@pytest.mark.asyncio
async def test_another_recipe_renders_a_real_variation():
    update = _make_callback_update(RECIPE_ANOTHER_CALLBACK)
    context = MagicMock()
    context.user_data = {"recipe_suggestion": load_recipe_suggestion()}
    await recipe_action(update, context=context)

    update.callback_query.answer.assert_awaited_once()
    sent = update.effective_chat.send_message.call_args[0][0]
    assert "quick variation" in sent
    assert "recipe_suggestion" in context.user_data


@pytest.mark.asyncio
async def test_unknown_callback_data_is_ignored():
    update = _make_callback_update("something:else")
    await recipe_action(update, context=MagicMock())
    update.callback_query.answer.assert_not_awaited()
    update.effective_chat.send_message.assert_not_awaited()
