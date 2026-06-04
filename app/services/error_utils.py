import json
import re
from copy import deepcopy
from typing import Any


MASKED_VALUE = "[REDACTED]"

DEFAULT_FALLBACK_MESSAGE = "処理中にエラーが発生しました。"

DEFAULT_SENSITIVE_KEYS = {
    "key",
    "api_key",
    "apikey",
    "apiKey",
    "accessKey",
    "keepa_api_key",
    "token",
    "authorization",
    "password",
    "secret",
}

_SENSITIVE_KEY_PATTERN = (
    r"(?:keepa_api_key|accessKey|apiKey|api_key|apikey|authorization|token|password|secret|key)"
)

_QUERY_OR_ASSIGNMENT_RE = re.compile(
    rf"(?P<prefix>(?:[?&\s]|^){{1}}{_SENSITIVE_KEY_PATTERN}\s*=\s*)(?P<value>[^&\s,;]+)",
    re.IGNORECASE,
)
_JSON_DOUBLE_QUOTE_RE = re.compile(
    rf'(?P<prefix>"{_SENSITIVE_KEY_PATTERN}"\s*:\s*")(?P<value>[^"]*)(")',
    re.IGNORECASE,
)
_JSON_SINGLE_QUOTE_RE = re.compile(
    rf"(?P<prefix>'{_SENSITIVE_KEY_PATTERN}'\s*:\s*')(?P<value>[^']*)(')",
    re.IGNORECASE,
)
_HEADER_RE = re.compile(
    rf"(?P<prefix>{_SENSITIVE_KEY_PATTERN}\s*:\s*)(?P<value>[^\n\r,;]+)",
    re.IGNORECASE,
)


def _safe_string(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        if isinstance(value, (dict, list, tuple, set)):
            return json.dumps(_to_jsonable(value), ensure_ascii=False)
    except (TypeError, ValueError):
        pass
    try:
        return str(value)
    except Exception:
        return ""


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    return value


def mask_sensitive_text(value: object) -> str:
    """Return text with API keys and similar secret values redacted."""

    text = _safe_string(value)
    if not text:
        return ""

    text = _QUERY_OR_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group('prefix')}{MASKED_VALUE}",
        text,
    )
    text = _JSON_DOUBLE_QUOTE_RE.sub(
        lambda match: f"{match.group('prefix')}{MASKED_VALUE}{match.group(3)}",
        text,
    )
    text = _JSON_SINGLE_QUOTE_RE.sub(
        lambda match: f"{match.group('prefix')}{MASKED_VALUE}{match.group(3)}",
        text,
    )
    text = _HEADER_RE.sub(
        lambda match: f"{match.group('prefix')}{MASKED_VALUE}",
        text,
    )
    return text


def sanitize_error_message(
    error: object,
    fallback: str = DEFAULT_FALLBACK_MESSAGE,
) -> str:
    """Convert an arbitrary error object into a safe message for UI/DB/log use."""

    message = mask_sensitive_text(error)
    if not message.strip():
        return fallback
    return message


def sanitize_dict(
    data: dict,
    sensitive_keys: set[str] | None = None,
) -> dict:
    """Deep-copy a dict and redact sensitive values without mutating the original."""

    keys = sensitive_keys or DEFAULT_SENSITIVE_KEYS
    normalized_keys = {key.lower() for key in keys}

    def sanitize_value(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: (
                    MASKED_VALUE
                    if str(key).lower() in normalized_keys
                    else sanitize_value(item)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [sanitize_value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(sanitize_value(item) for item in value)
        if isinstance(value, str):
            return mask_sensitive_text(value)
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        return mask_sensitive_text(value)

    return sanitize_value(deepcopy(data))


def build_user_friendly_error_message(
    error_type: str,
    detail: object | None = None,
) -> str:
    """Build a short Japanese message safe enough for screen display."""

    messages = {
        "missing_api_key": "Keepa API Keyが未設定です。設定画面でAPI Keyを保存してください。",
        "invalid_api_key": "Keepa API Keyが正しくない可能性があります。設定画面で確認してください。",
        "token_insufficient": "Keepa APIのトークンが不足しています。時間をおいて再実行してください。",
        "keepa_connection_failed": "Keepa APIへの接続に失敗しました。通信環境またはAPI状態を確認してください。",
        "keepa_api_failed": "Keepa APIでエラーが発生しました。",
        "db_save_failed": "データベース保存中にエラーが発生しました。",
        "csv_export_failed": "CSV出力中にエラーが発生しました。",
        "data_insufficient": "商品データの一部が不足しているため、判定をunknownとして扱います。",
        "unknown": DEFAULT_FALLBACK_MESSAGE,
    }
    message = messages.get(error_type, messages["unknown"])

    if detail is None:
        return message

    safe_detail = sanitize_error_message(detail, fallback="")
    if not safe_detail:
        return message

    if len(safe_detail) > 120:
        safe_detail = f"{safe_detail[:117]}..."
    return f"{message} 詳細: {safe_detail}"


def log_safe(logger, level: str, message: str, **context) -> None:
    """Log a sanitized message and sanitized context."""

    safe_message = mask_sensitive_text(message)
    safe_context = sanitize_dict(context) if context else {}
    safe_level = level if level in {"debug", "info", "warning", "error", "exception"} else "info"
    log_method = getattr(logger, safe_level, logger.info)

    if safe_context:
        log_method("%s | context=%s", safe_message, safe_context)
    else:
        log_method("%s", safe_message)
