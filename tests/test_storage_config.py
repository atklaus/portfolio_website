from lib.storage.s3_compat import get_storage_config


def test_r2_precedence_over_spaces(monkeypatch):
    monkeypatch.setenv("R2_BUCKET", "r2-bucket")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "r2-key")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "r2-secret")
    monkeypatch.setenv("R2_ENDPOINT", "https://r2.example")
    monkeypatch.setenv("R2_REGION", "auto")
    monkeypatch.setenv("SPACES_BUCKET", "spaces-bucket")
    monkeypatch.setenv("SPACES_ACCESS_KEY_ID", "spaces-key")
    monkeypatch.setenv("SPACES_SECRET_ACCESS_KEY", "spaces-secret")

    config = get_storage_config(reload=True)

    assert config.provider == "r2"
    assert config.bucket == "r2-bucket"
