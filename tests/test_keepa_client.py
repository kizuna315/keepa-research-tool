from __future__ import annotations

import json

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import RequestException, Timeout

from app.models import AppSetting
from app.services.keepa_client import (
    KeepaApiError,
    KeepaApiKeyMissingError,
    KeepaClient,
    KeepaTokenError,
)
from app.services.settings_defaults import DEFAULT_SETTINGS


class DummySettingsService:
    def __init__(self, values: dict[str, str | None]):
        self._values = values

    def get(self, key: str, default=None):
        return self._values.get(key, default)


class DummyResponse:
    def __init__(self, status_code: int = 200, payload=None, json_error: Exception | None = None):
        self.status_code = status_code
        self._payload = {} if payload is None else payload
        self._json_error = json_error

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._payload


def make_client(values: dict[str, str | None], timeout: int = 30) -> KeepaClient:
    return KeepaClient(settings_service=DummySettingsService(values), timeout=timeout)


def test_get_api_key_raises_when_missing():
    client = make_client({})
    with pytest.raises(KeepaApiKeyMissingError):
        client._get_api_key()


def test_get_api_key_raises_when_blank():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "   "})
    with pytest.raises(KeepaApiKeyMissingError):
        client._get_api_key()


def test_get_domain_id_uses_default_when_not_set():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "test-key"})
    assert client._get_domain_id() == int(DEFAULT_SETTINGS[AppSetting.KEY_DEFAULT_DOMAIN_ID])


def test_get_domain_id_raises_for_invalid_value():
    client = make_client(
        {
            AppSetting.KEY_KEEPA_API_KEY: "test-key",
            AppSetting.KEY_DEFAULT_DOMAIN_ID: "invalid",
        }
    )
    with pytest.raises(KeepaApiError):
        client._get_domain_id()


def test_request_adds_key_and_domain_params(monkeypatch):
    captured = {}
    client = make_client(
        {
            AppSetting.KEY_KEEPA_API_KEY: "secret-key",
            AppSetting.KEY_DEFAULT_DOMAIN_ID: "5",
        },
        timeout=12,
    )

    def fake_get(url, params, timeout):
        captured["url"] = url
        captured["params"] = params
        captured["timeout"] = timeout
        return DummyResponse(status_code=200, payload={"ok": True, "tokensLeft": 10})

    monkeypatch.setattr("app.services.keepa_client.requests.get", fake_get)

    payload = client._request("/product", {"asin": "B000000000"})

    assert payload["ok"] is True
    assert captured["url"] == "https://api.keepa.com/product"
    assert captured["params"]["asin"] == "B000000000"
    assert captured["params"]["key"] == "secret-key"
    assert captured["params"]["domain"] == 5
    assert captured["timeout"] == 12


def test_request_wraps_requests_exception(monkeypatch):
    client = make_client(
        {
            AppSetting.KEY_KEEPA_API_KEY: "super-secret-key",
            AppSetting.KEY_DEFAULT_DOMAIN_ID: "5",
        }
    )

    def fake_get(url, params, timeout):
        raise RequestException("failed key=super-secret-key")

    monkeypatch.setattr("app.services.keepa_client.requests.get", fake_get)

    with pytest.raises(KeepaApiError) as exc_info:
        client._request("/product")
    assert "super-secret-key" not in str(exc_info.value)


def test_request_raises_on_http_500(monkeypatch):
    client = make_client(
        {
            AppSetting.KEY_KEEPA_API_KEY: "test-key",
            AppSetting.KEY_DEFAULT_DOMAIN_ID: "5",
        }
    )

    def fake_get(url, params, timeout):
        return DummyResponse(status_code=500, payload={"message": "error"})

    monkeypatch.setattr("app.services.keepa_client.requests.get", fake_get)

    with pytest.raises(KeepaApiError):
        client._request("/product")


def test_request_raises_when_response_has_error(monkeypatch):
    client = make_client(
        {
            AppSetting.KEY_KEEPA_API_KEY: "test-key",
            AppSetting.KEY_DEFAULT_DOMAIN_ID: "5",
        }
    )

    def fake_get(url, params, timeout):
        return DummyResponse(status_code=200, payload={"error": "bad request"})

    monkeypatch.setattr("app.services.keepa_client.requests.get", fake_get)

    with pytest.raises(KeepaApiError):
        client._request("/product")


