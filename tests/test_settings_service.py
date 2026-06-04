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


def test_get_returns_default_setting_when_not_saved(app, db_schema):
    with app.app_context():
        value = SettingsService.get(AppSetting.KEY_DEFAULT_MIN_PRICE)
    assert value == "1500"


def test_get_prefers_saved_value_over_default(app, db_schema):
    with app.app_context():
        SettingsService.set(AppSetting.KEY_DEFAULT_MIN_PRICE, "2000")
        value = SettingsService.get(AppSetting.KEY_DEFAULT_MIN_PRICE)
    assert value == "2000"


def test_get_returns_fallback_for_unknown_key(app, db_schema):
    with app.app_context():
        value = SettingsService.get("custom_key", "fallback")
    assert value == "fallback"


def test_set_creates_new_setting(app, db_schema):
    with app.app_context():
        setting = SettingsService.set("custom_key", "custom_value")
        fetched = AppSetting.query.filter_by(key="custom_key").first()
    assert setting.id is not None
    assert fetched is not None
    assert fetched.value == "custom_value"


def test_set_updates_existing_setting(app, db_schema):
    with app.app_context():
        SettingsService.set(AppSetting.KEY_DEFAULT_MAX_PRICE, "12000")
        updated = SettingsService.set(AppSetting.KEY_DEFAULT_MAX_PRICE, "9000")
        fetched = AppSetting.query.filter_by(key=AppSetting.KEY_DEFAULT_MAX_PRICE).first()
    assert updated.id is not None
    assert fetched is not None
    assert fetched.value == "9000"


def test_get_many_returns_multiple_values(app, db_schema):
    with app.app_context():
        SettingsService.set(AppSetting.KEY_DEFAULT_DOMAIN_ID, "1")
        result = SettingsService.get_many(
            [
                AppSetting.KEY_DEFAULT_DOMAIN_ID,
                AppSetting.KEY_DEFAULT_MIN_OFFER_COUNT,
                "unknown_key",
            ]
        )
    assert result[AppSetting.KEY_DEFAULT_DOMAIN_ID] == "1"
    assert result[AppSetting.KEY_DEFAULT_MIN_OFFER_COUNT] == "3"
    assert result["unknown_key"] is None


def test_set_many_saves_multiple_values(app, db_schema):
    with app.app_context():
        saved = SettingsService.set_many(
            {
                AppSetting.KEY_DEFAULT_MIN_PRICE: "1700",
                AppSetting.KEY_DEFAULT_MAX_PRICE: "11000",
                "custom_flag": "on",
            }
        )
        all_rows = AppSetting.query.filter(
            AppSetting.key.in_(
                [
                    AppSetting.KEY_DEFAULT_MIN_PRICE,
                    AppSetting.KEY_DEFAULT_MAX_PRICE,
                    "custom_flag",
                ]
            )
        ).all()
    assert set(saved.keys()) == {
        AppSetting.KEY_DEFAULT_MIN_PRICE,
        AppSetting.KEY_DEFAULT_MAX_PRICE,
        "custom_flag",
    }
    assert len(all_rows) == 3


def test_get_all_known_settings_masks_secret_by_default(app, db_schema):
    with app.app_context():
        SettingsService.set(AppSetting.KEY_KEEPA_API_KEY, "dummy-secret-key")
        result = SettingsService.get_all_known_settings(include_secrets=False)
    assert result[AppSetting.KEY_KEEPA_API_KEY] is None


def test_get_all_known_settings_returns_secret_when_enabled(app, db_schema):
    with app.app_context():
        SettingsService.set(AppSetting.KEY_KEEPA_API_KEY, "dummy-secret-key")
        result = SettingsService.get_all_known_settings(include_secrets=True)
    assert result[AppSetting.KEY_KEEPA_API_KEY] == "dummy-secret-key"


def test_set_raises_value_error_for_empty_key(app, db_schema):
    with app.app_context():
        with pytest.raises(ValueError):
            SettingsService.set("", "x")
        with pytest.raises(ValueError):
            SettingsService.set("   ", "x")


def test_set_many_rolls_back_when_invalid_key_is_included(app, db_schema):
    with app.app_context():
        with pytest.raises(ValueError):
            SettingsService.set_many(
                {
                    AppSetting.KEY_DEFAULT_MIN_PRICE: "2000",
                    "": "invalid",
                }
            )

        persisted = AppSetting.query.filter_by(
            key=AppSetting.KEY_DEFAULT_MIN_PRICE
        ).first()
        assert persisted is None
