"""Short-lived durable decision state in the existing households table."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from botocore.exceptions import ClientError

from pantrypulse.persistence.inventory import HOUSEHOLDS_TABLE, InventoryPersistenceError, _deserialize_map, _serialize_map
from pantrypulse.schemas import DonationCandidate, PantryItem, RecipeSuggestion, ShoppingList
from pantrypulse.tools.decisions import CombinedDecision


@dataclass(frozen=True)
class StoredDecision:
    actions: tuple[str, ...]
    recipe: RecipeSuggestion | None
    shopping_list: ShoppingList
    donation_candidates: tuple[DonationCandidate, ...]


class DecisionSessionRepository:
    """Persist an opaque, expiring decision token without a new table."""

    def __init__(self, client: Any, *, table: str = HOUSEHOLDS_TABLE) -> None:
        self._client, self._table = client, table

    @staticmethod
    def _key(household_id: str, session_id: str) -> str:
        return f"__decision_session__#{household_id}#{session_id}"

    def save(self, household_id: str, session_id: str, decision: CombinedDecision, *, minutes: int = 30) -> None:
        payload = {"actions": list(decision.actions), "recipe": decision.recipe.model_dump(mode="json") if decision.recipe else None, "shopping": decision.shopping_list.model_dump(mode="json"), "candidates": [c.model_dump(mode="json") for c in decision.donation_candidates]}
        record = {"household_id": self._key(household_id, session_id), "record_type": "decision_session", "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat(), "payload": json.dumps(payload, separators=(",", ":"))}
        try:
            self._client.put_item(TableName=self._table, Item=_serialize_map(record), ConditionExpression="attribute_not_exists(household_id)")
        except ClientError as exc:
            raise InventoryPersistenceError("Decision session could not be saved.") from exc

    def load(self, household_id: str, session_id: str) -> StoredDecision | None:
        key = self._key(household_id, session_id)
        try:
            response = self._client.get_item(TableName=self._table, Key=_serialize_map({"household_id": key}))
        except ClientError as exc:
            raise InventoryPersistenceError("Decision session could not be read.") from exc
        if not response.get("Item"):
            return None
        try:
            record = _deserialize_map(response["Item"])
            if datetime.fromisoformat(record["expires_at"]) <= datetime.now(timezone.utc):
                self.delete(household_id, session_id)
                return None
            data = json.loads(record["payload"])
            return StoredDecision(tuple(data["actions"]), RecipeSuggestion.model_validate(data["recipe"]) if data["recipe"] else None, ShoppingList.model_validate(data["shopping"]), tuple(DonationCandidate.model_validate(c) for c in data["candidates"]))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise InventoryPersistenceError("Stored decision session could not be read.") from exc

    def delete(self, household_id: str, session_id: str) -> None:
        self._client.delete_item(TableName=self._table, Key=_serialize_map({"household_id": self._key(household_id, session_id)}))


class DuplicatePhotoError(InventoryPersistenceError):
    """A confirmed Telegram photo already exists for this household."""


class PhotoReceiptRepository:
    """Persist one receipt per normalized image fingerprint without a new table."""

    def __init__(self, client: Any, *, table: str = HOUSEHOLDS_TABLE) -> None:
        self._client, self._table = client, table

    def claim(self, household_id: str, fingerprint: str) -> None:
        key = f"__photo_receipt__#{household_id}#{fingerprint}"
        try:
            self._client.put_item(TableName=self._table, Item=_serialize_map({"household_id": key, "record_type": "photo_receipt"}), ConditionExpression="attribute_not_exists(household_id)")
        except ClientError as error:
            if error.response["Error"].get("Code") == "ConditionalCheckFailedException":
                raise DuplicatePhotoError("This photo was already added to your pantry.") from error
            raise InventoryPersistenceError("Photo receipt could not be saved.") from error


@dataclass(frozen=True)
class StoredIngestion:
    """A confirmation preview that survives stateless webhook invocations."""

    items: tuple[PantryItem, ...]
    fingerprint: str


class IngestionSessionRepository:
    """Persist a short-lived photo preview in the existing households table."""

    def __init__(self, client: Any, *, table: str = HOUSEHOLDS_TABLE) -> None:
        self._client, self._table = client, table

    @staticmethod
    def _key(household_id: str, token: str) -> str:
        return f"__ingestion_session__#{household_id}#{token}"

    def save(self, household_id: str, token: str, items: list[PantryItem], fingerprint: str, *, minutes: int = 30) -> None:
        record = {
            "household_id": self._key(household_id, token),
            "record_type": "ingestion_session",
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat(),
            "payload": json.dumps({"items": [item.model_dump(mode="json") for item in items], "fingerprint": fingerprint}, separators=(",", ":")),
        }
        try:
            self._client.put_item(TableName=self._table, Item=_serialize_map(record))
        except ClientError as exc:
            raise InventoryPersistenceError("Photo preview could not be saved.") from exc

    def load(self, household_id: str, token: str) -> StoredIngestion | None:
        try:
            response = self._client.get_item(TableName=self._table, Key=_serialize_map({"household_id": self._key(household_id, token)}))
        except ClientError as exc:
            raise InventoryPersistenceError("Photo preview could not be read.") from exc
        if not response.get("Item"):
            return None
        try:
            record = _deserialize_map(response["Item"])
            if datetime.fromisoformat(record["expires_at"]) <= datetime.now(timezone.utc):
                self.delete(household_id, token)
                return None
            payload = json.loads(record["payload"])
            return StoredIngestion(tuple(PantryItem.model_validate(item) for item in payload["items"]), str(payload["fingerprint"]))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise InventoryPersistenceError("Stored photo preview could not be read.") from exc

    def delete(self, household_id: str, token: str) -> None:
        self._client.delete_item(TableName=self._table, Key=_serialize_map({"household_id": self._key(household_id, token)}))


@dataclass(frozen=True)
class StoredInteraction:
    """Opaque, short-lived callback state for a stateless Telegram webhook."""

    kind: str
    payload: dict[str, Any]


class InteractionSessionRepository:
    """Store button flows and one pending text edit without adding a table."""

    def __init__(self, client: Any, *, table: str = HOUSEHOLDS_TABLE) -> None:
        self._client, self._table = client, table

    @staticmethod
    def _key(household_id: str, token: str) -> str:
        return f"__interaction_session__#{household_id}#{token}"

    @staticmethod
    def _cursor_key(household_id: str, kind: str) -> str:
        return f"__interaction_cursor__#{household_id}#{kind}"

    @staticmethod
    def _expires(minutes: int) -> str:
        return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()

    def save(self, household_id: str, token: str, kind: str, payload: dict[str, Any], *, minutes: int = 30) -> None:
        record = {
            "household_id": self._key(household_id, token), "record_type": "interaction_session",
            "kind": kind, "expires_at": self._expires(minutes),
            "payload": json.dumps(payload, separators=(",", ":")),
        }
        try:
            self._client.put_item(TableName=self._table, Item=_serialize_map(record))
        except ClientError as exc:
            raise InventoryPersistenceError("Interaction session could not be saved.") from exc

    def load(self, household_id: str, token: str, *, kind: str | None = None) -> StoredInteraction | None:
        try:
            response = self._client.get_item(TableName=self._table, Key=_serialize_map({"household_id": self._key(household_id, token)}))
        except ClientError as exc:
            raise InventoryPersistenceError("Interaction session could not be read.") from exc
        if not response.get("Item"):
            return None
        try:
            record = _deserialize_map(response["Item"])
            if datetime.fromisoformat(record["expires_at"]) <= datetime.now(timezone.utc):
                self.delete(household_id, token)
                return None
            if kind is not None and record["kind"] != kind:
                return None
            return StoredInteraction(str(record["kind"]), json.loads(record["payload"]))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise InventoryPersistenceError("Stored interaction session could not be read.") from exc

    def delete(self, household_id: str, token: str) -> None:
        self._client.delete_item(TableName=self._table, Key=_serialize_map({"household_id": self._key(household_id, token)}))

    def set_cursor(self, household_id: str, kind: str, token: str, *, minutes: int = 30) -> None:
        record = {"household_id": self._cursor_key(household_id, kind), "record_type": "interaction_cursor", "expires_at": self._expires(minutes), "payload": json.dumps({"token": token})}
        self._client.put_item(TableName=self._table, Item=_serialize_map(record))

    def get_cursor(self, household_id: str, kind: str) -> str | None:
        key = self._cursor_key(household_id, kind)
        response = self._client.get_item(TableName=self._table, Key=_serialize_map({"household_id": key}))
        if not response.get("Item"):
            return None
        record = _deserialize_map(response["Item"])
        if datetime.fromisoformat(record["expires_at"]) <= datetime.now(timezone.utc):
            self._client.delete_item(TableName=self._table, Key=_serialize_map({"household_id": key}))
            return None
        return str(json.loads(record["payload"])["token"])

    def clear_cursor(self, household_id: str, kind: str) -> None:
        self._client.delete_item(TableName=self._table, Key=_serialize_map({"household_id": self._cursor_key(household_id, kind)}))
