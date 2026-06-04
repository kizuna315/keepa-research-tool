import logging

from app.services.error_utils import (
    MASKED_VALUE,
    build_user_friendly_error_message,
    log_safe,
    mask_sensitive_text,
    sanitize_dict,
    sanitize_error_message,
)


def test_mask_sensitive_text_masks_query_key():
    text = "https://api.keepa.com/product?key=abc123&domain=5"

    result = mask_sensitive_text(text)

    assert "abc123" not in result
    assert f"key={MASKED_VALUE}" in result
    assert "domain=5" in result


def test_mask_sensitive_text_masks_json_like_api_key():
    text = '{"apiKey": "abc123", "status": 401}'

    result = mask_sensitive_text(text)

    assert "abc123" not in result
    assert f'"apiKey": "{MASKED_VALUE}"' in result
    assert '"status": 401' in result


def test_mask_sensitive_text_masks_authorization_header():
    text = "Authorization: Bearer abc123"

    result = mask_sensitive_text(text)

    assert "Bearer abc123" not in result
    assert f"Authorization: {MASKED_VALUE}" in result


def test_sanitize_error_message_handles_exception():
    error = RuntimeError("Keepa failed api_key=abc123")

    result = sanitize_error_message(error)

    assert "abc123" not in result
    assert MASKED_VALUE in result
    assert "Keepa failed" in result


def test_sanitize_error_message_handles_none():
    assert sanitize_error_message(None) == "処理中にエラーが発生しました。"


def test_sanitize_dict_masks_nested_sensitive_values():
    data = {
        "status": 401,
        "key": "abc123",
        "nested": {
            "apiKey": "def456",
            "url": "https://api.keepa.com/token?key=ghi789",
        },
        "items": [
            {"accessKey": "jkl000"},
            "Authorization: Bearer mno111",
        ],
    }

    result = sanitize_dict(data)

    result_text = str(result)
    assert "abc123" not in result_text
    assert "def456" not in result_text
    assert "ghi789" not in result_text
    assert "jkl000" not in result_text
    assert "mno111" not in result_text
    assert result["key"] == MASKED_VALUE
    assert result["nested"]["apiKey"] == MASKED_VALUE
    assert result["nested"]["url"] == f"https://api.keepa.com/token?key={MASKED_VALUE}"
    assert result["items"][0]["accessKey"] == MASKED_VALUE
    assert MASKED_VALUE in result["items"][1]


def test_sanitize_dict_does_not_mutate_original():
    data = {"nested": {"token": "abc123"}}

    result = sanitize_dict(data)

    assert result["nested"]["token"] == MASKED_VALUE
    assert data["nested"]["token"] == "abc123"


def test_sanitize_dict_masks_secret_inside_exception_object():
    data = {
        "detail": RuntimeError(
            "request failed with url /product?asin=B0TEST1234&key=abc123&domain=5"
        )
    }

    result = sanitize_dict(data)

    assert "abc123" not in str(result)
    assert f"key={MASKED_VALUE}" in result["detail"]
    assert "asin=B0TEST1234" in result["detail"]


def test_build_user_friendly_error_message_known_types():
    expected_fragments = {
        "missing_api_key": "Keepa API Keyが未設定です。",
        "invalid_api_key": "Keepa API Keyが正しくない可能性があります。",
        "token_insufficient": "Keepa APIのトークンが不足しています。",
        "keepa_connection_failed": "Keepa APIへの接続に失敗しました。",
        "keepa_api_failed": "Keepa APIでエラーが発生しました。",
        "db_save_failed": "データベース保存中にエラーが発生しました。",
        "csv_export_failed": "CSV出力中にエラーが発生しました。",
        "data_insufficient": "商品データの一部が不足しているため",
        "unknown": "処理中にエラーが発生しました。",
        "not_supported": "処理中にエラーが発生しました。",
    }

    for error_type, fragment in expected_fragments.items():
        assert fragment in build_user_friendly_error_message(error_type)


def test_build_user_friendly_error_message_masks_detail():
    result = build_user_friendly_error_message(
        "keepa_api_failed",
        "request failed key=abc123",
    )

    assert "Keepa APIでエラーが発生しました。" in result
    assert "abc123" not in result
    assert MASKED_VALUE in result


def test_log_safe_does_not_log_secret(caplog):
    logger = logging.getLogger("test_log_safe_does_not_log_secret")

    with caplog.at_level(logging.ERROR, logger=logger.name):
        log_safe(
            logger,
            "error",
            "Keepa API failed key=abc123",
            url="https://api.keepa.com/product?key=def456&domain=5",
            status=401,
        )

    output = "\n".join(record.getMessage() for record in caplog.records)
    assert "abc123" not in output
    assert "def456" not in output
    assert MASKED_VALUE in output
    assert "status" in output