def test_request_raises_token_error_when_tokens_depleted(monkeypatch):
    client = make_client(
        {
            AppSetting.KEY_KEEPA_API_KEY: "test-key",
            AppSetting.KEY_DEFAULT_DOMAIN_ID: "5",
        }
    )

    def fake_get(url, params, timeout):
        return DummyResponse(status_code=200, payload={"tokensLeft": 0})

    monkeypatch.setattr("app.services.keepa_client.requests.get", fake_get)

    with pytest.raises(KeepaTokenError):
        client._request("/product")


def test_api_key_value_is_not_exposed_in_missing_key_error():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "  "})
    with pytest.raises(KeepaApiKeyMissingError) as exc_info:
        client._get_api_key()
    assert "keepa_api_key" not in str(exc_info.value).lower()


def test_get_token_status_maps_tokens_left_and_optional_fields(monkeypatch):
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "top-secret-key"})
    raw_payload = {
        "tokensLeft": 123,
        "refillRate": 20,
        "refillIn": 30000,
        "tokenFlowReduction": 0.0,
        "tokensConsumed": 2,
    }

    def fake_request(path, params=None):
        assert path == "/token"
        assert params == {}
        return raw_payload

    monkeypatch.setattr(client, "_request", fake_request)

    result = client.get_token_status()

    assert result["tokens_left"] == 123
    assert result["refill_rate"] == 20
    assert result["refill_in"] == 30000
    assert result["token_flow_reduction"] == 0.0
    assert result["tokens_consumed"] == 2
    assert result["raw"] == raw_payload


def test_get_token_status_allows_missing_optional_fields(monkeypatch):
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "top-secret-key"})

    def fake_request(path, params=None):
        return {"tokensLeft": 10}

    monkeypatch.setattr(client, "_request", fake_request)

    result = client.get_token_status()

    assert result["tokens_left"] == 10
    assert result["refill_rate"] is None
    assert result["refill_in"] is None
    assert result["token_flow_reduction"] is None
    assert result["tokens_consumed"] is None


def test_get_token_status_raises_when_tokens_left_missing(monkeypatch):
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "ultra-secret-key"})

    def fake_request(path, params=None):
        return {"refillRate": 10}

    monkeypatch.setattr(client, "_request", fake_request)

    with pytest.raises(KeepaApiError) as exc_info:
        client.get_token_status()
    assert "ultra-secret-key" not in str(exc_info.value)


def test_get_token_status_raises_token_error_when_tokens_depleted(monkeypatch):
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "top-secret-key"})

    def fake_request(path, params=None):
        return {"tokensLeft": 0}

    monkeypatch.setattr(client, "_request", fake_request)

    with pytest.raises(KeepaTokenError):
        client.get_token_status()


def test_get_token_status_allow_depleted_returns_refill_information(monkeypatch):
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "top-secret-key"})
    called = {}

    def fake_request(path, params=None, raise_on_empty_tokens=True):
        called["path"] = path
        called["raise_on_empty_tokens"] = raise_on_empty_tokens
        return {"tokensLeft": 0, "refillRate": 20, "refillIn": 95000}

    monkeypatch.setattr(client, "_request", fake_request)

    result = client.get_token_status(allow_depleted=True)

    assert called["path"] == "/token"
    assert called["raise_on_empty_tokens"] is False
    assert result["tokens_left"] == 0
    assert result["refill_rate"] == 20
    assert result["refill_in"] == 95000


def test_get_token_status_uses_token_path(monkeypatch):
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "top-secret-key"})
    called = {}

    def fake_request(path, params=None):
        called["path"] = path
        called["params"] = params
        return {"tokensLeft": 5}

    monkeypatch.setattr(client, "_request", fake_request)

    client.get_token_status()

    assert called["path"] == "/token"
    assert called["params"] == {}


def test_get_token_status_return_value_does_not_include_api_key(monkeypatch):
    secret = "my-real-secret-key"
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: secret})

    def fake_request(path, params=None):
        return {"tokensLeft": 7, "refillRate": 1}

    monkeypatch.setattr(client, "_request", fake_request)
    result = client.get_token_status()

    assert secret not in str(result)


def test_get_products_by_asins_calls_product_path_with_expected_params(monkeypatch):
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    called = {}

    def fake_request(path, params=None):
        called["path"] = path
        called["params"] = params
        return {"products": [{"asin": "B000000001"}]}

    monkeypatch.setattr(client, "_request", fake_request)
    result = client.get_products_by_asins(["b000000001", " B000000002 "])

    assert called["path"] == "/product"
    assert called["params"]["asin"] == "B000000001,B000000002"
    assert called["params"]["stats"] == 90
    assert called["params"]["offers"] == 20
    assert result == [{"asin": "B000000001"}]


