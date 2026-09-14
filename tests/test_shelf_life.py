"""Tests for the deterministic BE-5 shelf-life fallback."""

from datetime import date, timedelta

import pytest

from pantrypulse.schemas import Category, DateType, ExpirySource
from pantrypulse.tools.shelf_life import ESTIMATED_CONFIDENCE, estimate_shelf_life


PURCHASE_DATE = date(2026, 9, 3)


@pytest.mark.parametrize(
    ("category", "days"),
    [
        (Category.DAIRY, 7),
        (Category.PRODUCE, 5),
        (Category.MEAT, 2),
        (Category.DELI, 3),
        (Category.BAKERY, 5),
        (Category.PANTRY, 90),
        (Category.FROZEN, 90),
    ],
)
def test_perishable_categories_return_low_confidence_estimates(category, days):
    estimate = estimate_shelf_life(category, PURCHASE_DATE)

    assert estimate.expiry_date == PURCHASE_DATE + timedelta(days=days)
    assert estimate.date_type is DateType.ESTIMATED
    assert estimate.expiry_source is ExpirySource.SHELF_LIFE_TABLE
    assert estimate.confidence == ESTIMATED_CONFIDENCE
    assert estimate.confidence < 0.6


@pytest.mark.parametrize("category", [Category.HOUSEHOLD, Category.NON_PERISHABLE])
def test_non_expiring_categories_are_never_counted_down(category):
    estimate = estimate_shelf_life(category, PURCHASE_DATE)

    assert estimate.expiry_date is None
    assert estimate.date_type is DateType.NONE
    assert estimate.expiry_source is ExpirySource.SHELF_LIFE_TABLE
    assert estimate.confidence == ESTIMATED_CONFIDENCE
