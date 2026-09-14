from pantrypulse.interface import lambda_handler
from pantrypulse.interface.lambda_handler import handler


def test_scheduled_event_is_acknowledged_without_loading_secrets():
    result = handler({"source": "pantrypulse.schedule", "action": "daily_check"}, None)
    assert result == {"statusCode": 202, "body": "scheduled check acknowledged"}


def test_webhook_rejects_missing_secret_without_processing(monkeypatch):
    monkeypatch.setattr(lambda_handler, "_webhook_secret", lambda: "secret")
    monkeypatch.setattr(lambda_handler, "_process_webhook", lambda _payload: (_ for _ in ()).throw(AssertionError()))
    assert handler({"body": "{}", "headers": {}}, None) == {"statusCode": 401, "body": "unauthorized"}


def test_webhook_processes_matching_secret(monkeypatch):
    received = []

    async def fake_process(payload):
        received.append(payload)

    monkeypatch.setattr(lambda_handler, "_webhook_secret", lambda: "secret")
    monkeypatch.setattr(lambda_handler, "_process_webhook", fake_process)
    result = handler({"body": '{"update_id": 1}', "headers": {"X-Telegram-Bot-Api-Secret-Token": "secret"}}, None)
    assert result == {"statusCode": 200, "body": "ok"}
    assert received == [{"update_id": 1}]
