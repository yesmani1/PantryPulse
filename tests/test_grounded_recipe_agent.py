"""Grounded Recipe Agent output may improve wording, never pantry safety facts."""

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from pantrypulse.agents.pantry import PantryAgents
from pantrypulse.interface.handlers.commands import recipe
from pantrypulse.interface.handlers.recipe_actions import recipe_action
from pantrypulse.interface.services import AppServices
from pantrypulse.interface.config import Settings
from pantrypulse.persistence.sessions import InteractionSessionRepository
from pantrypulse.schemas import (
    Category, DateType, ExpirySource, ItemStatus, PantryItem,
)
from pantrypulse.tools.domain import find_recipe
from pantrypulse.schemas import FindRecipeRequest, ExpiryRisk, RiskLevel


def _item() -> PantryItem:
    now = datetime(2026, 9, 14, tzinfo=timezone.utc)
    return PantryItem(
        household_id="telegram:123", item_id="turkey", name="Turkey", category=Category.DELI,
        quantity=1, unit="pack", purchase_date=date(2026, 9, 12), expiry_date=date(2026, 9, 15),
        date_type=DateType.USE_BY, expiry_source=ExpirySource.OCR, confidence=0.9,
        sealed=True, high_risk=True, status=ItemStatus.ACTIVE, created_at=now, updated_at=now,
    )


def _suggestion():
    item = _item()
    risk = ExpiryRisk(
        item_id=item.item_id, name=item.name, date_type=DateType.USE_BY,
        expiry_date=item.expiry_date, expiry_source=ExpirySource.OCR, confidence=0.9,
        high_risk=True, risk_level=RiskLevel.HIGH, days_from_expiry=1,
        guidance="Use promptly.", explanation="test",
    )
    return find_recipe(FindRecipeRequest(at_risk_items=[risk], pantry=[item])).suggestion


class _RecipeAgent:
    def __init__(self, response: str) -> None:
        self.response, self.prompts = response, []

    def __call__(self, prompt: str):
        self.prompts.append(prompt)
        return SimpleNamespace(text=self.response)


def _services(agent: _RecipeAgent) -> AppServices:
    agents = PantryAgents(
        pantry=Mock(), extraction=Mock(), expiry=Mock(), recipe=agent,
        replenishment=Mock(), donation=Mock(),
    )
    return AppServices(
        inventory=Mock(), feedback=Mock(), sessions=Mock(), photo_receipts=Mock(),
        settings=Settings(telegram_bot_token="test"), agents=agents,
    )


def test_recipe_agent_generates_grounded_title_steps_and_optional_staples():
    agent = _RecipeAgent(
        '{"title":"Turkey skillet bowl","steps":["Warm optional oil in a skillet.","Cook Turkey until ready.","Serve the Turkey bowl."],"preparation_minutes":18,"optional_staples":["oil","pepper"]}'
    )
    suggestion = _suggestion()
    assert suggestion is not None

    generated = _services(agent).generate_grounded_recipe(suggestion)

    assert generated is not None
    assert generated.name == "Turkey skillet bowl"
    assert generated.instructions[1] == "Cook Turkey until ready."
    assert generated.optional_staples == ["oil", "pepper"]
    assert generated.rescued_item_ids == suggestion.rescued_item_ids
    assert generated.ingredients == suggestion.ingredients
    assert "Turkey (1 pack)" in agent.prompts[0]
    assert "only oil, salt, pepper, or water" in agent.prompts[0]


def test_recipe_agent_allows_a_grounded_creative_title():
    suggestion = _suggestion()
    assert suggestion is not None

    generated = _services(_RecipeAgent(
        '{"title":"Weeknight breakfast scramble","steps":["Warm optional oil.","Cook Turkey.","Serve."],"preparation_minutes":20,"optional_staples":["oil"]}'
    )).generate_grounded_recipe(suggestion)

    assert generated is not None
    assert generated.name == "Weeknight breakfast scramble"


@pytest.mark.parametrize("response", [
    "not json",
    '{"title":"Turkey bowl","steps":["One","Two","Three"],"preparation_minutes":20,"optional_staples":["butter"]}',
])
def test_invalid_agent_response_uses_deterministic_fallback(response):
    suggestion = _suggestion()
    assert suggestion is not None
    assert _services(_RecipeAgent(response)).generate_grounded_recipe(suggestion) is None


@pytest.mark.asyncio
async def test_recipe_command_renders_generated_recipe_and_persists_it():
    suggestion = _suggestion()
    generated = suggestion.model_copy(update={
        "name": "Turkey skillet bowl", "instructions": ["Cook Turkey.", "Season with optional pepper.", "Serve."],
        "preparation_minutes": 18, "optional_staples": ["pepper"],
    })
    repository = object.__new__(InteractionSessionRepository)
    repository.save = Mock()
    services = SimpleNamespace(
        inventory=Mock(), interactions=repository,
        generate_grounded_recipe=Mock(return_value=generated),
    )
    services.inventory.get_inventory.return_value.items = [_item()]
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=123, send_message=AsyncMock()))
    context = SimpleNamespace(user_data={}, application=SimpleNamespace(bot_data={"services": services}))

    await recipe(update, context)

    rendered = update.effective_chat.send_message.call_args.args[0]
    assert "Turkey skillet bowl" in rendered
    assert "AI assist (Recipe Agent)" in rendered
    assert "[optional staple] pepper" in rendered
    assert repository.save.call_count == 2
    assert repository.save.call_args.args[3]["suggestion"]["name"] == "Turkey skillet bowl"


@pytest.mark.asyncio
async def test_another_recipe_uses_agent_when_available():
    suggestion = _suggestion()
    generated = suggestion.model_copy(update={
        "name": "Turkey tray bake", "instructions": ["Arrange Turkey.", "Bake Turkey.", "Serve Turkey."],
        "preparation_minutes": 24,
    })
    services = SimpleNamespace(generate_grounded_recipe=Mock(return_value=generated), interactions=None)
    update = SimpleNamespace(
        callback_query=SimpleNamespace(data="recipe:another", answer=AsyncMock()),
        effective_chat=SimpleNamespace(id=123, send_message=AsyncMock()),
    )
    context = SimpleNamespace(user_data={"recipe_suggestion": suggestion}, application=SimpleNamespace(bot_data={"services": services}))

    await recipe_action(update, context)

    services.generate_grounded_recipe.assert_called_once_with(suggestion, alternative=True)
    assert "Turkey tray bake" in update.effective_chat.send_message.call_args.args[0]
    assert "AI assist (Recipe Agent)" in update.effective_chat.send_message.call_args.args[0]
