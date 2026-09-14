"""Deterministic Tier 3 shelf-life estimates for items without label dates."""

from dataclasses import dataclass
from datetime import date, timedelta

from pantrypulse.schemas import Category, DateType, ExpirySource


ESTIMATED_CONFIDENCE = 0.45

_SHELF_LIFE_DAYS: dict[Category, int | None] = {
    Category.DAIRY: 7,
    Category.PRODUCE: 5,
    Category.MEAT: 2,
    Category.DELI: 3,
    Category.BAKERY: 5,
    Category.PANTRY: 90,
    Category.FROZEN: 90,
    Category.HOUSEHOLD: None,
    Category.NON_PERISHABLE: None,
}


@dataclass(frozen=True)
class ShelfLifeEstimate:
    """The result of a category-based expiry fallback estimate."""

    expiry_date: date | None
    date_type: DateType
    expiry_source: ExpirySource
    confidence: float


def estimate_shelf_life(category: Category, purchase_date: date) -> ShelfLifeEstimate:
    """Estimate expiry only when barcode and OCR provided no usable date.

    The estimate is intentionally broad, low-confidence demo data. It must be
    surfaced as an estimate, never as a printed or scanned expiry date.
    """
    shelf_life_days = _SHELF_LIFE_DAYS[category]
    if shelf_life_days is None:
        return ShelfLifeEstimate(
            expiry_date=None,
            date_type=DateType.NONE,
            expiry_source=ExpirySource.SHELF_LIFE_TABLE,
            confidence=ESTIMATED_CONFIDENCE,
        )

    return ShelfLifeEstimate(
        expiry_date=purchase_date + timedelta(days=shelf_life_days),
        date_type=DateType.ESTIMATED,
        expiry_source=ExpirySource.SHELF_LIFE_TABLE,
        confidence=ESTIMATED_CONFIDENCE,
    )
