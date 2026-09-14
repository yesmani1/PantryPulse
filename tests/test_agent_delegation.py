"""Offline integration proof for explicit PantryAgent specialist delegation."""

from types import SimpleNamespace
from unittest.mock import Mock

from pantrypulse.agents.pantry import PantryAgents, SpecialistTask
from pantrypulse.interface.config import Settings
from pantrypulse.interface.services import AppServices


class FakeSpecialist:
    def __init__(self, name: str) -> None:
        self.name, self.prompts = name, []

    def __call__(self, prompt: str) -> dict[str, str]:
        self.prompts.append(prompt)
        return {"specialist": self.name, "prompt": prompt}


def test_orchestrator_routes_each_eligible_task_to_its_named_specialist():
    specialists = {name: FakeSpecialist(name) for name in ("extraction", "expiry", "recipe", "replenishment", "donation")}
    agents = PantryAgents(pantry=SimpleNamespace(), extraction=specialists["extraction"], expiry=specialists["expiry"], recipe=specialists["recipe"], replenishment=specialists["replenishment"], donation=specialists["donation"])
    expected = {
        SpecialistTask.EXTRACTION: "extraction", SpecialistTask.EXPIRY_EXPLANATION: "expiry",
        SpecialistTask.RECIPE: "recipe", SpecialistTask.REPLENISHMENT: "replenishment",
        SpecialistTask.DONATION_COMMUNICATION: "donation",
    }
    for task, name in expected.items():
        assert agents.delegate(task, f"test {task}")["specialist"] == name
        assert specialists[name].prompts == [f"test {task}"]


def test_optional_specialist_copy_returns_text_or_safe_fallback():
    recipe = FakeSpecialist("recipe")
    agents = PantryAgents(pantry=Mock(), extraction=Mock(), expiry=Mock(), recipe=recipe, replenishment=Mock(), donation=Mock())
    services = AppServices(inventory=Mock(), feedback=Mock(), sessions=Mock(), photo_receipts=Mock(), settings=Settings(telegram_bot_token="test"), agents=agents)
    assert services.optional_specialist_copy(SpecialistTask.RECIPE, "friendly note") == "{'specialist': 'recipe', 'prompt': 'friendly note'}"
    unavailable = Mock()
    unavailable.delegate.side_effect = RuntimeError("offline")
    unavailable_services = AppServices(inventory=Mock(), feedback=Mock(), sessions=Mock(), photo_receipts=Mock(), settings=Settings(telegram_bot_token="test"), agents=unavailable)
    assert unavailable_services.optional_specialist_copy(SpecialistTask.RECIPE, "friendly note") is None