def test_get_products_by_asins_trims_uppercases_and_deduplicates():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    cleaned = client._clean_asins(
        [
            " b000000001 ",
            "B000000001",
            "b000000002",
            "",
            "   ",
            None,
            "b000000002",
            "B000000003",
        ]
    )
    assert cleaned == ["B000000001", "B000000002", "B000000003"]


def test_get_products_by_asins_raises_when_asins_empty():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    with pytest.raises(KeepaApiError):
        client.get_products_by_asins([])


def test_get_products_by_asins_raises_when_asins_all_invalid():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "real-secret-key"})
    with pytest.raises(KeepaApiError) as exc_info:
        client.get_products_by_asins(["", "   ", None])
    assert "real-secret-key" not in str(exc_info.value)


def test_get_products_by_asins_raises_when_products_missing(monkeypatch):
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})

    def fake_request(path, params=None):
        return {"ok": True}

    monkeypatch.setattr(client, "_request", fake_request)

    with pytest.raises(KeepaApiError):
        client.get_products_by_asins(["B000000001"])


def test_get_products_by_asins_raises_when_products_not_list(monkeypatch):
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})

    def fake_request(path, params=None):
        return {"products": {"asin": "B000000001"}}

    monkeypatch.setattr(client, "_request", fake_request)

    with pytest.raises(KeepaApiError):
        client.get_products_by_asins(["B000000001"])


def test_get_products_by_asins_returns_empty_list(monkeypatch):
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})

    def fake_request(path, params=None):
        return {"products": []}

    monkeypatch.setattr(client, "_request", fake_request)

    assert client.get_products_by_asins(["B000000001"]) == []


def test_get_products_by_asins_returns_products_list_as_is(monkeypatch):
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    products = [{"asin": "B000000001"}, {"asin": "B000000002"}]

    def fake_request(path, params=None):
        return {"products": products}

    monkeypatch.setattr(client, "_request", fake_request)
    result = client.get_products_by_asins(["B000000001", "B000000002"])
    assert result is products


def test_normalize_product_returns_basic_fields():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    raw = {
        "asin": "b000000001",
        "title": "Sample Product",
        "brand": "BrandX",
        "manufacturer": "MakerY",
    }
    result = client.normalize_product(raw)
    assert result["asin"] == "B000000001"
    assert result["title"] == "Sample Product"
    assert result["brand"] == "BrandX"
    assert result["manufacturer"] == "MakerY"


def test_normalize_product_raises_when_raw_is_not_dict():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    with pytest.raises(KeepaApiError):
        client.normalize_product(["not-dict"])


def test_normalize_product_raises_when_asin_missing():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    with pytest.raises(KeepaApiError):
        client.normalize_product({"title": "Sample Product"})


def test_normalize_product_raises_when_title_missing():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    with pytest.raises(KeepaApiError):
        client.normalize_product({"asin": "B000000001"})


def test_normalize_product_sets_jan_and_ean_from_ean_list():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    raw = {"asin": "B000000001", "title": "Sample Product", "eanList": ["4901234567890"]}
    result = client.normalize_product(raw)
    assert result["jan"] == "4901234567890"
    assert result["ean"] == "4901234567890"


def test_normalize_product_extracts_category_from_last_category_tree():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    raw = {
        "asin": "B000000001",
        "title": "Sample Product",
        "categoryTree": [
            {"catId": 1, "name": "Parent"},
            {"catId": 2, "name": "Child"},
        ],
    }
    result = client.normalize_product(raw)
    assert result["category_id"] == "2"
    assert result["category_name"] == "Child"


def test_normalize_product_uses_root_category_when_present():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    raw = {
        "asin": "B000000001",
        "title": "Sample Product",
        "rootCategory": 999,
        "categoryTree": [{"catId": 2, "name": "Child"}],
    }
    result = client.normalize_product(raw)
    assert result["category_id"] == "999"


def test_normalize_product_builds_image_url_from_images_csv():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    raw = {
        "asin": "B000000001",
        "title": "Sample Product",
        "imagesCSV": "abc123.jpg,second.jpg",
    }
    result = client.normalize_product(raw)
    assert (
        result["image_url"]
        == "https://images-na.ssl-images-amazon.com/images/I/abc123.jpg"
    )


