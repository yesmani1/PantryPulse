"""Photo ingestion must be confirmed before it reaches inventory (IF-4)."""

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from pantrypulse.interface.handlers.photos import ingestion_confirmation
from pantrypulse.persistence.sessions import IngestionSessionRepository, StoredIngestion
from pantrypulse.schemas import (
    Category,
    DateType,
    ExpirySource,
    ItemStatus,
    PantryItem,
)


def _item() -> PantryItem:
    now = datetime(2026, 9, 4, tzinfo=timezone.utc)
    return PantryItem(
        household_id="telegram:123",
        item_id="item-1",
        name="Milk",
        category=Category.DAIRY,
        quantity=1,
        unit="carton",
        purchase_date=date(2026, 9, 4),
        expiry_date=date(2026, 9, 11),
        date_type=DateType.ESTIMATED,
        expiry_source=ExpirySource.SHELF_LIFE_TABLE,
        confidence=0.45,
        sealed=True,
        high_risk=False,
        status=ItemStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )


def _context(*, services: object, pending: dict[str, list[PantryItem]]) -> MagicMock:
    context = MagicMock()
    context.user_data = {"pending_ingestions": pending}
    context.application.bot_data = {"services": services}
    return context


def _update(data: str) -> MagicMock:
    update = MagicMock()
    update.effective_chat.send_message = AsyncMock()
    update.callback_query.data = data
    update.callback_query.answer = AsyncMock()
    return update


@pytest.mark.asyncio
async def test_confirmation_persists_exact_preview_once():
    services = MagicMock()
    context = _context(services=services, pending={"abc": [_item()]})
    update = _update("ingest:confirm:abc")

    await ingestion_confirmation(update, context)

    services.save_confirmed_items.assert_called_once_with([_item()], None)
    assert context.user_data["pending_ingestions"] == {}
    assert "Added 1 item" in update.effective_chat.send_message.call_args.args[0]
    update.callback_query.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancellation_never_persists_preview():
    services = MagicMock()
    context = _context(services=services, pending={"abc": [_item()]})
    update = _update("ingest:cancel:abc")

    await ingestion_confirmation(update, context)

    services.save_confirmed_items.assert_not_called()
    assert "did not add" in update.effective_chat.send_message.call_args.args[0]


@pytest.mark.asyncio
async def test_expired_preview_is_safe_noop():
    services = MagicMock()
    context = _context(services=services, pending={})
    update = _update("ingest:confirm:missing")

    await ingestion_confirmation(update, context)

    services.save_confirmed_items.assert_not_called()
    assert "expired" in update.effective_chat.send_message.call_args.args[0]


@pytest.mark.asyncio
async def test_lambda_callback_reloads_durable_preview_before_confirming():
    services = MagicMock()
    repository = object.__new__(IngestionSessionRepository)
    repository.load = MagicMock(return_value=StoredIngestion((_item(),), "fingerprint"))
    repository.delete = MagicMock()
    services.ingestion_sessions = repository
    context = _context(services=services, pending={})
    update = _update("ingest:confirm:abc")
    update.effective_chat.id = 123

    await ingestion_confirmation(update, context)

    repository.load.assert_called_once_with("telegram:123", "abc")
    services.save_confirmed_items.assert_called_once_with([_item()], "fingerprint")
    repository.delete.assert_called_once_with("telegram:123", "abc")
