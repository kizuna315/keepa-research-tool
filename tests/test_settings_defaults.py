from app.models import AppSetting
from app.services.settings_defaults import (
    DEFAULT_SETTINGS,
    SECRET_SETTING_KEYS,
    get_default_setting,
)


def test_default_settings_values_match_spec():
    assert DEFAULT_SETTINGS[AppSetting.KEY_DEFAULT_MIN_PRICE] == "1500"
    assert DEFAULT_SETTINGS[AppSetting.KEY_DEFAULT_MAX_PRICE] == "10000"
    assert DEFAULT_SETTINGS[AppSetting.KEY_DEFAULT_MIN_OFFER_COUNT] == "3"
    assert DEFAULT_SETTINGS[AppSetting.KEY_DEFAULT_MAX_OFFER_COUNT] == "15"


def test_default_settings_does_not_include_keepa_api_key_value():
    assert AppSetting.KEY_KEEPA_API_KEY not in DEFAULT_SETTINGS
    assert AppSetting.KEY_KEEPA_API_KEY in SECRET_SETTING_KEYS


def test_known_keys_are_consistent_with_defaults_and_secret_keys():
    combined_keys = set(DEFAULT_SETTINGS.keys()) | set(SECRET_SETTING_KEYS)

    assert combined_keys.issubset(AppSetting.KNOWN_KEYS)
    assert AppSetting.KNOWN_KEYS.issuperset(combined_keys)


def test_get_default_setting_returns_value_or_fallback():
    assert get_default_setting(AppSetting.KEY_DEFAULT_DOMAIN_ID) == "5"
    assert get_default_setting("non_existing_key", "fallback") == "fallback"
