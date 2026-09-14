"""IF-3 / IF-5 — fixtures validate, and every rendered row states its source."""

from datetime import date

import pytest

from pantrypulse.fixtures import load_pantry_items
from pantrypulse.interface.rendering import (
    _INGEST_TIER_LABEL,
    _SOURCE_LABEL,
    render_item,
    render_pantry,
)
from pantrypulse.schemas import DateType


@pytest.fixture
def items():
    """Anchored to a fixed day so assertions about dates do not drift."""
    return load_pantry_items(today=date(2026, 8, 26))


def test_fixtures_validate_against_schema(items):
    """CLAUDE.md: a fixture that will not validate means the contract moved
    without anyone saying so. Loading raises ValidationError if that happens."""
    assert len(items) == 30  # spec 7.1: pantry_state_demo.json is a 30-item pantry


def test_fixtures_cover_every_date_type(items):
    """The rendering has a branch per date_type; the fixtures must exercise all."""
    assert {item.date_type for item in items} == set(DateType)


def test_every_row_states_its_source(items):
    """IF-5, with no exceptions. This is the trust feature."""
    for item in items:
        row = render_item(item)
        assert _SOURCE_LABEL[item.expiry_source] in row, row
        assert _INGEST_TIER_LABEL[item.expiry_source] in row, row


def test_no_row_shows_a_bare_date(items):
    """Every date is qualified by what kind of date it is."""
    qualifiers = ("Use By", "Best Before", "Sell By", "Est.", "No expiry date")
    for item in items:
        row = render_item(item)
        assert any(q in row for q in qualifiers), row


def test_quality_and_safety_dates_read_differently(items):
    by_name = {item.name: render_item(item) for item in items}
    assert "Best Before" in by_name["Greek Yogurt"]
    assert "Use By" in by_name["Sliced Turkey"]


def test_sell_by_is_marked_as_not_the_users_deadline(items):
    row = next(r for i, r in ((i, render_item(i)) for i in items)
               if i.date_type is DateType.SELL_BY)
    assert "retailer date, not yours" in row


def test_non_perishable_is_never_given_a_date(items):
    row = next(r for i, r in ((i, render_item(i)) for i in items)
               if i.date_type is DateType.NONE)
    assert "No expiry date" in row
    assert "keeps indefinitely" in row


def test_low_confidence_estimate_is_flagged(items):
    row = next(render_item(i) for i in items if i.name == "Baby Spinach")
    assert "estimated from category" in row
    assert "low confidence" in row


def test_anchoring_keeps_fixtures_fresh():
    """Loading on a later day shifts the dates rather than letting them expire."""
    early = load_pantry_items(today=date(2026, 8, 26))
    later = load_pantry_items(today=date(2026, 10, 26))
    yogurt_early = next(i for i in early if i.name == "Greek Yogurt")
    yogurt_later = next(i for i in later if i.name == "Greek Yogurt")
    assert (yogurt_later.expiry_date - yogurt_early.expiry_date).days == 61


def test_quantities_lose_the_trailing_zero(items):
    assert "500 g" in render_item(next(i for i in items if i.name == "Greek Yogurt"))


def test_empty_pantry_reads_as_guidance_not_an_error():
    assert "Send me a photo" in render_pantry([])
