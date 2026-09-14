"""Loading for the mock data in fixtures/ (S-4, spec section 7).

Shared, not interface-only: the eval suite will want the same items.

Fixture dates are stored against an anchor_date and shifted to today on load,
so a fixture written in August still reads as "2 days past best_by" in
October. Set anchor_to_today=False to get the literal stored dates.
"""

import json
from datetime import date, timedelta
from pathlib import Path
from typing import TypeVar

from pantrypulse.schemas import (
    ContractModel,
    DonationCandidate,
    ExpiryRisk,
    ExtractedItem,
    PantryItem,
    RecipeSuggestion,
    RescueStats,
)

# src/pantrypulse/fixtures.py -> repo root -> fixtures/
FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"

_DATE_FIELDS = ("purchase_date", "expiry_date", "estimated_depletion_date")

_Model = TypeVar("_Model", bound=ContractModel)


def _shift(raw: dict, delta: timedelta) -> dict:
    """Move every date field in one raw item by delta. Datetimes are left alone:
    created_at/updated_at are provenance, not part of the expiry story."""
    shifted = dict(raw)
    for field in _DATE_FIELDS:
        value = shifted.get(field)
        if value is not None:
            shifted[field] = (date.fromisoformat(value) + delta).isoformat()
    return shifted


def _load_items(
    name: str,
    model: type[_Model],
    *,
    anchor_to_today: bool,
    today: date | None,
) -> list[_Model]:
    """Load and validate a list-shaped fixture: {"anchor_date"?, "items": [...]}.

    Raises:
        pydantic.ValidationError: a fixture no longer matches schemas.py, which
            per CLAUDE.md means the contract changed without anyone saying so.
    """
    payload = json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))

    delta = timedelta(0)
    if anchor_to_today and "anchor_date" in payload:
        anchor = date.fromisoformat(payload["anchor_date"])
        delta = (today or date.today()) - anchor

    return [model(**_shift(raw, delta)) for raw in payload["items"]]


def load_pantry_items(
    name: str = "pantry_state_demo.json",
    *,
    anchor_to_today: bool = True,
    today: date | None = None,
) -> list[PantryItem]:
    return _load_items(name, PantryItem, anchor_to_today=anchor_to_today, today=today)


def load_extracted_items(
    name: str,
    *,
    anchor_to_today: bool = True,
    today: date | None = None,
) -> list[ExtractedItem]:
    """name is one of extracted_items_receipt.json, extracted_items_package.json,
    or purchase_history_60d.json — all three are lists of ExtractedItem."""
    return _load_items(name, ExtractedItem, anchor_to_today=anchor_to_today, today=today)


def load_expiry_risks(
    name: str = "expiry_risks_mixed.json",
    *,
    anchor_to_today: bool = True,
    today: date | None = None,
) -> list[ExpiryRisk]:
    return _load_items(name, ExpiryRisk, anchor_to_today=anchor_to_today, today=today)


def load_donation_candidates(
    name: str = "donation_candidates.json",
    *,
    anchor_to_today: bool = True,
    today: date | None = None,
) -> list[DonationCandidate]:
    return _load_items(
        name, DonationCandidate, anchor_to_today=anchor_to_today, today=today
    )


def load_recipe_suggestion(name: str = "recipe_shakshuka.json") -> RecipeSuggestion:
    """A single recipe, not a list — no anchor_date, it carries no expiry dates."""
    payload = json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))
    payload.pop("_comment", None)
    return RecipeSuggestion(**payload)


def load_rescue_stats(name: str = "rescue_stats.json") -> list[RescueStats]:
    """Period strings like "2026-07" — no dates to anchor-shift."""
    payload = json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))
    return [RescueStats(**raw) for raw in payload["items"]]
