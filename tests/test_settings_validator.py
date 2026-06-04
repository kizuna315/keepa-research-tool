from app.models import AppSetting
from app.services.settings_validator import validate_settings_input


def _valid_values() -> dict[str, str]:
    return {
        AppSetting.KEY_DEFAULT_DOMAIN_ID: "5",
        AppSetting.KEY_DEFAULT_MIN_PRICE: "1500",
        AppSetting.KEY_DEFAULT_MAX_PRICE: "10000",
        AppSetting.KEY_DEFAULT_MIN_OFFER_COUNT: "3",
        AppSetting.KEY_DEFAULT_MAX_OFFER_COUNT: "15",
        AppSetting.KEY_EXCLUDE_AMAZON_IN_STOCK: "true",
        AppSetting.KEY_DEFAULT_MIN_SALES_RANK_DROPS_90: "10",
        AppSetting.KEY_CSV_EXPORT_DIR: "exports",
    }


def test_validate_settings_input_accepts_valid_values():
    errors = validate_settings_input(_valid_values())
    assert errors == {}


def test_validate_settings_input_rejects_non_numeric_min_price():
    values = _valid_values()
    values[AppSetting.KEY_DEFAULT_MIN_PRICE] = "abc"

    errors = validate_settings_input(values)

    assert AppSetting.KEY_DEFAULT_MIN_PRICE in errors


def test_validate_settings_input_rejects_max_price_less_than_min_price():
    values = _valid_values()
    values[AppSetting.KEY_DEFAULT_MIN_PRICE] = "2000"
    values[AppSetting.KEY_DEFAULT_MAX_PRICE] = "1000"

    errors = validate_settings_input(values)

    assert AppSetting.KEY_DEFAULT_MAX_PRICE in errors


def test_validate_settings_input_rejects_offer_count_range_violation():
    values = _valid_values()
    values[AppSetting.KEY_DEFAULT_MIN_OFFER_COUNT] = "8"
    values[AppSetting.KEY_DEFAULT_MAX_OFFER_COUNT] = "3"

    errors = validate_settings_input(values)

    assert AppSetting.KEY_DEFAULT_MAX_OFFER_COUNT in errors


def test_validate_settings_input_rejects_negative_sales_rank_drops():
    values = _valid_values()
    values[AppSetting.KEY_DEFAULT_MIN_SALES_RANK_DROPS_90] = "-1"

    errors = validate_settings_input(values)

    assert AppSetting.KEY_DEFAULT_MIN_SALES_RANK_DROPS_90 in errors


def test_validate_settings_input_rejects_empty_csv_dir():
    values = _valid_values()
    values[AppSetting.KEY_CSV_EXPORT_DIR] = ""

    errors = validate_settings_input(values)

    assert AppSetting.KEY_CSV_EXPORT_DIR in errors


def test_validate_settings_input_rejects_parent_path_in_csv_dir():
    values = _valid_values()
    values[AppSetting.KEY_CSV_EXPORT_DIR] = "../exports"

    errors = validate_settings_input(values)

    assert AppSetting.KEY_CSV_EXPORT_DIR in errors
