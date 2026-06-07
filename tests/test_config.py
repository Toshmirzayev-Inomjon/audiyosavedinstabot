from app.config import Settings
from app.services.ai import AIService


def _required_env(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:TEST")
    monkeypatch.delenv("WEBAPP_PUBLIC_URL", raising=False)
    monkeypatch.delenv("WEBAPP_PORT", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("RAILWAY_PUBLIC_DOMAIN", raising=False)
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_IMAGE_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("GEMINI_IMAGE_MODEL", raising=False)


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


def _ai_service(settings: Settings) -> AIService:
    return AIService(
        provider=settings.ai_provider,
        openai_api_key=settings.openai_api_key,
        openai_model=settings.openai_model,
        openai_image_model=settings.openai_image_model,
        gemini_api_key=settings.gemini_api_key,
        gemini_model=settings.gemini_model,
        gemini_image_model=settings.gemini_image_model,
    )


def test_openai_uses_one_api_key_for_ai_services(monkeypatch, tmp_path) -> None:
    _required_env(monkeypatch)
    monkeypatch.setenv("APP_ROOT", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-text-model")
    monkeypatch.setenv("OPENAI_IMAGE_MODEL", "test-image-model")

    settings = Settings.load(tmp_path / "empty.env")

    assert settings.openai_api_key == "test-key"
    assert settings.openai_model == "test-text-model"
    assert settings.openai_image_model == "test-image-model"
    assert _ai_service(settings).active_provider == "openai"


def test_auto_ai_provider_uses_local_without_api_keys(monkeypatch, tmp_path) -> None:
    _required_env(monkeypatch)
    monkeypatch.setenv("APP_ROOT", str(tmp_path))

    settings = Settings.load(tmp_path / "empty.env")
    service = _ai_service(settings)

    assert service.active_provider == "local"
    assert service.configured is True


def test_gemini_key_is_used_by_auto_ai_provider(monkeypatch, tmp_path) -> None:
    _required_env(monkeypatch)
    monkeypatch.setenv("APP_ROOT", str(tmp_path))
    monkeypatch.setenv("AI_PROVIDER", "auto")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test-model")
    monkeypatch.setenv("GEMINI_IMAGE_MODEL", "gemini-test-image-model")

    settings = Settings.load(tmp_path / "empty.env")
    service = _ai_service(settings)

    assert settings.gemini_api_key == "gemini-test-key"
    assert settings.gemini_model == "gemini-test-model"
    assert settings.gemini_image_model == "gemini-test-image-model"
    assert service.configured is True
    assert service.active_provider == "gemini"
