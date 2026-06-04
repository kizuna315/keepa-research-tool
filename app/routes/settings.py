from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from app.models import AppSetting
from app.services.error_utils import (
    build_user_friendly_error_message,
    log_safe,
    sanitize_error_message,
)
from app.services.settings_service import SettingsService
from app.services.settings_validator import validate_settings_input


settings_bp = Blueprint("settings", __name__, url_prefix="/settings")


def _has_keepa_api_key() -> bool:
    return SettingsService.get(AppSetting.KEY_KEEPA_API_KEY) not in (None, "")


def _build_values_from_form() -> dict[str, str | None]:
    return {
        AppSetting.KEY_DEFAULT_DOMAIN_ID: request.form.get(
            AppSetting.KEY_DEFAULT_DOMAIN_ID,
            "",
        ).strip(),
        AppSetting.KEY_DEFAULT_MIN_PRICE: request.form.get(
            AppSetting.KEY_DEFAULT_MIN_PRICE,
            "",
        ).strip(),
        AppSetting.KEY_DEFAULT_MAX_PRICE: request.form.get(
            AppSetting.KEY_DEFAULT_MAX_PRICE,
            "",
        ).strip(),
        AppSetting.KEY_DEFAULT_MIN_OFFER_COUNT: request.form.get(
            AppSetting.KEY_DEFAULT_MIN_OFFER_COUNT,
            "",
        ).strip(),
        AppSetting.KEY_DEFAULT_MAX_OFFER_COUNT: request.form.get(
            AppSetting.KEY_DEFAULT_MAX_OFFER_COUNT,
            "",
        ).strip(),
        AppSetting.KEY_EXCLUDE_AMAZON_IN_STOCK: (
            "true"
            if request.form.get(AppSetting.KEY_EXCLUDE_AMAZON_IN_STOCK) == "on"
            else "false"
        ),
        AppSetting.KEY_DEFAULT_MIN_SALES_RANK_DROPS_90: request.form.get(
            AppSetting.KEY_DEFAULT_MIN_SALES_RANK_DROPS_90,
            "",
        ).strip(),
        AppSetting.KEY_CSV_EXPORT_DIR: request.form.get(
            AppSetting.KEY_CSV_EXPORT_DIR,
            "",
        ).strip(),
    }


@settings_bp.get("/")
def settings_form():
    settings = SettingsService.get_all_known_settings(include_secrets=False)
    return render_template(
        "settings.html",
        settings=settings,
        errors={},
        has_keepa_api_key=_has_keepa_api_key(),
    )


@settings_bp.post("/")
def save_settings():
    values = _build_values_from_form()
    api_key = request.form.get(AppSetting.KEY_KEEPA_API_KEY, "").strip()

    errors = validate_settings_input(values)
    has_keepa_api_key = _has_keepa_api_key()

    if errors:
        flash("入力内容を確認してください。", "danger")
        settings_for_form = SettingsService.get_all_known_settings(include_secrets=False)
        settings_for_form.update(values)
        return (
            render_template(
                "settings.html",
                settings=settings_for_form,
                errors=errors,
                has_keepa_api_key=has_keepa_api_key,
            ),
            400,
        )

    if api_key:
        values[AppSetting.KEY_KEEPA_API_KEY] = api_key

    try:
        SettingsService.set_many(values)
    except Exception as exc:
        log_safe(
            current_app.logger,
            "error",
            "Settings save failed",
            error=sanitize_error_message(exc),
            keys=list(values.keys()),
        )
        flash(build_user_friendly_error_message("db_save_failed"), "danger")
        settings_for_form = SettingsService.get_all_known_settings(include_secrets=False)
        settings_for_form.update(
            {
                key: value
                for key, value in values.items()
                if key != AppSetting.KEY_KEEPA_API_KEY
            }
        )
        return (
            render_template(
                "settings.html",
                settings=settings_for_form,
                errors={},
                has_keepa_api_key=has_keepa_api_key,
            ),
            500,
        )

    flash("設定を保存しました。", "success")
    return redirect(url_for("settings.settings_form"))
