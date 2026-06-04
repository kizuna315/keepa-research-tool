from typing import Optional

from app.models import AppSetting

DEFAULT_SETTINGS = {
    AppSetting.KEY_DEFAULT_DOMAIN_ID: "5",
    AppSetting.KEY_DEFAULT_MIN_PRICE: "1500",
    AppSetting.KEY_DEFAULT_MAX_PRICE: "10000",
    AppSetting.KEY_DEFAULT_MIN_OFFER_COUNT: "3",
    AppSetting.KEY_DEFAULT_MAX_OFFER_COUNT: "15",
    AppSetting.KEY_EXCLUDE_AMAZON_IN_STOCK: "true",
    AppSetting.KEY_DEFAULT_MIN_SALES_RANK_DROPS_90: "10",
    AppSetting.KEY_CSV_EXPORT_DIR: "exports",
}

SECRET_SETTING_KEYS = {
    AppSetting.KEY_KEEPA_API_KEY,
}


def get_default_setting(key: str, fallback: Optional[str] = None) -> Optional[str]:
    return DEFAULT_SETTINGS.get(key, fallback)
