from pantrypulse.interface.services import ingestion_cache_directory


def test_ingestion_cache_uses_local_directory_outside_lambda(monkeypatch):
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    assert ingestion_cache_directory().as_posix() == ".cache/ingestion"


def test_ingestion_cache_uses_writable_tmp_in_lambda(monkeypatch):
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "pantrypulse-uat-bot")
    assert ingestion_cache_directory().as_posix() == "/tmp/pantrypulse/ingestion"
