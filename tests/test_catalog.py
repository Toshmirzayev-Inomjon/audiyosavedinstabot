from app.catalog import CATALOG, SERVICES, plan_allows, serialize_catalog
from app.services.catalog_executor import execute_local


def test_catalog_has_ten_categories_and_one_hundred_unique_services() -> None:
    assert len(CATALOG) == 10
    assert len(SERVICES) == 100
    assert sum(len(category.services) for category in CATALOG) == 100


def test_free_plan_only_unlocks_music_downloader() -> None:
    unlocked = {
        item["slug"]
        for category in serialize_catalog("free", ai_configured=True)
        for item in category["services"]
        if item["unlocked"]
    }

    assert unlocked == {"music_downloader"}
    assert plan_allows("standard", "free")
    assert plan_allows("premium", "standard")
    assert not plan_allows("standard", "premium")


def test_standard_plan_unlocks_about_half_of_catalog() -> None:
    unlocked = [
        item
        for category in serialize_catalog("standard", ai_configured=True)
        for item in category["services"]
        if item["unlocked"]
    ]

    assert 45 <= len(unlocked) <= 55


def test_ai_services_report_missing_configuration() -> None:
    items = [
        item
        for category in serialize_catalog("premium", ai_configured=False)
        for item in category["services"]
    ]
    ai_chat = next(item for item in items if item["slug"] == "ai_chat")
    password = next(item for item in items if item["slug"] == "password_generator")

    assert ai_chat["configured"] is False
    assert ai_chat["ready"] is False
    assert password["configured"] is True
    assert password["ready"] is True


def test_local_catalog_tools() -> None:
    password = execute_local("password_generator", "24").text
    bmi = execute_local("bmi", "70,1.75").text
    loan = execute_local("loan_calculator", "1000000,12,12").text
    qr = execute_local("qr_barcode", "https://example.com").image

    assert len(password.splitlines()[-1]) == 24
    assert "22.9" in bmi
    assert "oylik" in loan
    assert qr is not None and qr.startswith(b"\x89PNG")
