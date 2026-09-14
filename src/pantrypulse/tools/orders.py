"""Deterministic helpers for externally placed grocery orders."""

from __future__ import annotations

import re

from pantrypulse.schemas import Category


def normalise_item_name(name: str) -> str:
    """Return the conservative duplicate key used for shopping and pantry rows."""
    return " ".join(re.sub(r"[^\w]+", " ", name.casefold()).split())


# Only unambiguous grocery words belong here.  Returning ``None`` is safer than
# calling an unfamiliar item pantry food and giving it an invented shelf life.
_CATEGORY_KEYWORDS: tuple[tuple[Category, tuple[str, ...]], ...] = (
    (Category.DAIRY, ("milk", "yogurt", "yoghurt", "cheese", "butter", "cream")),
    (Category.MEAT, ("chicken", "beef", "pork", "turkey", "lamb", "sausage")),
    (Category.DELI, ("deli", "ham", "salami", "prosciutto")),
    (Category.FROZEN, ("frozen", "ice cream")),
    (Category.BAKERY, ("bread", "bagel", "bun", "tortilla", "pastry")),
    (Category.PRODUCE, ("apple", "banana", "lettuce", "tomato", "onion", "potato", "avocado")),
    (Category.HOUSEHOLD, ("detergent", "tissue", "toilet paper", "paper towel", "dish soap")),
    (Category.PANTRY, ("rice", "pasta", "flour", "beans", "cereal", "oil", "salt", "sugar", "coffee")),
)


def infer_order_category(name: str) -> Category | None:
    """Return a category only when a shopping-list name is plainly recognisable."""
    normalized = normalise_item_name(name)
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(keyword in normalized for keyword in keywords):
            return category
    return None
