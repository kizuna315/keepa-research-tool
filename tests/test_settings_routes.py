import pytest

from app.extensions import db
from app.models import AppSetting
from app.services.settings_service import SettingsService


@pytest.fixture()
def db_schema(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        yield
        db.session.remove()
        db.drop_all()


def _valid_form_data() -> dict[str, str]:
    return {
        AppSetting.KEY_DEFAULT_DOMAIN_ID: "5",
        AppSetting.KEY_DEFAULT_MIN_PRICE: "1500",
        AppSetting.KEY_DEFAULT_MAX_PRICE: "10000",
        AppSetting.KEY_DEFAULT_MIN_OFFER_COUNT: "3",
        AppSetting.KEY_DEFAULT_MAX_OFFER_COUNT: "15",
        AppSetting.KEY_DEFAULT_MIN_SALES_RANK_DROPS_90: "10",
        AppSetting.KEY_CSV_EXPORT_DIR: "exports",
        AppSetting.KEY_EXCLUDE_AMAZON_IN_STOCK: "on",
    }


def test_settings_get_returns_form(client, db_schema):
    response = client.get("/settings/")
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Keepa API Key" in text
    assert 'type="password"' in text


def test_settings_get_uses_default_values_when_not_saved(client, db_schema):
    response = client.get("/settings/")
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'name="default_min_price" value="1500"' in text
    assert 'name="default_max_price" value="10000"' in text
    assert 'name="default_min_offer_count" value="3"' in text
    assert 'name="default_max_offer_count" value="15"' in text


def test_settings_get_does_not_expose_saved_api_key(client, app, db_schema):
    with app.app_context():
        SettingsService.set(AppSetting.KEY_KEEPA_API_KEY, "dummy-keepa-api-key-for-test")

    response = client.get("/settings/")
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "dummy-keepa-api-key-for-test" not in text


def test_settings_post_saves_regular_values(client, app, db_schema):
    response = client.post("/settings/", data=_valid_form_data(), follow_redirects=True)

    assert response.status_code == 200
    assert "alert-success" in response.get_data(as_text=True)
    with app.app_context():
        assert SettingsService.get(AppSetting.KEY_DEFAULT_MIN_PRICE) == "1500"
        assert SettingsService.get(AppSetting.KEY_DEFAULT_MAX_PRICE) == "10000"
        assert SettingsService.get(AppSetting.KEY_EXCLUDE_AMAZON_IN_STOCK) == "true"


def test_saved_settings_are_redisplayed_on_settings_page(client, app, db_schema):
    with app.app_context():
        SettingsService.set(AppSetting.KEY_DEFAULT_MIN_PRICE, "2200")
        SettingsService.set(AppSetting.KEY_DEFAULT_MAX_PRICE, "8800")

    response = client.get("/settings/")
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'name="default_min_price" value="2200"' in text
    assert 'name="default_max_price" value="8800"' in text


def test_settings_post_saves_api_key_when_provided(client, app, db_schema):
    data = _valid_form_data()
    data[AppSetting.KEY_KEEPA_API_KEY] = "dummy-keepa-api-key-for-test"

    response = client.post("/settings/", data=data, follow_redirects=True)

    assert response.status_code == 200
    with app.app_context():
        assert SettingsService.get(AppSetting.KEY_KEEPA_API_KEY) == "dummy-keepa-api-key-for-test"
    assert "dummy-keepa-api-key-for-test" not in response.get_data(as_text=True)


def test_settings_post_keeps_existing_api_key_when_input_is_blank(client, app, db_schema):
    with app.app_context():
        SettingsService.set(AppSetting.KEY_KEEPA_API_KEY, "dummy-keepa-api-key-for-test")

    data = _valid_form_data()
    data[AppSetting.KEY_KEEPA_API_KEY] = ""

    response = client.post("/settings/", data=data, follow_redirects=True)

    assert response.status_code == 200
    with app.app_context():
        assert SettingsService.get(AppSetting.KEY_KEEPA_API_KEY) == "dummy-keepa-api-key-for-test"
    assert "dummy-keepa-api-key-for-test" not in response.get_data(as_text=True)


def test_settings_success_does_not_display_api_key_value(client, app, db_schema):
    data = _valid_form_data()
    data[AppSetting.KEY_KEEPA_API_KEY] = "SECRET_KEEPA_KEY_123"

    response = client.post("/settings/", data=data, follow_redirects=True)
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "設定を保存しました。" in text
    assert "SECRET_KEEPA_KEY_123" not in text


def test_settings_save_error_does_not_flash_api_key(client, db_schema, monkeypatch, caplog):
    data = _valid_form_data()
    data[AppSetting.KEY_KEEPA_API_KEY] = "SECRET_KEEPA_KEY_123"

    def failing_set_many(values):
        raise RuntimeError("db failed apiKey=SECRET_KEEPA_KEY_123")

    monkeypatch.setattr("app.routes.settings.SettingsService.set_many", failing_set_many)

    with caplog.at_level("ERROR"):
        response = client.post("/settings/", data=data)

    text = response.get_data(as_text=True)
    assert response.status_code == 500
    assert "データベース保存中にエラーが発生しました。" in text
    assert "SECRET_KEEPA_KEY_123" not in text
    assert "SECRET_KEEPA_KEY_123" not in caplog.text
    assert "[REDACTED]" in caplog.text


def test_settings_post_invalid_input_returns_400_and_does_not_update_db(client, app, db_schema):
    with app.app_context():
        SettingsService.set(AppSetting.KEY_DEFAULT_MIN_PRICE, "1500")

    invalid_data = _valid_form_data()
    invalid_data[AppSetting.KEY_DEFAULT_MIN_PRICE] = "abc"
    invalid_data[AppSetting.KEY_CSV_EXPORT_DIR] = "../bad"

    response = client.post("/settings/", data=invalid_data)
    text = response.get_data(as_text=True)

    assert response.status_code == 400
    assert "alert-danger" in text
    assert "is-invalid" in text
    assert 'value="abc"' in text
    assert '../bad' in text

    with app.app_context():
        assert SettingsService.get(AppSetting.KEY_DEFAULT_MIN_PRICE) == "1500"


def test_invalid_post_never_exposes_api_key_in_html(client, app, db_schema):
    with app.app_context():
        SettingsService.set(AppSetting.KEY_KEEPA_API_KEY, "dummy-keepa-api-key-for-test")

    invalid_data = _valid_form_data()
    invalid_data[AppSetting.KEY_DEFAULT_MAX_PRICE] = "100"
    invalid_data[AppSetting.KEY_DEFAULT_MIN_PRICE] = "200"

    response = client.post("/settings/", data=invalid_data)

    assert response.status_code == 400
    assert "dummy-keepa-api-key-for-test" not in response.get_data(as_text=True)


def test_dashboard_and_health_still_available(client):
    dashboard = client.get("/")
    health = client.get("/health")

    assert dashboard.status_code == 200
    assert health.status_code == 200


def test_navigation_settings_link_points_to_settings_page(client):
    response = client.get("/")
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'href="/settings/"' in text