def test_normalize_product_preserves_http_image_url():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    raw = {
        "asin": "B000000001",
        "title": "Sample Product",
        "imagesCSV": "https://example.com/image.jpg",
    }
    result = client.normalize_product(raw)
    assert result["image_url"] == "https://example.com/image.jpg"


def test_normalize_product_builds_amazon_and_keepa_urls():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    raw = {"asin": "b000000001", "title": "Sample Product"}
    result = client.normalize_product(raw)
    assert result["amazon_url"] == "https://www.amazon.co.jp/dp/B000000001"
    assert result["keepa_url"] == "https://keepa.com/#!product/5-B000000001"


def test_normalize_product_reads_prices_from_stats():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    raw = {
        "asin": "B000000001",
        "title": "Sample Product",
        "stats": {
            "current": [0, 3200, 0, 12345],
            "avg30": [0, 3000, 0, 11000],
            "avg90": [0, 3100, 0, 11500],
            "min": [0, 2800],
            "max": [0, 3500],
            "salesRankDrops90": 18,
        },
    }
    result = client.normalize_product(raw)
    assert result["current_price"] == 3200
    assert result["avg_price_30"] == 3000
    assert result["avg_price_90"] == 3100
    assert result["lowest_price_90"] == 2800
    assert result["highest_price_90"] == 3500
    assert result["sales_rank_drops_90"] == 18
    assert result["sales_rank_current"] == 12345


def test_normalize_product_reads_new_offer_count():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    raw = {"asin": "B000000001", "title": "Sample Product", "newOfferCount": 7}
    result = client.normalize_product(raw)
    assert result["new_offer_count"] == 7


def test_normalize_product_converts_rating_from_45_to_4_5():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    raw = {"asin": "B000000001", "title": "Sample Product", "rating": 45}
    result = client.normalize_product(raw)
    assert result["rating"] == 4.5


def test_normalize_product_sets_missing_values_to_none():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    raw = {"asin": "B000000001", "title": "Sample Product"}
    result = client.normalize_product(raw)
    assert result["current_price"] is None
    assert result["avg_price_30"] is None
    assert result["avg_price_90"] is None
    assert result["sales_rank_drops_90"] is None
    assert result["review_count"] is None
    assert result["image_url"] is None


def test_normalize_product_raw_keepa_json_is_saved():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    raw = {"asin": "B000000001", "title": "Sample Product", "brand": "BrandX"}
    result = client.normalize_product(raw)
    payload = json.loads(result["raw_keepa_json"])
    assert payload["asin"] == "B000000001"
    assert payload["title"] == "Sample Product"
    assert payload["brand"] == "BrandX"


def test_normalize_product_masks_sensitive_keys_in_raw_json():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    raw = {
        "asin": "B000000001",
        "title": "Sample Product",
        "key": "actual-key",
        "apiKey": "actual-api-key",
        "nested": {"accessKey": "nested-secret"},
    }
    result = client.normalize_product(raw)
    payload = json.loads(result["raw_keepa_json"])
    assert payload["key"] == "[REDACTED]"
    assert payload["apiKey"] == "[REDACTED]"
    assert payload["nested"]["accessKey"] == "[REDACTED]"
    assert "actual-key" not in result["raw_keepa_json"]
    assert "actual-api-key" not in result["raw_keepa_json"]
    assert "nested-secret" not in result["raw_keepa_json"]


def test_normalize_product_includes_product_model_compatible_keys():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    raw = {
        "asin": "b0test1234",
        "title": "テスト商品",
        "brand": "Test Brand",
        "stats": {
            "current": [None, 1980],
            "avg30": [None, 2000],
            "avg90": [None, 2100],
            "salesRankDrops90": 12,
        },
        "newOfferCount": 5,
        "availabilityAmazon": -1,
    }
    result = client.normalize_product(raw)

    expected_keys = {
        "asin",
        "jan",
        "ean",
        "title",
        "brand",
        "manufacturer",
        "category_id",
        "category_name",
        "image_url",
        "amazon_url",
        "keepa_url",
        "current_price",
        "avg_price_30",
        "avg_price_90",
        "lowest_price_90",
        "highest_price_90",
        "sales_rank_current",
        "sales_rank_avg_30",
        "sales_rank_avg_90",
        "sales_rank_drops_30",
        "sales_rank_drops_90",
        "new_offer_count",
        "used_offer_count",
        "fba_offer_count",
        "amazon_in_stock",
        "amazon_was_in_stock_90",
        "review_count",
        "rating",
        "raw_keepa_json",
    }
    assert expected_keys.issubset(set(result.keys()))


