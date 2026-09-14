"""Tests for the provider switch and deterministic local development tools."""

from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from pantrypulse.agents.pantry import build_agents
from pantrypulse.agents.providers import AgentRole, create_model
from pantrypulse.interface.config import ModelProvider, Settings
from pantrypulse.schemas import (
    AnalyzeGroceryImageRequest, AnalyzeGroceryImageResponse, Category,
    CheckExpiringItemsRequest, DateType, ExpirySource, ExtractedItem,
    FeedbackResponse, ImageMode, ItemStatus, PantryItem,
)
from pantrypulse.tools.domain import (
    check_expiring_items, classify_date_label, derive_high_risk, parse_gs1_barcode,
)
from pantrypulse.tools.ingestion import DevResponseCache, analyze_grocery_image, downscale_image, to_pantry_items


def _settings(provider=ModelProvider.OLLAMA):
    return Settings(telegram_bot_token="token", model_provider=provider)


def _item(**overrides):
    values = dict(household_id="h", item_id="i", name="Deli turkey", category=Category.DELI,
        quantity=1, unit="pack", purchase_date=date(2026, 9, 1), expiry_date=date(2026, 9, 4),
        date_type=DateType.USE_BY, expiry_source=ExpirySource.OCR, confidence=0.9,
        sealed=True, high_risk=True, status=ItemStatus.ACTIVE,
        created_at=datetime(2026, 9, 1, tzinfo=timezone.utc), updated_at=datetime(2026, 9, 1, tzinfo=timezone.utc))
    values.update(overrides)
    return PantryItem(**values)


def test_provider_factory_and_named_agents_construct_without_network():
    assert type(create_model(_settings(), AgentRole.TEXT)).__name__ == "OllamaModel"
    assert type(create_model(_settings(ModelProvider.BEDROCK), AgentRole.VISION)).__name__ == "BedrockModel"
    agents = build_agents(_settings())
    assert agents.pantry.name == "pantry_agent"
    assert agents.pantry.tool_names == [
        "extraction_agent",
        "expiry_agent",
        "recipe_agent",
        "replenishment_agent",
        "donation_agent",
    ]
    assert agents.extraction.name == "extraction_agent"
    assert agents.expiry.name == "expiry_agent"
    assert agents.recipe.name == "recipe_agent"
    assert agents.replenishment.name == "replenishment_agent"
    assert agents.donation.name == "donation_agent"


def test_gs1_and_high_risk_are_deterministic():
    response = parse_gs1_barcode(type("Request", (), {"raw_payload": "01012345678901281726093010LOT9"})())
    assert response.data.gtin == "01234567890128"
    assert response.data.expiry_date == date(2026, 9, 30)
    assert derive_high_risk(Category.DELI)
    assert derive_high_risk(Category.DAIRY, "soft cheese")


def test_best_by_and_sell_by_are_suppressed_before_their_dates():
    best_by = _item(date_type=DateType.BEST_BY, high_risk=False, expiry_date=date(2026, 9, 5))
    sell_by = _item(item_id="sell", date_type=DateType.SELL_BY, high_risk=False, expiry_date=date(2026, 9, 1))
    risks = check_expiring_items([best_by, sell_by], CheckExpiringItemsRequest(household_id="h", as_of=date(2026, 9, 3))).risks
    assert [risk.risk_level.value for risk in risks] == ["none", "none"]


def test_ingestion_cache_and_fallback_conversion(tmp_path: Path, caplog):
    caplog.set_level("INFO")
    extracted = ExtractedItem(name="Milk", category=Category.DAIRY, quantity=1, unit="carton",
        purchase_date=date(2026, 9, 1), date_type=DateType.ESTIMATED,
        expiry_source=ExpirySource.OCR, confidence=0.8, sealed=True)
    response = AnalyzeGroceryImageResponse(items=[extracted])
    calls = Mock(return_value=response)
    source = BytesIO()
    Image.new("RGB", (2200, 1600), "white").save(source, format="JPEG")
    request = AnalyzeGroceryImageRequest(image_bytes=source.getvalue(), mode=ImageMode.RECEIPT, household_id="h")
    cache = DevResponseCache(tmp_path)
    assert analyze_grocery_image(request, invoke_vision=calls, cache=cache, cache_key="ollama").items == [extracted]
    assert analyze_grocery_image(request, invoke_vision=calls, cache=cache, cache_key="ollama").items == [extracted]
    assert calls.call_count == 1
    assert "ingestion cache hit" in caplog.text
    pantry = to_pantry_items([extracted], household_id="h")
    assert pantry[0].expiry_source is ExpirySource.SHELF_LIFE_TABLE
    assert pantry[0].high_risk is False
    with Image.open(BytesIO(downscale_image(request.image_bytes))) as resized:
        assert max(resized.size) == 1500


def test_date_label_classifier_keeps_quality_and_safety_meaning():
    assert classify_date_label("BEST BEFORE 10/10", Category.DAIRY).date_type is DateType.BEST_BY
    assert classify_date_label("USE BY 10/10", Category.DELI).date_type is DateType.USE_BY
