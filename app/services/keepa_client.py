from __future__ import annotations

import json
from typing import Any

import requests
from flask import current_app, has_app_context
from requests import Response
from requests.exceptions import ConnectionError, RequestException, Timeout

from app.models import AppSetting
from app.services.error_utils import (
    build_user_friendly_error_message,
    log_safe,
    mask_sensitive_text,
    sanitize_dict,
    sanitize_error_message,
)
from app.services.settings_defaults import DEFAULT_SETTINGS
from app.services.settings_service import SettingsService


class KeepaClientError(Exception):
    """Keepa client common error."""

    def __init__(self, message: str = "", error_type: str = "unknown"):
        super().__init__(mask_sensitive_text(message))
        self.error_type = error_type


class KeepaApiKeyMissingError(KeepaClientError):
    """Keepa API Key is not configured."""


class KeepaApiError(KeepaClientError):
    """Keepa API communication or response error."""


class KeepaTokenError(KeepaClientError):
    """Keepa token or authentication error."""

class KeepaClient:
    BASE_URL = "https://api.keepa.com"
    _NEW_PRICE_INDEX = 1
    _SALES_RANK_INDEX = 3
    _SENSITIVE_KEY_NAMES = {
        "key",
        "apikey",
        "api_key",
        "accesskey",
        "access_key",
        "keepa_api_key",
    }

    def __init__(self, settings_service: Any = None, timeout: int = 30):
        self._settings_service = settings_service or SettingsService
        self._timeout = timeout
        self._last_tokens_left: int | None = None

    def _get_api_key(self) -> str:
        api_key = self._settings_service.get(AppSetting.KEY_KEEPA_API_KEY)
        if api_key is None or not str(api_key).strip():
            raise KeepaApiKeyMissingError(
                build_user_friendly_error_message("missing_api_key"),
                error_type="missing_api_key",
            )
        return str(api_key).strip()

    def _get_domain_id(self) -> int:
        domain_value = self._settings_service.get(AppSetting.KEY_DEFAULT_DOMAIN_ID)
        if domain_value is None:
            domain_value = DEFAULT_SETTINGS.get(AppSetting.KEY_DEFAULT_DOMAIN_ID)

        try:
            domain_id = int(domain_value)
        except (TypeError, ValueError) as exc:
            raise KeepaApiError(
                "Invalid Keepa domain configuration.",
                error_type="keepa_api_failed",
            ) from exc

        if domain_id < 1:
            raise KeepaApiError(
                "Keepa domain must be a positive integer.",
                error_type="keepa_api_failed",
            )

        return domain_id

    def _request(
        self,
        path: str,
        params: dict | None = None,
        raise_on_empty_tokens: bool = True,
        log_context: dict | None = None,
    ) -> dict:
        request_params = dict(params or {})
        request_params["key"] = self._get_api_key()
        request_params["domain"] = self._get_domain_id()
        url = f"{self.BASE_URL}{path}"
        before_tokens = self._last_tokens_left
        if before_tokens is None and path != "/token":
            before_tokens = self._read_current_tokens_for_log(request_params)

        try:
            response = requests.get(url, params=request_params, timeout=self._timeout)
        except (Timeout, ConnectionError) as exc:
            self._log_keepa_error(
                "Keepa API connection failed.",
                path=path,
                params=request_params,
                error_type="keepa_connection_failed",
                detail=exc,
            )
            raise KeepaApiError(
                build_user_friendly_error_message("keepa_connection_failed"),
                error_type="keepa_connection_failed",
            ) from None
        except RequestException as exc:
            self._log_keepa_error(
                "Keepa API request failed.",
                path=path,
                params=request_params,
                error_type="keepa_connection_failed",
                detail=exc,
            )
            raise KeepaApiError(
                build_user_friendly_error_message("keepa_connection_failed"),
                error_type="keepa_connection_failed",
            ) from None

        self._raise_for_bad_status(response, path=path, params=request_params)
        payload = self._parse_json(response)
        self._raise_for_api_errors(payload, path=path, params=request_params)

        tokens_left = payload.get("tokensLeft")
        after_tokens = self._optional_token_value(tokens_left)
        self._log_token_consumption(
            path=path,
            params=request_params,
            before_tokens=before_tokens,
            after_tokens=after_tokens,
            log_context=log_context,
        )
        if after_tokens is not None:
            self._last_tokens_left = after_tokens

        if tokens_left is not None and raise_on_empty_tokens:
            try:
                if int(tokens_left) <= 0:
                    raise KeepaTokenError(
                        build_user_friendly_error_message("token_insufficient"),
                        error_type="token_insufficient",
                    )
            except (TypeError, ValueError) as exc:
                raise KeepaApiError(
                    "Invalid tokensLeft value in Keepa response.",
                    error_type="keepa_api_failed",
                ) from exc

        return payload

    def get_token_status(self, allow_depleted: bool = False) -> dict:
        try:
            raw = self._request(
                "/token",
                params={},
                raise_on_empty_tokens=not allow_depleted,
            )
        except TypeError:
            # Keep compatibility with tests or injected clients using the old helper shape.
            raw = self._request("/token", params={})

        if "tokensLeft" not in raw:
            raise KeepaApiError(
                "Keepa token response is missing tokensLeft.",
                error_type="keepa_api_failed",
            )

        try:
            tokens_left = int(raw.get("tokensLeft"))
        except (TypeError, ValueError) as exc:
            raise KeepaApiError(
                "Invalid tokensLeft value in Keepa token response.",
                error_type="keepa_api_failed",
            ) from exc

        if tokens_left <= 0 and not allow_depleted:
            raise KeepaTokenError(
                build_user_friendly_error_message("token_insufficient"),
                error_type="token_insufficient",
            )

        return {
            "tokens_left": tokens_left,
            "refill_rate": self._optional_int(raw, "refillRate"),
            "refill_in": self._optional_int(raw, "refillIn"),
            "token_flow_reduction": self._optional_float(raw, "tokenFlowReduction"),
            "tokens_consumed": self._optional_int(raw, "tokensConsumed"),
            "raw": raw,
        }

    def get_products_by_asins(self, asins: list[str], offers: int | None = 20) -> list[dict]:
        cleaned_asins = self._clean_asins(asins)
        if not cleaned_asins:
            raise KeepaApiError(
                "No valid ASINs were provided.",
                error_type="data_insufficient",
            )

        request_params = {
            "asin": ",".join(cleaned_asins),
            "stats": 90,
        }
        log_context = {}
        if offers is not None:
            normalized_offers = int(offers)
            log_context["offers"] = normalized_offers
            if normalized_offers > 0:
                request_params["offers"] = normalized_offers
                log_context["mode"] = "detail"
            else:
                log_context["mode"] = "light"

        response = self._request_with_log_context(
            "/product",
            params=request_params,
            log_context=log_context,
        )

        products = response.get("products")
        if products is None:
            raise KeepaApiError(
                "Keepa product response did not contain products.",
                error_type="keepa_api_failed",
            )
        if not isinstance(products, list):
            raise KeepaApiError(
                "Keepa product response products must be a list.",
                error_type="keepa_api_failed",
            )
        return products

    def search_products(
        self,
        keyword: str,
        category_id=None,
        limit: int = 100,
        filters: dict | None = None,
        fetch_mode: str = "light",
    ) -> list[dict]:
        keyword_text = str(keyword).strip() if keyword is not None else ""
        if not keyword_text:
            raise KeepaApiError(
                "Keyword is required for Keepa product search.",
                error_type="data_insufficient",
            )

        if not isinstance(limit, int) or limit < 1 or limit > 100:
            raise KeepaApiError(
                "Search limit must be between 1 and 100.",
                error_type="data_insufficient",
            )

        if filters is not None and not isinstance(filters, dict):
            raise KeepaApiError(
                "Search filters must be a dictionary.",
                error_type="data_insufficient",
            )
        if fetch_mode not in {"light", "detail"}:
            raise KeepaApiError(
                "Search fetch_mode must be light or detail.",
                error_type="data_insufficient",
            )

        params = {
            "term": keyword_text,
            "type": "product",
            "limit": limit,
        }
        if category_id is not None and str(category_id).strip():
            params["category"] = str(category_id).strip()

        try:
            response = self._request_with_log_context(
                "/search",
                params=params,
                log_context={"mode": fetch_mode},
            )

            asin_list = self._extract_search_asins(response)
            if asin_list:
                offers = 20 if fetch_mode == "detail" else 0
                return self.get_products_by_asins(asin_list[:limit], offers=offers)

            products = response.get("products")
            if isinstance(products, list):
                return products[:limit]

            return []
        except KeepaApiKeyMissingError as exc:
            raise KeepaApiKeyMissingError(
                build_user_friendly_error_message("missing_api_key"),
                error_type="missing_api_key",
            ) from exc
        except KeepaTokenError as exc:
            raise KeepaTokenError(
                build_user_friendly_error_message("token_insufficient"),
                error_type="token_insufficient",
            ) from exc
        except KeepaClientError as exc:
            raise KeepaApiError(
                sanitize_error_message(exc, fallback="Keepa product search failed."),
                error_type=getattr(exc, "error_type", "keepa_api_failed"),
            ) from exc

    def normalize_product(self, raw_product: dict) -> dict:
        if not isinstance(raw_product, dict):
            raise KeepaApiError(
                "Keepa product must be a dictionary.",
                error_type="data_insufficient",
            )

        asin_raw = raw_product.get("asin")
        asin = str(asin_raw).strip().upper() if asin_raw is not None else ""
        if not asin:
            raise KeepaApiError(
                "Keepa product is missing ASIN.",
                error_type="data_insufficient",
            )

        title_raw = raw_product.get("title")
        title = str(title_raw).strip() if title_raw is not None else ""
        if not title:
            raise KeepaApiError(
                "Keepa product is missing title.",
                error_type="data_insufficient",
            )

        ean_value = self._extract_first_ean(raw_product.get("eanList"))
        category_id, category_name = self._extract_category(raw_product)
        image_url = self._extract_image_url(raw_product.get("imagesCSV"))
        if image_url is None:
            image_url = self._extract_image_url_from_images(raw_product.get("images"))

        stats = raw_product.get("stats")
        stats = stats if isinstance(stats, dict) else {}

        current_price = self._extract_stat_price(stats, "current")
        if current_price is None:
            current_price = self._normalize_positive_int(raw_product.get("current_price"))

        normalized = {
            "asin": asin,
            "jan": ean_value,
            "ean": ean_value,
            "title": title,
            "brand": raw_product.get("brand"),
            "manufacturer": raw_product.get("manufacturer"),
            "category_id": category_id,
            "category_name": category_name,
            "image_url": image_url,
            "amazon_url": f"https://www.amazon.co.jp/dp/{asin}",
            "keepa_url": f"https://keepa.com/#!product/5-{asin}",
            "current_price": current_price,
            "avg_price_30": self._extract_stat_price(stats, "avg30"),
            "avg_price_90": self._extract_stat_price(stats, "avg90"),
            "lowest_price_90": self._first_non_none(
                self._extract_stat_price(stats, "minInInterval"),
                self._extract_stat_price(stats, "min"),
            ),
            "highest_price_90": self._first_non_none(
                self._extract_stat_price(stats, "maxInInterval"),
                self._extract_stat_price(stats, "max"),
            ),
            "sales_rank_current": self._extract_stat_rank(stats, "current"),
            "sales_rank_avg_30": self._extract_stat_rank(stats, "avg30"),
            "sales_rank_avg_90": self._extract_stat_rank(stats, "avg90"),
            "sales_rank_drops_30": self._first_non_none(
                self._normalize_non_negative_int(stats.get("salesRankDrops30")),
                self._normalize_non_negative_int(raw_product.get("salesRankDrops30")),
            ),
            "sales_rank_drops_90": self._first_non_none(
                self._normalize_non_negative_int(stats.get("salesRankDrops90")),
                self._normalize_non_negative_int(raw_product.get("salesRankDrops90")),
            ),
            "new_offer_count": self._first_non_none(
                self._normalize_non_negative_int(raw_product.get("newOfferCount")),
                self._normalize_non_negative_int(raw_product.get("offerCount")),
                self._normalize_non_negative_int(stats.get("totalOfferCount")),
                self._normalize_non_negative_int(stats.get("retrievedOfferCount")),
            ),
            "used_offer_count": self._normalize_non_negative_int(
                raw_product.get("usedOfferCount")
            ),
            "fba_offer_count": self._normalize_non_negative_int(
                self._first_non_none(
                    raw_product.get("fbaOfferCount"),
                    raw_product.get("fba_offer_count"),
                    stats.get("offerCountFBA"),
                )
            ),
            "amazon_in_stock": self._normalize_amazon_in_stock(
                raw_product.get("availabilityAmazon")
            ),
            "amazon_was_in_stock_90": self._extract_amazon_was_in_stock_90(stats),
            "review_count": self._first_non_none(
                self._normalize_non_negative_int(raw_product.get("reviews")),
                self._normalize_non_negative_int(raw_product.get("reviewCount")),
            ),
            "rating": self._normalize_rating(raw_product.get("rating")),
            "raw_keepa_json": json.dumps(
                self._sanitize_sensitive_data(raw_product),
                ensure_ascii=False,
            ),
        }
        return normalized

    @classmethod
    def _raise_for_bad_status(
        cls,
        response: Response,
        path: str | None = None,
        params: dict | None = None,
    ) -> None:
        if response.status_code >= 400:
            error_type = cls._error_type_for_status(response.status_code)
            cls._log_keepa_error(
                "Keepa API returned bad HTTP status.",
                path=path,
                params=params,
                status_code=response.status_code,
                error_type=error_type,
            )
            error_cls = KeepaTokenError if error_type == "token_insufficient" else KeepaApiError
            raise error_cls(
                build_user_friendly_error_message(error_type),
                error_type=error_type,
            )

    @staticmethod
    def _parse_json(response: Response) -> dict:
        try:
            payload = response.json()
        except ValueError as exc:
            raise KeepaApiError(
                build_user_friendly_error_message("keepa_api_failed"),
                error_type="keepa_api_failed",
            ) from exc

        if not isinstance(payload, dict):
            raise KeepaApiError(
                "Keepa API returned unexpected JSON format.",
                error_type="keepa_api_failed",
            )

        return payload

    @classmethod
    def _raise_for_api_errors(
        cls,
        payload: dict,
        path: str | None = None,
        params: dict | None = None,
    ) -> None:
        detail = payload.get("error") or payload.get("errors")
        if not detail:
            return
        error_type = cls._classify_payload_error(detail)
        cls._log_keepa_error(
            "Keepa API reported an error.",
            path=path,
            params=params,
            error_type=error_type,
            detail=detail,
        )
        error_cls = KeepaTokenError if error_type == "token_insufficient" else KeepaApiError
        raise error_cls(
            build_user_friendly_error_message(error_type),
            error_type=error_type,
        )

    @staticmethod
    def _optional_int(payload: dict, key: str) -> int | None:
        value = payload.get(key)
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise KeepaApiError(
                f"Invalid {key} value in Keepa response.",
                error_type="keepa_api_failed",
            ) from exc

    @staticmethod
    def _optional_float(payload: dict, key: str) -> float | None:
        value = payload.get(key)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise KeepaApiError(
                f"Invalid {key} value in Keepa response.",
                error_type="keepa_api_failed",
            ) from exc

    @staticmethod
    def _optional_token_value(value) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _clean_asins(asins: list[str]) -> list[str]:
        if not asins:
            return []

        cleaned: list[str] = []
        seen: set[str] = set()
        for asin in asins:
            if asin is None:
                continue
            normalized = str(asin).strip().upper()
            if not normalized or normalized in seen:
                continue
            cleaned.append(normalized)
            seen.add(normalized)
        return cleaned

    def _extract_search_asins(self, response: dict) -> list[str]:
        for key in ("asinList", "asins"):
            value = response.get(key)
            if isinstance(value, list):
                return self._clean_asins(value)

        products = response.get("products")
        if isinstance(products, list):
            asins = [
                product.get("asin")
                for product in products
                if isinstance(product, dict) and product.get("asin")
            ]
            return self._clean_asins(asins)

        return []

    @staticmethod
    def _safe_list_get(value, index, default=None):
        if isinstance(value, (list, tuple)) and 0 <= index < len(value):
            return value[index]
        return default

    @staticmethod
    def _normalize_positive_int(value) -> int | None:
        if value is None:
            return None
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            return None
        if normalized <= 0:
            return None
        return normalized

    @staticmethod
    def _normalize_non_negative_int(value) -> int | None:
        if value is None:
            return None
        try:
            normalized = int(value)
        except (TypeError, ValueError):
            return None
        if normalized < 0:
            return None
        return normalized

    @staticmethod
    def _first_non_none(*values):
        for value in values:
            if value is not None:
                return value
        return None

    def _extract_stat_price(self, stats: dict, key: str) -> int | None:
        raw_value = stats.get(key)
        value = self._safe_list_get(raw_value, self._NEW_PRICE_INDEX)
        if value is None:
            value = raw_value
        return self._extract_keepa_price_value(value)

    def _extract_stat_rank(self, stats: dict, key: str) -> int | None:
        value = self._safe_list_get(stats.get(key), self._SALES_RANK_INDEX)
        return self._normalize_positive_int(value)

    @staticmethod
    def _extract_first_ean(ean_list) -> str | None:
        if not isinstance(ean_list, (list, tuple)) or not ean_list:
            return None
        first = ean_list[0]
        if first is None:
            return None
        text = str(first).strip()
        return text or None

    @staticmethod
    def _extract_category(raw_product: dict) -> tuple[str | None, str | None]:
        root_category = raw_product.get("rootCategory")
        category_tree = raw_product.get("categoryTree")
        category_id = str(root_category) if root_category is not None else None
        category_name = None

        if isinstance(category_tree, list) and category_tree:
            last = category_tree[-1]
            if isinstance(last, dict):
                if category_id is None and last.get("catId") is not None:
                    category_id = str(last.get("catId"))
                if last.get("name") is not None:
                    category_name = str(last.get("name"))
        return category_id, category_name

    @staticmethod
    def _extract_image_url(images_csv) -> str | None:
        if not isinstance(images_csv, str) or not images_csv.strip():
            return None

        first_image = images_csv.split(",")[0].strip()
        if not first_image:
            return None
        if first_image.startswith("http://") or first_image.startswith("https://"):
            return first_image
        return f"https://images-na.ssl-images-amazon.com/images/I/{first_image}"

    @classmethod
    def _extract_image_url_from_images(cls, images) -> str | None:
        if not isinstance(images, (list, tuple)):
            return None

        for image in images:
            candidate = None
            if isinstance(image, str):
                candidate = image
            elif isinstance(image, dict):
                for key in ("l", "large", "m", "medium", "s", "small", "url"):
                    if image.get(key):
                        candidate = image.get(key)
                        break
            if not candidate:
                continue

            if isinstance(candidate, str):
                return cls._extract_image_url(candidate)
        return None

    @staticmethod
    def _normalize_amazon_in_stock(value) -> bool | None:
        if value is None:
            return False
        if isinstance(value, bool):
            return value
        try:
            return int(value) > 0
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_amazon_was_in_stock_90(stats: dict) -> bool | None:
        marker = stats.get("amazonInStock90")
        if marker is None:
            out_of_stock_percentage = KeepaClient._extract_keepa_numeric_value(
                stats.get("outOfStockPercentage90"),
                index=0,
            )
            if out_of_stock_percentage is not None:
                if out_of_stock_percentage == 100:
                    return False
                if 0 <= out_of_stock_percentage <= 99:
                    return True

            out_of_stock_count = KeepaClient._extract_keepa_numeric_value(
                stats.get("outOfStockCountAmazon90"),
                index=0,
            )
            if out_of_stock_count is not None:
                return out_of_stock_count < 90

            return None
        try:
            return int(marker) > 0
        except (TypeError, ValueError):
            if isinstance(marker, bool):
                return marker
            return None

    @classmethod
    def _extract_keepa_price_value(cls, value) -> int | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return cls._normalize_positive_int(value)
        if isinstance(value, (list, tuple)):
            if len(value) >= 2 and not isinstance(value[1], (list, tuple, dict)):
                return cls._normalize_positive_int(value[1])
            for item in value:
                extracted = cls._extract_keepa_price_value(item)
                if extracted is not None:
                    return extracted
        return None

    @classmethod
    def _extract_keepa_numeric_value(cls, value, index: int = 0) -> int | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return cls._normalize_non_negative_int(value)
        if isinstance(value, (list, tuple)):
            indexed = cls._safe_list_get(value, index)
            normalized = cls._normalize_non_negative_int(indexed)
            if normalized is not None:
                return normalized
            if len(value) >= 2 and not isinstance(value[1], (list, tuple, dict)):
                return cls._normalize_non_negative_int(value[1])
        return None

    @staticmethod
    def _normalize_rating(value) -> float | None:
        if value is None:
            return None
        try:
            rating = float(value)
        except (TypeError, ValueError):
            return None
        if rating <= 0:
            return None
        if rating > 5:
            rating = rating / 10
        return rating

    @classmethod
    def _sanitize_sensitive_data(cls, value):
        if isinstance(value, dict):
            return sanitize_dict(value)
        if isinstance(value, list):
            return [cls._sanitize_sensitive_data(item) for item in value]
        if isinstance(value, tuple):
            return [cls._sanitize_sensitive_data(item) for item in value]
        if isinstance(value, str):
            return mask_sensitive_text(value)
        return value

    @staticmethod
    def _error_type_for_status(status_code: int) -> str:
        if status_code in (401, 403):
            return "invalid_api_key"
        if status_code == 429:
            return "token_insufficient"
        return "keepa_api_failed"

    @staticmethod
    def _classify_payload_error(detail) -> str:
        text = mask_sensitive_text(detail).lower()
        if "token" in text or "tokensleft" in text:
            return "token_insufficient"
        if "auth" in text or "invalid key" in text or "api key" in text:
            return "invalid_api_key"
        return "keepa_api_failed"

    @staticmethod
    def _log_keepa_error(message: str, **context) -> None:
        if not has_app_context():
            return
        log_safe(current_app.logger, "error", message, **context)

    @classmethod
    def _log_token_consumption(
        cls,
        path: str,
        params: dict,
        before_tokens: int | None,
        after_tokens: int | None,
        log_context: dict | None = None,
    ) -> None:
        if not has_app_context() or path == "/token":
            return
        log_context = log_context or {}
        consumed = None
        if before_tokens is not None and after_tokens is not None:
            consumed = max(0, before_tokens - after_tokens)

        log_safe(
            current_app.logger,
            "info",
            "Keepa API token consumption",
            before_tokens=before_tokens,
            after_tokens=after_tokens,
            consumed=consumed,
            endpoint=path,
            mode=log_context.get("mode") or cls._token_log_mode(path, params),
            limit=params.get("limit"),
            offers=log_context.get("offers", params.get("offers")),
        )

    @staticmethod
    def _token_log_mode(path: str, params: dict) -> str:
        if path == "/search":
            return "keyword_search"
        if path == "/product":
            if params.get("offers") == 0:
                return "light"
            if params.get("offers") is not None:
                return "detail"
            return "product_detail"
        return path.strip("/") or "unknown"

    def _read_current_tokens_for_log(self, request_params: dict) -> int | None:
        token_params = {
            "key": request_params.get("key"),
            "domain": request_params.get("domain"),
        }
        try:
            response = requests.get(
                f"{self.BASE_URL}/token",
                params=token_params,
                timeout=self._timeout,
            )
            if response.status_code >= 400:
                return None
            payload = self._parse_json(response)
        except Exception:
            return None

        tokens_left = self._optional_token_value(payload.get("tokensLeft"))
        if tokens_left is not None:
            self._last_tokens_left = tokens_left
        return tokens_left

    def _request_with_log_context(
        self,
        path: str,
        params: dict | None = None,
        log_context: dict | None = None,
    ) -> dict:
        try:
            return self._request(path, params=params, log_context=log_context)
        except TypeError as exc:
            if "log_context" not in str(exc):
                raise
            return self._request(path, params=params)
