"""PantryPulse Agents-as-Tools registry with explicit, switchable models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from strands import Agent

from pantrypulse.agents.providers import AgentRole, create_model
from pantrypulse.interface.config import Settings


_COMMON = "Return only validated PantryPulse contract data. Never invent an expiry date or safety claim."


class SpecialistTask(StrEnum):
    """Agent-eligible work; safety and persistence never enter this router."""

    EXTRACTION = "extraction"
    EXPIRY_EXPLANATION = "expiry_explanation"
    RECIPE = "recipe"
    REPLENISHMENT = "replenishment"
    DONATION_COMMUNICATION = "donation_communication"


@dataclass(frozen=True)
class PantryAgents:
    """One orchestrator and the five explicitly routed specialist agents."""

    pantry: Any
    extraction: Any
    expiry: Any
    recipe: Any
    replenishment: Any
    donation: Any

    def delegate(self, task: SpecialistTask, prompt: str) -> Any:
        """Route bounded generative work to one named specialist.

        The caller supplies deterministic safety facts; a specialist may explain
        or phrase them but cannot alter classification, eligibility, or storage.
        """
        specialist = {
            SpecialistTask.EXTRACTION: self.extraction,
            SpecialistTask.EXPIRY_EXPLANATION: self.expiry,
            SpecialistTask.RECIPE: self.recipe,
            SpecialistTask.REPLENISHMENT: self.replenishment,
            SpecialistTask.DONATION_COMMUNICATION: self.donation,
        }[task]
        return specialist(prompt)


def build_agents(settings: Settings) -> PantryAgents:
    """Create the hierarchy; all provider creation stays in providers.py."""
    text_model = create_model(settings, AgentRole.TEXT)
    vision_model = create_model(settings, AgentRole.VISION)
    extraction = Agent(name="extraction_agent", description="Extract grocery details from images.", model=vision_model, system_prompt=f"You extract groceries from receipt and package images. {_COMMON}")
    expiry = Agent(name="expiry_agent", description="Classify date labels and explain them.", model=text_model, system_prompt=f"You classify date labels and explain their consumer meaning. {_COMMON}")
    recipe = Agent(name="recipe_agent", description="Create grounded rescue recipes from confirmed pantry items.", model=text_model, system_prompt=f"You create concise recipes only from confirmed pantry ingredients and explicitly allowed optional staples. {_COMMON}")
    replenishment = Agent(name="replenishment_agent", description="Forecast depletion and shopping needs.", model=text_model, system_prompt=f"You forecast depletion and create a concise shopping list. {_COMMON}")
    donation = Agent(name="donation_agent", description="Apply strict donation safety eligibility.", model=text_model, system_prompt=f"You apply stricter donation safety rules than personal-use rules. {_COMMON}")
    pantry = Agent(name="pantry_agent", model=text_model, system_prompt=f"You coordinate PantryPulse specialists into one household decision. {_COMMON}", tools=[extraction, expiry, recipe, replenishment, donation])
    return PantryAgents(pantry=pantry, extraction=extraction, expiry=expiry, recipe=recipe, replenishment=replenishment, donation=donation)