def test_products_by_asins_output_can_be_normalized_and_raw_json_is_loadable(monkeypatch):
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    raw_product = {
        "asin": "b0test1234",
        "title": "テスト商品",
        "brand": "Test Brand",
        "stats": {
            "current": [None, 1980],
            "avg30": [None, 2000],
            "avg90": [None, 2100],
            "salesRankDrops90": 12,
        },
        "newOfferCount": 5,
        "availabilityAmazon": -1,
    }

    def fake_request(path, params=None):
        return {"products": [raw_product]}

    monkeypatch.setattr(client, "_request", fake_request)

    products = client.get_products_by_asins([" b0test1234 "])
    normalized = client.normalize_product(products[0])

    assert isinstance(normalized["raw_keepa_json"], str)
    parsed = json.loads(normalized["raw_keepa_json"])
    assert parsed["asin"] == "b0test1234"
    assert parsed["title"] == "テスト商品"


def test_search_products_calls_search_path_with_keyword_and_limit(monkeypatch):
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    called = {}

    def fake_request(path, params=None):
        called["path"] = path
        called["params"] = params
        return {"products": []}

    monkeypatch.setattr(client, "_request", fake_request)

    result = client.search_products("  water bottle  ", limit=25)

    assert result == []
    assert called["path"] == "/search"
    assert called["params"]["term"] == "water bottle"
    assert called["params"]["type"] == "product"
    assert called["params"]["limit"] == 25
    assert "domain" not in called["params"]


def test_search_products_raises_when_keyword_empty():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    with pytest.raises(KeepaApiError):
        client.search_products("   ")


@pytest.mark.parametrize("limit", [0, 101])
def test_search_products_raises_when_limit_out_of_range(limit):
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    with pytest.raises(KeepaApiError):
        client.search_products("keyword", limit=limit)


def test_search_products_adds_category_when_present(monkeypatch):
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    called = {}

    def fake_request(path, params=None):
        called["params"] = params
        return {"products": []}

    monkeypatch.setattr(client, "_request", fake_request)

    client.search_products("keyword", category_id=12345, limit=10)

    assert called["params"]["category"] == "12345"


def test_search_products_raises_when_filters_is_not_dict():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    with pytest.raises(KeepaApiError):
        client.search_products("keyword", filters=["not", "dict"])


def test_search_products_uses_asin_list_and_fetches_products(monkeypatch):
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    called = {}

    def fake_request(path, params=None):
        return {"asinList": ["b0test0001", "B0TEST0002"]}

    def fake_get_products_by_asins(asins, offers=20):
        called["asins"] = asins
        called["offers"] = offers
        return [{"asin": asin, "title": f"Product {asin}"} for asin in asins]

    monkeypatch.setattr(client, "_request", fake_request)
    monkeypatch.setattr(client, "get_products_by_asins", fake_get_products_by_asins)

    result = client.search_products("keyword", limit=2)

    assert called["asins"] == ["B0TEST0001", "B0TEST0002"]
    assert called["offers"] == 0
    assert result == [
        {"asin": "B0TEST0001", "title": "Product B0TEST0001"},
        {"asin": "B0TEST0002", "title": "Product B0TEST0002"},
    ]


def test_search_products_uses_asins_and_fetches_products(monkeypatch):
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    called = {}

    def fake_request(path, params=None):
        return {"asins": ["b0test0003", "B0TEST0004"]}

    def fake_get_products_by_asins(asins, offers=20):
        called["asins"] = asins
        called["offers"] = offers
        return [{"asin": asin} for asin in asins]

    monkeypatch.setattr(client, "_request", fake_request)
    monkeypatch.setattr(client, "get_products_by_asins", fake_get_products_by_asins)

    result = client.search_products("keyword", limit=2)

    assert called["asins"] == ["B0TEST0003", "B0TEST0004"]
    assert called["offers"] == 0
    assert result == [{"asin": "B0TEST0003"}, {"asin": "B0TEST0004"}]


