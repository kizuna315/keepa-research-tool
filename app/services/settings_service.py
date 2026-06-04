from __future__ import annotations

from app.extensions import db
from app.models import AppSetting
from app.services.settings_defaults import (
    SECRET_SETTING_KEYS,
    get_default_setting,
)


class SettingsService:
    @staticmethod
    def get(key: str, default: str | None = None) -> str | None:
        setting = AppSetting.query.filter_by(key=key).first()
        if setting is not None:
            return setting.value
        return get_default_setting(key, default)

    @staticmethod
    def set(key: str, value: str | None) -> AppSetting:
        if key is None or not key.strip():
            raise ValueError("Setting key must not be empty.")

        setting = AppSetting.query.filter_by(key=key).first()
        if setting is None:
            setting = AppSetting(key=key, value=value)
            db.session.add(setting)
        else:
            setting.value = value

        db.session.commit()
        return setting

    @staticmethod
    def get_many(keys: list[str]) -> dict[str, str | None]:
        return {key: SettingsService.get(key) for key in keys}

    @staticmethod
    def set_many(values: dict[str, str | None]) -> dict[str, AppSetting]:
        result: dict[str, AppSetting] = {}
        try:
            for key, value in values.items():
                if key is None or not key.strip():
                    raise ValueError("Setting key must not be empty.")

                setting = AppSetting.query.filter_by(key=key).first()
                if setting is None:
                    setting = AppSetting(key=key, value=value)
                    db.session.add(setting)
                else:
                    setting.value = value
                result[key] = setting

            db.session.commit()
            return result
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def get_all_known_settings(include_secrets: bool = False) -> dict[str, str | None]:
        result: dict[str, str | None] = {}
        for key in sorted(AppSetting.KNOWN_KEYS):
            if key in SECRET_SETTING_KEYS and not include_secrets:
                result[key] = None
            else:
                result[key] = SettingsService.get(key)
        return result
