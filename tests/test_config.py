from app.config import Settings


def _required_env(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:TEST")
    monkeypatch.delenv("WEBAPP_PUBLIC_URL", raising=False)
    monkeypatch.delenv("WEBAPP_PORT", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("RAILWAY_PUBLIC_DOMAIN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_API_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_MUSIC_MODEL", raising=False)
    monkeypatch.delenv("HUGGINGFACE_ASR_MODEL", raising=False)
    monkeypatch.delenv("AUDD_API_TOKEN", raising=False)


def test_railway_domain_is_used_for_webapp(monkeypatch, tmp_path) -> None:
    _required_env(monkeypatch)
    monkeypatch.setenv("APP_ROOT", str(tmp_path))
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "saved-insta.up.railway.app")

    settings = Settings.load(tmp_path / "empty.env")

    assert settings.webapp_public_url == "https://saved-insta.up.railway.app"


def test_explicit_webapp_url_overrides_railway(monkeypatch, tmp_path) -> None:
    _required_env(monkeypatch)
    monkeypatch.setenv("APP_ROOT", str(tmp_path))
    monkeypatch.setenv("WEBAPP_PUBLIC_URL", "https://app.example.com/")
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "saved-insta.up.railway.app")

    settings = Settings.load(tmp_path / "empty.env")

    assert settings.webapp_public_url == "https://app.example.com"


def test_railway_port_is_used_when_webapp_port_is_missing(
    monkeypatch,
    tmp_path,
) -> None:
    _required_env(monkeypatch)
    monkeypatch.setenv("APP_ROOT", str(tmp_path))
    monkeypatch.setenv("PORT", "4321")

    settings = Settings.load(tmp_path / "empty.env")

    assert settings.webapp_port == 4321


def test_huggingface_settings_are_loaded(monkeypatch, tmp_path) -> None:
    _required_env(monkeypatch)
    monkeypatch.setenv("APP_ROOT", str(tmp_path))
    monkeypatch.setenv("HUGGINGFACE_API_TOKEN", "hf_test_token")
    monkeypatch.setenv("HUGGINGFACE_MUSIC_MODEL", "owner/music-model")
    monkeypatch.setenv("HUGGINGFACE_ASR_MODEL", "owner/asr-model")
    monkeypatch.setenv("AUDD_API_TOKEN", "audd_test_token")

    settings = Settings.load(tmp_path / "empty.env")

    assert settings.huggingface_api_token == "hf_test_token"
    assert settings.huggingface_music_model == "owner/music-model"
    assert settings.huggingface_asr_model == "owner/asr-model"
    assert settings.audd_api_token == "audd_test_token"


def test_owner_is_admin_when_admin_ids_is_empty(monkeypatch, tmp_path) -> None:
    _required_env(monkeypatch)
    monkeypatch.setenv("APP_ROOT", str(tmp_path))
    monkeypatch.setenv("ADMIN_IDS", "")

    settings = Settings.load(tmp_path / "empty.env")

    assert 7795087338 in settings.admin_ids