def test_search_products_limits_asins_before_fetching_products(monkeypatch):
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    called = {}

    def fake_request(path, params=None):
        return {"asinList": ["B0TEST0001", "B0TEST0002", "B0TEST0003"]}

    def fake_get_products_by_asins(asins, offers=20):
        called["asins"] = asins
        called["offers"] = offers
        return [{"asin": asin} for asin in asins]

    monkeypatch.setattr(client, "_request", fake_request)
    monkeypatch.setattr(client, "get_products_by_asins", fake_get_products_by_asins)

    client.search_products("keyword", limit=2)

    assert called["asins"] == ["B0TEST0001", "B0TEST0002"]
    assert called["offers"] == 0


def test_search_products_fetches_product_details_from_search_products_asins(monkeypatch):
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    called = {}
    products = [
        {"asin": "B0TEST0001", "title": "Product 1"},
        {"asin": "B0TEST0002", "title": "Product 2"},
        {"asin": "B0TEST0003", "title": "Product 3"},
    ]

    def fake_request(path, params=None):
        return {"products": products}

    def fake_get_products_by_asins(asins, offers=20):
        called["asins"] = asins
        called["offers"] = offers
        return [{"asin": asin, "title": f"Detailed {asin}"} for asin in asins]

    monkeypatch.setattr(client, "_request", fake_request)
    monkeypatch.setattr(client, "get_products_by_asins", fake_get_products_by_asins)

    result = client.search_products("keyword", limit=2)

    assert called["asins"] == ["B0TEST0001", "B0TEST0002"]
    assert called["offers"] == 0
    assert result == [
        {"asin": "B0TEST0001", "title": "Detailed B0TEST0001"},
        {"asin": "B0TEST0002", "title": "Detailed B0TEST0002"},
    ]


def test_keyword_research_light_mode_uses_no_or_low_offers(monkeypatch):
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    called = {}

    def fake_request(path, params=None):
        return {"asinList": ["B0LIGHT001"]}

    def fake_get_products_by_asins(asins, offers=20):
        called["asins"] = asins
        called["offers"] = offers
        return [{"asin": asins[0]}]

    monkeypatch.setattr(client, "_request", fake_request)
    monkeypatch.setattr(client, "get_products_by_asins", fake_get_products_by_asins)

    client.search_products("keyword", limit=1, fetch_mode="light")

    assert called["asins"] == ["B0LIGHT001"]
    assert called["offers"] == 0


def test_keyword_research_detail_mode_uses_offers_20(monkeypatch):
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    called = {}

    def fake_request(path, params=None):
        return {"asinList": ["B0DETAIL01"]}

    def fake_get_products_by_asins(asins, offers=20):
        called["asins"] = asins
        called["offers"] = offers
        return [{"asin": asins[0]}]

    monkeypatch.setattr(client, "_request", fake_request)
    monkeypatch.setattr(client, "get_products_by_asins", fake_get_products_by_asins)

    client.search_products("keyword", limit=1, fetch_mode="detail")

    assert called["asins"] == ["B0DETAIL01"]
    assert called["offers"] == 20


def test_search_products_returns_direct_products_with_limit_when_asins_missing(monkeypatch):
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    products = [
        {"title": "Product 1"},
        {"title": "Product 2"},
        {"title": "Product 3"},
    ]

    def fake_request(path, params=None):
        return {"products": products}

    monkeypatch.setattr(client, "_request", fake_request)

    result = client.search_products("keyword", limit=2)

    assert result == products[:2]


def test_search_products_returns_empty_list_when_no_asins_or_products(monkeypatch):
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})

    def fake_request(path, params=None):
        return {"ok": True}

    monkeypatch.setattr(client, "_request", fake_request)

    assert client.search_products("keyword") == []


def test_search_products_error_message_does_not_include_api_key(monkeypatch):
    secret = "real-secret-key"
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: secret})

    def fake_request(path, params=None):
        raise KeepaApiError(f"failed key={secret}")

    monkeypatch.setattr(client, "_request", fake_request)

    with pytest.raises(KeepaApiError) as exc_info:
        client.search_products("keyword")

    assert secret not in str(exc_info.value)


def test_get_token_status_missing_api_key_returns_safe_error():
    client = make_client({})

    with pytest.raises(KeepaApiKeyMissingError) as exc_info:
        client.get_token_status()

    assert exc_info.value.error_type == "missing_api_key"
    assert "Keepa API Keyが未設定です。" in str(exc_info.value)
    assert "keepa_api_key" not in str(exc_info.value).lower()


