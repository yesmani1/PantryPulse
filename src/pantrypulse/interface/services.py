"""Application service wiring for Telegram handlers.

Handlers receive these services from Application.bot_data, keeping AWS and
model construction outside the Telegram surface and straightforward to fake.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from pantrypulse.agents.pantry import PantryAgents, SpecialistTask, build_agents
from pantrypulse.agents.providers import invoke_vision_json
from pantrypulse.interface.config import Settings
from pantrypulse.persistence.feedback import FeedbackRepository
from pantrypulse.persistence.inventory import InventoryRepository
from pantrypulse.persistence.provisioning import create_aws_session
from pantrypulse.persistence.sessions import DecisionSessionRepository, IngestionSessionRepository, InteractionSessionRepository, PhotoReceiptRepository
from pantrypulse.schemas import (
    AddInventoryItemsRequest,
    AnalyzeGroceryImageRequest,
    AnalyzeGroceryImageResponse,
    GroundedRecipeResponse,
    PantryItem,
    RecipeSuggestion,
)
from pantrypulse.tools.ingestion import (
    DevResponseCache,
    analyze_grocery_image,
    to_pantry_items,
    verify_extractions,
)

logger = logging.getLogger(__name__)


def ingestion_cache_directory() -> Path:
    """Return a writable cache directory in both local and Lambda runtimes."""
    if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        return Path("/tmp") / "pantrypulse" / "ingestion"
    return Path(".cache") / "ingestion"


def household_for_chat(chat_id: int) -> str:
    """Stable, private household key derived from the Telegram chat ID."""
    return f"telegram:{chat_id}"


@dataclass(frozen=True)
class AppServices:
    inventory: InventoryRepository
    feedback: FeedbackRepository
    sessions: DecisionSessionRepository
    photo_receipts: PhotoReceiptRepository
    settings: Settings
    agents: PantryAgents
    ingestion_sessions: IngestionSessionRepository | None = None
    interactions: InteractionSessionRepository | None = None

    def optional_specialist_copy(self, task: SpecialistTask, prompt: str) -> str | None:
        """Return bounded optional Strands wording; callers retain the facts."""
        try:
            result = self.agents.delegate(task, prompt)
            text = str(getattr(result, "text", result)).strip()
            if text:
                logger.info("specialist_assist task=%s", task.value)
                return text[:500]
            return None
        except Exception:
            logger.warning("specialist unavailable for task=%s", task, exc_info=True)
            return None

    def generate_grounded_recipe(
        self, suggestion: RecipeSuggestion, *, alternative: bool = False
    ) -> RecipeSuggestion | None:
        """Ask Recipe Agent for bounded wording around deterministic rescue facts.

        The caller has already selected safe, at-risk pantry items. This method
        may improve the title and preparation wording only; it never changes
        the selected items, safety outcome, or inventory.
        """
        confirmed = [
            ingredient
            for ingredient in suggestion.ingredients
            if not ingredient.missing and ingredient.pantry_item_id
        ]
        if not confirmed:
            return None
        ingredient_lines = "\n".join(
            f"- {ingredient.name}" + (
                f" ({ingredient.quantity:g}" + (f" {ingredient.unit}" if ingredient.unit else "") + ")"
                if ingredient.quantity is not None
                else ""
            )
            for ingredient in confirmed
        )
        variation = (
            "Create a meaningfully different preparation from the prior recipe."
            if alternative
            else "Create the best simple preparation."
        )
        prompt = f"""Create one concise rescue recipe using only these confirmed pantry ingredients:
{ingredient_lines}

{variation}
You may optionally mention only oil, salt, pepper, or water, and must label them optional.
Never add any other ingredient, infer dates, give food-safety advice, change the rescue items,
or claim inventory actions. Return JSON only in this exact shape:
{{"title":"...","steps":["...","...","..."],"preparation_minutes":20,"optional_staples":["oil"]}}
The title must name at least one confirmed pantry ingredient."""
        try:
            result = self.agents.delegate(SpecialistTask.RECIPE, prompt)
            text = str(getattr(result, "text", result)).strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            generated = GroundedRecipeResponse.model_validate(json.loads(text))
            logger.info("specialist_recipe_generated alternative=%s", alternative)
            return suggestion.model_copy(update={
                "name": generated.title,
                "instructions": generated.steps,
                "preparation_minutes": generated.preparation_minutes,
                "optional_staples": generated.optional_staples,
            })
        except Exception:
            logger.warning("grounded recipe unavailable; using deterministic fallback", exc_info=True)
            return None


    def _read(self, request: AnalyzeGroceryImageRequest, model_id: str | None):
        """One independent read of the image by one named model."""
        return analyze_grocery_image(
            request,
            invoke_vision=lambda image_bytes, prompt: invoke_vision_json(
                self.settings,
                image_bytes,
                prompt,
                schema=AnalyzeGroceryImageResponse.model_json_schema(),
                model_id=model_id,
            ),
            cache=DevResponseCache(ingestion_cache_directory()),
            cache_key=f"{self.settings.model_provider}:{model_id or 'default'}",
        )

    def analyze_photo(self, request: AnalyzeGroceryImageRequest) -> list[PantryItem]:
        """Extract and tier an image; callers must explicitly confirm before saving.

        Two different models read the same photo. A printed date is kept only
        where both agree, because one model alone reports wrong dates at high
        confidence and cannot be talked out of them.
        """
        primary = self._read(request, self.settings.vision_model())
        items = primary.items
        verifier_model = self.settings.verifier_vision_model()
        if verifier_model:
            try:
                verifier = self._read(request, verifier_model)
                items = verify_extractions(primary.items, verifier.items)
            except Exception:  # a verifier outage must not block ingestion
                logger.warning("Vision verifier unavailable; dates unverified", exc_info=True)
                items = [
                    item.model_copy(update={"expiry_date": None, "needs_confirmation": True})
                    if item.expiry_date is not None
                    else item
                    for item in primary.items
                ]

        return to_pantry_items(
            items,
            household_id=request.household_id,
            purchase_date=request.purchase_date,
        )
    def save_confirmed_items(self, items: list[PantryItem], photo_fingerprint: str | None = None) -> None:
        """Atomically persist the exact items shown in a confirmation preview."""
        if not items:
            raise ValueError("At least one extracted item is required.")
        if photo_fingerprint:
            self.photo_receipts.claim(items[0].household_id, photo_fingerprint)
        self.inventory.add_inventory_items(
            AddInventoryItemsRequest(items=items, idempotency_key=str(uuid4()))
        )


def create_services(settings: Settings) -> AppServices:
    """Create UAT repositories through the normal ignored-.env credential chain."""
    session = create_aws_session(profile_name=None, region_name="us-west-2")
    client: Any = session.client("dynamodb")
    return AppServices(
        inventory=InventoryRepository(client), feedback=FeedbackRepository(client),
        sessions=DecisionSessionRepository(client), photo_receipts=PhotoReceiptRepository(client),
        settings=settings, agents=build_agents(settings), ingestion_sessions=IngestionSessionRepository(client),
        interactions=InteractionSessionRepository(client)
    )
