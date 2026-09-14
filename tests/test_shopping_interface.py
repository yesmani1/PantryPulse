"""IF-9 shopping list generation and household controls."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from pantrypulse.interface.handlers.commands import (
    SHOPPING_ADD_CALLBACK,
    SHOPPING_APPROVE_CALLBACK,
    SHOPPING_EDIT_CALLBACK,
    SHOPPING_NEW_CALLBACK,
    SHOPPING_READY_CALLBACK,
    shopping,
)
from pantrypulse.interface.handlers.shopping_actions import shopping_action, shopping_edit_text
from pantrypulse.persistence.sessions import InteractionSessionRepository, StoredInteraction
from pantrypulse.schemas import ShoppingList, ShoppingListItem
from pantrypulse.agents.pantry import SpecialistTask


def _update() -> MagicMock:
    update = MagicMock()
    update.effective_chat.id = 12345
    update.effective_chat.send_message = AsyncMock()
    return update


@pytest.mark.asyncio
async def test_shopping_command_renders_list_and_controls():
    update = _update()
    context = MagicMock()
    context.user_data = {}
    await shopping(update, context)
    assert "Shopping list" in update.effective_chat.send_message.call_args.args[0]
    assert context.user_data["shopping_list"].items
    keyboard = update.effective_chat.send_message.call_args.kwargs["reply_markup"]
    assert [button.text for button in keyboard.inline_keyboard[0]] == ["Approve", "Edit", "Ignore"]


@pytest.mark.asyncio
async def test_shopping_surfaces_bounded_replenishment_agent_copy():
    update = _update()
    services = MagicMock()
    services.inventory.get_inventory.return_value.items = []
    services.optional_specialist_copy.return_value = "Your plan is ready when you are."
    context = MagicMock()
    context.user_data = {}
    context.application.bot_data = {"services": services}

    await shopping(update, context)

    assert "AI assist (Replenishment Agent)" in update.effective_chat.send_message.call_args.args[0]
    assert services.optional_specialist_copy.call_args.args[0] is SpecialistTask.REPLENISHMENT


@pytest.mark.asyncio
async def test_shopping_approve_keeps_selected_list():
    update = _update()
    update.callback_query.data = SHOPPING_APPROVE_CALLBACK
    update.callback_query.answer = AsyncMock()
    context = MagicMock()
    context.user_data = {"shopping_list": MagicMock()}
    await shopping_action(update, context)
    assert "approved_shopping_list" in context.user_data
    assert "shopping_list" not in context.user_data


@pytest.mark.asyncio
async def test_shopping_edit_reply_replaces_pending_list():
    update = _update()
    update.message.text = "milk, onions"
    context = MagicMock()
    context.user_data = {"shopping_edit": MagicMock()}
    await shopping_edit_text(update, context)
    assert [item.name for item in context.user_data["shopping_list"].items] == ["milk", "onions"]
    assert "shopping_edit" not in context.user_data


@pytest.mark.asyncio
async def test_shopping_edit_callback_requests_text_input():
    update = _update()
    update.callback_query.data = SHOPPING_EDIT_CALLBACK
    update.callback_query.answer = AsyncMock()
    context = MagicMock()
    context.user_data = {"shopping_list": MagicMock()}
    await shopping_action(update, context)
    assert "shopping_edit" in context.user_data
    assert "Reply with" in update.effective_chat.send_message.call_args.args[0]


@pytest.mark.asyncio
async def test_tokenized_approval_recovers_shopping_list_after_memory_loss():
    update = _update()
    update.callback_query.data = "shopping:approve:token123"
    update.callback_query.answer = AsyncMock()
    repository = object.__new__(InteractionSessionRepository)
    repository.load = MagicMock(return_value=StoredInteraction("shopping", {"shopping": ShoppingList(items=[ShoppingListItem(name="milk")]).model_dump(mode="json")}))
    repository.save = MagicMock()
    repository.delete = MagicMock()
    services = MagicMock()
    services.interactions = repository
    context = MagicMock()
    context.user_data = {}
    context.application.bot_data = {"services": services}

    await shopping_action(update, context)

    repository.load.assert_called_once_with("telegram:12345", "token123", kind="shopping")
    repository.delete.assert_called_once_with("telegram:12345", "token123")
    assert "approved_shopping_list" in context.user_data


@pytest.mark.asyncio
async def test_ready_to_shop_uses_honest_external_handoff_message():
    update = _update()
    update.callback_query.data = f"{SHOPPING_READY_CALLBACK}:approved-shopping"
    update.callback_query.answer = AsyncMock()
    context = MagicMock()
    context.user_data = {}

    await shopping_action(update, context)

    assert "Amazon Fresh or Whole Foods" in update.effective_chat.send_message.call_args.args[0]


@pytest.mark.asyncio
async def test_approved_shopping_command_has_add_refresh_and_handoff_actions():
    update = _update()
    repository = object.__new__(InteractionSessionRepository)
    repository.load = MagicMock(return_value=StoredInteraction("approved_shopping", {"shopping": ShoppingList(items=[ShoppingListItem(name="milk")]).model_dump(mode="json")}))
    services = MagicMock()
    services.interactions = repository
    context = MagicMock()
    context.user_data = {}
    context.application.bot_data = {"services": services}

    await shopping(update, context)

    keyboard = update.effective_chat.send_message.call_args.kwargs["reply_markup"]
    data = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert data == [f"{SHOPPING_ADD_CALLBACK}:approved-shopping", f"{SHOPPING_NEW_CALLBACK}:approved-shopping", "order:mark:approved-shopping", f"{SHOPPING_READY_CALLBACK}:approved-shopping"]


@pytest.mark.asyncio
async def test_approved_list_can_be_reapproved_after_memory_loss():
    update = _update()
    update.callback_query.data = "shopping:approve:approved-shopping"
    update.callback_query.answer = AsyncMock()
    approved = StoredInteraction("approved_shopping", {"shopping": ShoppingList(items=[ShoppingListItem(name="onions")]).model_dump(mode="json")})
    repository = object.__new__(InteractionSessionRepository)
    repository.load = MagicMock(side_effect=[None, approved])
    repository.save = MagicMock()
    repository.delete = MagicMock()
    services = MagicMock()
    services.interactions = repository
    context = MagicMock()
    context.user_data = {}
    context.application.bot_data = {"services": services}

    await shopping_action(update, context)

    assert "approved for today" in update.effective_chat.send_message.call_args.args[0]
    repository.delete.assert_not_called()