def test_get_token_status_invalid_api_key_is_classified(monkeypatch):
    secret = "SECRET_KEEPA_KEY_123"
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: secret})

    def fake_get(url, params, timeout):
        return DummyResponse(status_code=401, payload={"error": f"invalid key {secret}"})

    monkeypatch.setattr("app.services.keepa_client.requests.get", fake_get)

    with pytest.raises(KeepaApiError) as exc_info:
        client.get_token_status()

    assert exc_info.value.error_type == "invalid_api_key"
    assert secret not in str(exc_info.value)


def test_get_token_status_token_insufficient_is_classified(monkeypatch):
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "SECRET_KEEPA_KEY_123"})

    def fake_get(url, params, timeout):
        return DummyResponse(status_code=429, payload={"error": "tokens depleted"})

    monkeypatch.setattr("app.services.keepa_client.requests.get", fake_get)

    with pytest.raises(KeepaTokenError) as exc_info:
        client.get_token_status()

    assert exc_info.value.error_type == "token_insufficient"
    assert "トークンが不足" in str(exc_info.value)


def test_get_token_status_connection_error_is_classified(monkeypatch):
    secret = "SECRET_KEEPA_KEY_123"
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: secret})

    def fake_get(url, params, timeout):
        raise Timeout(f"timeout key={secret}")

    monkeypatch.setattr("app.services.keepa_client.requests.get", fake_get)

    with pytest.raises(KeepaApiError) as exc_info:
        client.get_token_status()

    assert exc_info.value.error_type == "keepa_connection_failed"
    assert secret not in str(exc_info.value)


def test_get_products_by_asins_api_error_does_not_leak_api_key(monkeypatch):
    secret = "SECRET_KEEPA_KEY_123"
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: secret})

    def fake_get(url, params, timeout):
        return DummyResponse(status_code=403, payload={"error": f"apiKey={secret}"})

    monkeypatch.setattr("app.services.keepa_client.requests.get", fake_get)

    with pytest.raises(KeepaApiError) as exc_info:
        client.get_products_by_asins(["B0TEST0001"])

    assert exc_info.value.error_type == "invalid_api_key"
    assert secret not in str(exc_info.value)


def test_search_products_api_error_does_not_leak_api_key(monkeypatch):
    secret = "SECRET_KEEPA_KEY_123"
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: secret})

    def fake_get(url, params, timeout):
        raise RequestsConnectionError(f"connection failed apiKey={secret}")

    monkeypatch.setattr("app.services.keepa_client.requests.get", fake_get)

    with pytest.raises(KeepaApiError) as exc_info:
        client.search_products("keyword")

    assert exc_info.value.error_type == "keepa_connection_failed"
    assert secret not in str(exc_info.value)


def test_keepa_client_logs_masked_api_key(app, caplog, monkeypatch):
    secret = "SECRET_KEEPA_KEY_123"
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: secret})

    def fake_get(url, params, timeout):
        return DummyResponse(status_code=500, payload={"error": "server error"})

    monkeypatch.setattr("app.services.keepa_client.requests.get", fake_get)

    with app.app_context(), caplog.at_level("ERROR"):
        with pytest.raises(KeepaApiError):
            client.get_products_by_asins(["B0TEST0001"])

    assert secret not in caplog.text
    assert "[REDACTED]" in caplog.text
    assert "keepa_api_key" not in caplog.text


def test_normalize_product_missing_optional_fields_does_not_crash():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    raw = {
        "asin": "B0TEST0001",
        "title": "Optional Missing Product",
        "stats": None,
        "csv": None,
        "offers": None,
        "imagesCSV": None,
        "salesRanks": None,
    }

    result = client.normalize_product(raw)

    assert result["asin"] == "B0TEST0001"
    assert result["title"] == "Optional Missing Product"
    assert result["current_price"] is None
    assert result["sales_rank_drops_90"] is None
    assert result["image_url"] is None


def test_raw_keepa_json_does_not_include_api_key():
    secret = "SECRET_KEEPA_KEY_123"
    token = "Bearer SECRET_TOKEN_456"
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: secret})
    raw = {
        "asin": "B0TEST0001",
        "title": "Safe Raw Product",
        "requestUrl": f"https://api.keepa.com/product?key={secret}&domain=5",
        "headers": {"Authorization": token},
        "nested": {"token": "abc123"},
    }

    result = client.normalize_product(raw)

    assert secret not in result["raw_keepa_json"]
    assert "SECRET_TOKEN_456" not in result["raw_keepa_json"]
    assert "abc123" not in result["raw_keepa_json"]
    assert "[REDACTED]" in result["raw_keepa_json"]



