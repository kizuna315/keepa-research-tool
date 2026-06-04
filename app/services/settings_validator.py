from __future__ import annotations

from app.models import AppSetting


def _parse_int(
    values: dict[str, str | None],
    key: str,
    label: str,
    min_value: int,
    errors: dict[str, str],
) -> int | None:
    raw_value = (values.get(key) or "").strip()
    if raw_value == "":
        errors[key] = f"{label}は必須です。"
        return None

    try:
        parsed = int(raw_value)
    except ValueError:
        errors[key] = f"{label}は{min_value}以上の整数で入力してください。"
        return None

    if parsed < min_value:
        errors[key] = f"{label}は{min_value}以上の整数で入力してください。"
        return None

    return parsed


def validate_settings_input(values: dict[str, str | None]) -> dict[str, str]:
    errors: dict[str, str] = {}

    domain_id = _parse_int(
        values,
        AppSetting.KEY_DEFAULT_DOMAIN_ID,
        "デフォルトAmazonドメイン",
        1,
        errors,
    )
    min_price = _parse_int(
        values,
        AppSetting.KEY_DEFAULT_MIN_PRICE,
        "デフォルト価格下限",
        0,
        errors,
    )
    max_price = _parse_int(
        values,
        AppSetting.KEY_DEFAULT_MAX_PRICE,
        "デフォルト価格上限",
        1,
        errors,
    )
    min_offer_count = _parse_int(
        values,
        AppSetting.KEY_DEFAULT_MIN_OFFER_COUNT,
        "デフォルト出品者数下限",
        0,
        errors,
    )
    max_offer_count = _parse_int(
        values,
        AppSetting.KEY_DEFAULT_MAX_OFFER_COUNT,
        "デフォルト出品者数上限",
        1,
        errors,
    )
    min_sales_rank_drops = _parse_int(
        values,
        AppSetting.KEY_DEFAULT_MIN_SALES_RANK_DROPS_90,
        "ランキング変動回数の最低条件",
        0,
        errors,
    )

    exclude_amazon = values.get(AppSetting.KEY_EXCLUDE_AMAZON_IN_STOCK)
    if exclude_amazon not in {"true", "false"}:
        errors[AppSetting.KEY_EXCLUDE_AMAZON_IN_STOCK] = (
            "Amazon本体あり商品の扱いはtrueまたはfalseで指定してください。"
        )

    csv_export_dir = (values.get(AppSetting.KEY_CSV_EXPORT_DIR) or "").strip()
    if csv_export_dir == "":
        errors[AppSetting.KEY_CSV_EXPORT_DIR] = "CSV出力先は必須です。"
    elif ".." in csv_export_dir:
        errors[AppSetting.KEY_CSV_EXPORT_DIR] = "CSV出力先に「..」は使用できません。"

    if (
        min_price is not None
        and max_price is not None
        and AppSetting.KEY_DEFAULT_MAX_PRICE not in errors
        and max_price < min_price
    ):
        errors[AppSetting.KEY_DEFAULT_MAX_PRICE] = (
            "デフォルト価格上限は価格下限以上にしてください。"
        )

    if (
        min_offer_count is not None
        and max_offer_count is not None
        and AppSetting.KEY_DEFAULT_MAX_OFFER_COUNT not in errors
        and max_offer_count < min_offer_count
    ):
        errors[AppSetting.KEY_DEFAULT_MAX_OFFER_COUNT] = (
            "出品者数上限は出品者数下限以上にしてください。"
        )

    _ = domain_id
    _ = min_sales_rank_drops

    return errors