def test_normalize_product_extracts_lowest_highest_price_from_stats_min_max_pair():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    raw = {
        "asin": "B0TESTRAW1",
        "title": "Real Raw Shape Product",
        "stats": {
            "min": [[123456, 2400], [123457, 2300]],
            "max": [[123456, 3200], [123457, 3300]],
        },
    }

    result = client.normalize_product(raw)

    assert result["lowest_price_90"] == 2300
    assert result["highest_price_90"] == 3300


def test_normalize_product_extracts_price_from_min_in_interval_and_max_in_interval():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    raw = {
        "asin": "B0TESTRAW1",
        "title": "Interval Price Product",
        "stats": {
            "min": [[123456, 2400], [123457, 2300]],
            "max": [[123456, 3200], [123457, 3300]],
            "minInInterval": [[123456, 2450], [123457, 2350]],
            "maxInInterval": [[123456, 3050], [123457, 3150]],
        },
    }

    result = client.normalize_product(raw)

    assert result["lowest_price_90"] == 2350
    assert result["highest_price_90"] == 3150


def test_normalize_product_falls_back_to_stats_total_offer_count():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    raw = {
        "asin": "B0TESTRAW1",
        "title": "Offer Count Product",
        "stats": {"totalOfferCount": 7, "retrievedOfferCount": 6},
    }

    result = client.normalize_product(raw)

    assert result["new_offer_count"] == 7


def test_normalize_product_falls_back_to_stats_retrieved_offer_count():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    raw = {
        "asin": "B0TESTRAW1",
        "title": "Retrieved Offer Count Product",
        "stats": {"retrievedOfferCount": "6"},
    }

    result = client.normalize_product(raw)

    assert result["new_offer_count"] == 6


def test_normalize_product_falls_back_to_stats_offer_count_fba():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    raw = {
        "asin": "B0TESTRAW1",
        "title": "FBA Offer Count Product",
        "stats": {"offerCountFBA": 5},
    }

    result = client.normalize_product(raw)

    assert result["fba_offer_count"] == 5


def test_normalize_product_infers_amazon_was_in_stock_from_out_of_stock_percentage():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    raw_out_of_stock = {
        "asin": "B0TESTRAW1",
        "title": "Amazon Out Product",
        "stats": {"outOfStockPercentage90": 100},
    }
    raw_was_in_stock = {
        "asin": "B0TESTRAW2",
        "title": "Amazon Was Product",
        "stats": {"outOfStockPercentage90": [10, 0, 0]},
    }

    out_result = client.normalize_product(raw_out_of_stock)
    was_result = client.normalize_product(raw_was_in_stock)

    assert out_result["amazon_was_in_stock_90"] is False
    assert was_result["amazon_was_in_stock_90"] is True


def test_normalize_product_keeps_amazon_was_in_stock_unknown_when_data_missing():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    raw = {"asin": "B0TESTRAW1", "title": "Unknown Amazon History Product", "stats": {}}

    result = client.normalize_product(raw)

    assert result["amazon_was_in_stock_90"] is None


def test_normalize_product_uses_images_fallback_when_images_csv_missing():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    raw = {
        "asin": "B0TESTRAW1",
        "title": "Image Fallback Product",
        "images": [{"l": "https://example.com/image.jpg"}],
    }

    result = client.normalize_product(raw)

    assert result["image_url"] == "https://example.com/image.jpg"


def test_normalize_product_does_not_crash_with_malformed_stats_values():
    client = make_client({AppSetting.KEY_KEEPA_API_KEY: "secret-key"})
    raw = {
        "asin": "B0TESTRAW1",
        "title": "Malformed Stats Product",
        "stats": {
            "minInInterval": [[123456, -1], [123457, None]],
            "maxInInterval": "not-a-list",
            "totalOfferCount": "not-a-number",
            "offerCountFBA": {},
            "outOfStockPercentage90": "bad",
        },
        "images": [{"l": None}, {}],
    }

    result = client.normalize_product(raw)

    assert result["lowest_price_90"] is None
    assert result["highest_price_90"] is None
    assert result["new_offer_count"] is None
    assert result["fba_offer_count"] is None
    assert result["amazon_was_in_stock_90"] is None
    assert result["image_url"] is None
