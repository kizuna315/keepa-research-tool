from __future__ import annotations

import json
import re
from datetime import datetime

from flask import current_app, has_app_context

from app.extensions import db
from app.models import AppSetting, Product, ProductResearchRun, ResearchRun
from app.services.error_utils import (
    build_user_friendly_error_message,
    log_safe,
    sanitize_error_message,
)
from app.services.keepa_client import KeepaClient
from app.services.scoring_service import ScoringService
from app.services.settings_defaults import DEFAULT_SETTINGS


class ResearchServiceError(Exception):
    """Research service base exception."""

    def __init__(self, message: str = "", error_type: str = "unknown"):
        super().__init__(sanitize_error_message(message))
        self.error_type = error_type


class InvalidAsinInputError(ResearchServiceError):
    """Raised when ASIN input is invalid."""


class ResearchService:
    DEFAULT_RUN_NAME = "ASIN指定リサーチ"
    DEFAULT_KEYWORD_RUN_NAME = "キーワード検索リサーチ"
    DEFAULT_MIN_REVIEW_COUNT = "10"
    DEFAULT_MAX_REVIEW_COUNT = "99999"
    DEFAULT_KEYWORD_LIMIT = "100"
    DEFAULT_KEYWORD_FETCH_MODE = "light"
    KEYWORD_SEARCH_TOKEN_ESTIMATE = 1
    KEYWORD_LIGHT_DETAIL_TOKEN_ESTIMATE_PER_ASIN = 1
    KEYWORD_DETAIL_TOKEN_ESTIMATE_PER_ASIN = 6
    KEYWORD_DETAIL_OFFERS = 20
    KEYWORD_FETCH_MODES = {"light", "detail"}
    _ASIN_PATTERN = re.compile(r"^[A-Za-z0-9]{8,20}$")
    _REDACTABLE_ERROR_PATTERN = re.compile(
        r"(?i)\b(api[_-]?key|access[_-]?key|keepa[_-]?api[_-]?key|key)\b\s*[:=]\s*([^\s,;]+)"
    )

    def __init__(self, db_session=None, keepa_client=None, scoring_service=None):
        self._db_session = db_session or db.session
        self._keepa_client = keepa_client or KeepaClient()
        self._scoring_service = scoring_service or ScoringService()

    def parse_asins(self, asin_text: str) -> list[str]:
        if asin_text is None:
            raise InvalidAsinInputError("No valid ASINs were provided.")

        normalized_text = str(asin_text).replace(",", "\n")
        candidates = normalized_text.splitlines()

        asins: list[str] = []
        seen: set[str] = set()

        for candidate in candidates:
            asin = candidate.strip().upper()
            if not asin:
                continue
            if not self._ASIN_PATTERN.fullmatch(asin):
                continue
            if asin in seen:
                continue
            asins.append(asin)
            seen.add(asin)

        if not asins:
            raise InvalidAsinInputError("No valid ASINs were provided.")

        return asins

    def build_asin_conditions(self, name: str | None, asins: list[str]) -> dict:
        run_name = name.strip() if isinstance(name, str) else ""
        return {
            "type": "asin",
            "name": run_name or self.DEFAULT_RUN_NAME,
            "asins": asins,
            "total_requested": len(asins),
        }

    def create_research_run_for_asins(self, name: str | None, asin_text: str):
        asins = self.parse_asins(asin_text)
        conditions = self.build_asin_conditions(name, asins)

        research_run = ResearchRun(
            name=conditions["name"],
            keyword=None,
            category_id=None,
            status=ResearchRun.STATUS_PENDING,
            conditions_json=json.dumps(conditions, ensure_ascii=False),
            total_requested=len(asins),
            total_fetched=0,
            total_saved=0,
            error_message=None,
            started_at=None,
            finished_at=None,
        )

        try:
            self._db_session.add(research_run)
            self._db_session.commit()
            return research_run
        except Exception as exc:
            self._db_session.rollback()
            raise ResearchServiceError("Failed to create research run.") from exc

    def build_keyword_conditions(self, values: dict) -> dict:
        name = self._clean_text(self._get_value(values, "name"))
        keyword = self._clean_text(self._get_value(values, "keyword"))
        if not keyword:
            raise ResearchServiceError("Keyword is required.")

        min_price = self._parse_required_int(
            self._get_value(
                values,
                "min_price",
                DEFAULT_SETTINGS[AppSetting.KEY_DEFAULT_MIN_PRICE],
            ),
            "min_price",
        )
        max_price = self._parse_required_int(
            self._get_value(
                values,
                "max_price",
                DEFAULT_SETTINGS[AppSetting.KEY_DEFAULT_MAX_PRICE],
            ),
            "max_price",
        )
        min_review_count = self._parse_required_int(
            self._get_value(values, "min_review_count", self.DEFAULT_MIN_REVIEW_COUNT),
            "min_review_count",
        )
        max_review_count = self._parse_required_int(
            self._get_value(values, "max_review_count", self.DEFAULT_MAX_REVIEW_COUNT),
            "max_review_count",
        )
        min_offer_count = self._parse_required_int(
            self._get_value(
                values,
                "min_offer_count",
                DEFAULT_SETTINGS[AppSetting.KEY_DEFAULT_MIN_OFFER_COUNT],
            ),
            "min_offer_count",
        )
        max_offer_count = self._parse_required_int(
            self._get_value(
                values,
                "max_offer_count",
                DEFAULT_SETTINGS[AppSetting.KEY_DEFAULT_MAX_OFFER_COUNT],
            ),
            "max_offer_count",
        )
        min_sales_rank_drops_90 = self._parse_required_int(
            self._get_value(
                values,
                "min_sales_rank_drops_90",
                DEFAULT_SETTINGS[AppSetting.KEY_DEFAULT_MIN_SALES_RANK_DROPS_90],
            ),
            "min_sales_rank_drops_90",
        )
        limit = self._parse_required_int(
            self._get_value(values, "limit", self.DEFAULT_KEYWORD_LIMIT),
            "limit",
        )
        fetch_mode = self._clean_text(
            self._get_value(values, "fetch_mode", self.DEFAULT_KEYWORD_FETCH_MODE)
        ) or self.DEFAULT_KEYWORD_FETCH_MODE

        if min_price > max_price:
            raise ResearchServiceError("min_price must be less than or equal to max_price.")
        if min_review_count > max_review_count:
            raise ResearchServiceError(
                "min_review_count must be less than or equal to max_review_count."
            )
        if min_offer_count > max_offer_count:
            raise ResearchServiceError(
                "min_offer_count must be less than or equal to max_offer_count."
            )
        if limit < 1 or limit > 100:
            raise ResearchServiceError("limit must be between 1 and 100.")
        if fetch_mode not in self.KEYWORD_FETCH_MODES:
            raise ResearchServiceError("fetch_mode must be light or detail.")

        category_id = self._clean_text(self._get_value(values, "category_id")) or None
        exclude_amazon_in_stock = self._parse_bool(
            self._get_value(
                values,
                "exclude_amazon_in_stock",
                DEFAULT_SETTINGS[AppSetting.KEY_EXCLUDE_AMAZON_IN_STOCK],
            )
        )

        return {
            "type": "keyword",
            "name": name or self.DEFAULT_KEYWORD_RUN_NAME,
            "keyword": keyword,
            "category_id": category_id,
            "filters": {
                "min_price": min_price,
                "max_price": max_price,
                "min_review_count": min_review_count,
                "max_review_count": max_review_count,
                "min_offer_count": min_offer_count,
                "max_offer_count": max_offer_count,
                "exclude_amazon_in_stock": exclude_amazon_in_stock,
                "min_sales_rank_drops_90": min_sales_rank_drops_90,
            },
            "limit": limit,
            "fetch_mode": fetch_mode,
        }

    def create_research_run_for_keyword(self, values: dict):
        conditions = self.build_keyword_conditions(values)
        research_run = ResearchRun(
            name=conditions["name"],
            keyword=conditions["keyword"],
            category_id=conditions["category_id"],
            status=ResearchRun.STATUS_PENDING,
            conditions_json=json.dumps(conditions, ensure_ascii=False),
            total_requested=conditions["limit"],
            total_fetched=0,
            total_saved=0,
            error_message=None,
            started_at=None,
            finished_at=None,
        )

        try:
            self._db_session.add(research_run)
            self._db_session.commit()
            return research_run
        except Exception as exc:
            self._db_session.rollback()
            raise ResearchServiceError("Failed to create keyword research run.") from exc

    def estimate_keyword_research_tokens(
        self,
        limit: int,
        offers: int = KEYWORD_DETAIL_OFFERS,
        tokens_left: int | None = None,
        fetch_mode: str = DEFAULT_KEYWORD_FETCH_MODE,
    ) -> dict:
        try:
            safe_limit = int(limit)
        except (TypeError, ValueError):
            safe_limit = 1
        safe_limit = max(1, min(safe_limit, 100))

        fetch_mode = fetch_mode if fetch_mode in self.KEYWORD_FETCH_MODES else self.DEFAULT_KEYWORD_FETCH_MODE
        # Keepa /search is cheap. Detail mode fetches offers, light mode keeps ASIN detail fetch lean.
        detail_per_asin = (
            self.KEYWORD_DETAIL_TOKEN_ESTIMATE_PER_ASIN
            if fetch_mode == "detail"
            else self.KEYWORD_LIGHT_DETAIL_TOKEN_ESTIMATE_PER_ASIN
        )
        search_tokens = self.KEYWORD_SEARCH_TOKEN_ESTIMATE
        detail_tokens = safe_limit * detail_per_asin
        estimated_total = search_tokens + detail_tokens

        recommended_limit = safe_limit
        if tokens_left is not None:
            try:
                available_tokens = max(0, int(tokens_left))
            except (TypeError, ValueError):
                available_tokens = 0
            remaining_for_details = max(0, available_tokens - search_tokens)
            recommended_limit = max(1, min(safe_limit, remaining_for_details // detail_per_asin))

        return {
            "search_tokens": search_tokens,
            "detail_tokens": detail_tokens,
            "detail_tokens_per_asin": detail_per_asin,
            "estimated_total": estimated_total,
            "recommended_limit": recommended_limit,
            "limit": safe_limit,
            "offers": offers,
            "fetch_mode": fetch_mode,
        }

    def check_keyword_research_token_preflight(
        self,
        limit: int,
        token_status: dict | None = None,
        fetch_mode: str = DEFAULT_KEYWORD_FETCH_MODE,
    ) -> dict:
        if token_status is None:
            token_status = self._get_keyword_token_status()

        tokens_left = self._extract_tokens_left(token_status)
        estimate = self.estimate_keyword_research_tokens(
            limit,
            tokens_left=tokens_left,
            fetch_mode=fetch_mode,
        )
        estimate["tokens_left"] = tokens_left
        estimate["can_check"] = token_status is not None and tokens_left is not None

        if not estimate["can_check"]:
            return estimate

        if max(0, int(tokens_left)) < estimate["estimated_total"]:
            raise ResearchServiceError(
                self.build_keyword_token_preflight_message(tokens_left, estimate),
                error_type="token_insufficient",
            )
        return estimate

    def build_keyword_token_guidance(self, token_status: dict | None = None) -> dict:
        if token_status is None:
            token_status = self._get_keyword_token_status()

        tokens_left = self._extract_tokens_left(token_status)
        estimate_for_five = self.estimate_keyword_research_tokens(5, tokens_left=tokens_left)

        if token_status is None or tokens_left is None:
            return {
                "available": False,
                "tokens_left": None,
                "tokens_available": None,
                "recommended_limit": 1,
                "estimated_for_limit_5": estimate_for_five["estimated_total"],
                "message": "トークン状態を取得できませんでした。キーワード検索は少数件で実行してください。",
            }

        tokens_available = max(0, int(tokens_left))
        if tokens_available < 10:
            recommended_limit = 1
            message = "現在のトークンでは、キーワード検索は1件程度がおすすめです。"
        elif tokens_available < 30:
            recommended_limit = 2
            message = "現在のトークンでは、キーワード検索は1〜2件程度がおすすめです。"
        else:
            recommended_limit = 5
            message = "現在のトークンでは、キーワード検索は5件程度までが目安です。"

        return {
            "available": True,
            "tokens_left": tokens_left,
            "tokens_available": tokens_available,
            "recommended_limit": recommended_limit,
            "estimated_for_limit_5": estimate_for_five["estimated_total"],
            "message": message,
        }

    def build_keyword_token_preflight_message(self, tokens_left, estimate: dict) -> str:
        tokens_available = 0
        try:
            tokens_available = max(0, int(tokens_left))
        except (TypeError, ValueError):
            pass

        return (
            f"現在使えるトークンは {tokens_available} です。"
            f"取得上限{estimate['limit']}件には約{estimate['estimated_total']}トークン以上を推奨します。"
            f"取得上限を{estimate['recommended_limit']}件に下げるか、"
            "トークン回復後に再実行してください。"
            "キーワード検索は検索後にASIN詳細を再取得するため、ASIN指定より多くのトークンを消費します。"
        )

    def mark_running(self, research_run):
        research_run.status = ResearchRun.STATUS_RUNNING
        research_run.started_at = datetime.utcnow()
        try:
            self._db_session.commit()
            return research_run
        except Exception as exc:
            self._db_session.rollback()
            raise ResearchServiceError("Failed to mark research run as running.") from exc

    def execute_asin_research(self, research_run_id):
        research_run = self._get_research_run_by_id(research_run_id)
        if research_run is None:
            raise ResearchServiceError("Research run was not found.")

        try:
            conditions = self._load_conditions(research_run.conditions_json)
            asins = conditions.get("asins") if isinstance(conditions, dict) else None
            if not isinstance(asins, list) or not asins:
                raise InvalidAsinInputError("No valid ASINs were provided.")

            self.mark_running(research_run)

            raw_products = self._keepa_client.get_products_by_asins(asins)
            total_fetched = len(raw_products)
            total_saved = 0

            for raw_product in raw_products:
                product_data = self._keepa_client.normalize_product(raw_product)
                product = self.save_or_update_product(product_data)
                self._scoring_service.apply_scoring(product)
                self.link_product_to_research_run(product, research_run)
                total_saved += 1

            return self.finish_research_run(
                research_run,
                total_fetched=total_fetched,
                total_saved=total_saved,
            )
        except Exception as exc:
            self._log_safe(
                "error",
                "ASIN research execution failed",
                research_run_id=getattr(research_run, "id", None),
                error=sanitize_error_message(exc),
                error_type=getattr(exc, "error_type", "unknown"),
            )
            self.fail_research_run(research_run, exc)
            raise ResearchServiceError("ASIN research execution failed.") from exc

    def execute_keyword_research(self, research_run_id):
        research_run = self._get_research_run_by_id(research_run_id)
        if research_run is None:
            raise ResearchServiceError("Research run was not found.")

        try:
            conditions = self._load_conditions(research_run.conditions_json)
            if conditions.get("type") != "keyword":
                raise ResearchServiceError("Research run is not a keyword research run.")

            keyword = self._clean_text(conditions.get("keyword"))
            if not keyword:
                raise ResearchServiceError("Keyword is required.")

            category_id = conditions.get("category_id")
            filters = conditions.get("filters") or {}
            if not isinstance(filters, dict):
                raise ResearchServiceError("Keyword research filters must be an object.")

            limit = conditions.get("limit", 100)
            try:
                limit = int(limit)
            except (TypeError, ValueError) as exc:
                raise ResearchServiceError("Keyword research limit must be an integer.") from exc
            if limit < 1 or limit > 100:
                raise ResearchServiceError("Keyword research limit must be between 1 and 100.")
            fetch_mode = conditions.get("fetch_mode", self.DEFAULT_KEYWORD_FETCH_MODE)
            fetch_mode = self._clean_text(fetch_mode) or self.DEFAULT_KEYWORD_FETCH_MODE
            if fetch_mode not in self.KEYWORD_FETCH_MODES:
                raise ResearchServiceError("Keyword research fetch_mode must be light or detail.")

            self.check_keyword_research_token_preflight(limit, fetch_mode=fetch_mode)
            self.mark_running(research_run)

            raw_products = self._keepa_client.search_products(
                keyword,
                category_id=category_id,
                limit=limit,
                filters=filters,
                fetch_mode=fetch_mode,
            )
            total_fetched = len(raw_products)
            total_saved = 0

            for raw_product in raw_products:
                product_data = self._keepa_client.normalize_product(raw_product)
                matches_filters = self.product_matches_keyword_filters(product_data, filters)

                product = self.save_or_update_product(product_data)
                self._scoring_service.apply_scoring(product)
                if not matches_filters:
                    product.judgement = Product.JUDGEMENT_BAD
                    product.status = Product.STATUS_EXCLUDED

                self.link_product_to_research_run(product, research_run)
                total_saved += 1

            return self.finish_research_run(
                research_run,
                total_fetched=total_fetched,
                total_saved=total_saved,
            )
        except Exception as exc:
            self._log_safe(
                "error",
                "Keyword research execution failed",
                research_run_id=getattr(research_run, "id", None),
                error=sanitize_error_message(exc),
                error_type=getattr(exc, "error_type", "unknown"),
            )
            self.fail_research_run(research_run, exc)
            raise ResearchServiceError("Keyword research execution failed.") from exc

    def product_matches_keyword_filters(self, product_data: dict, filters: dict) -> bool:
        filters = filters or {}

        checks = [
            ("current_price", "min_price", "min"),
            ("current_price", "max_price", "max"),
            ("review_count", "min_review_count", "min"),
            ("review_count", "max_review_count", "max"),
            ("new_offer_count", "min_offer_count", "min"),
            ("new_offer_count", "max_offer_count", "max"),
            ("sales_rank_drops_90", "min_sales_rank_drops_90", "min"),
        ]

        for product_key, filter_key, direction in checks:
            if filter_key not in filters or filters.get(filter_key) is None:
                continue
            product_value = self._optional_int(product_data.get(product_key))
            filter_value = self._optional_int(filters.get(filter_key))
            if product_value is None or filter_value is None:
                return False
            if direction == "min" and product_value < filter_value:
                return False
            if direction == "max" and product_value > filter_value:
                return False

        if self._parse_bool(filters.get("exclude_amazon_in_stock")):
            if product_data.get("amazon_in_stock") is True:
                return False

        return True

    def save_or_update_product(self, product_data: dict):
        try:
            asin = product_data.get("asin")
            if not asin:
                raise ResearchServiceError(
                    "Product data is missing ASIN.",
                    error_type="data_insufficient",
                )

            title = product_data.get("title") or "タイトル不明"
            product = Product.query.filter_by(asin=asin).first()
            now = datetime.utcnow()

            if product is None:
                product = Product(asin=asin, title=title)
                product.first_seen_at = now
                self._db_session.add(product)

            protected_fields = {
                "id",
                "created_at",
                "updated_at",
                "first_seen_at",
                "last_checked_at",
            }
            for key, value in product_data.items():
                if key in protected_fields:
                    continue
                if key == "title" and not value:
                    value = "タイトル不明"
                if hasattr(product, key):
                    setattr(product, key, value)

            product.last_checked_at = now
            if product.first_seen_at is None:
                product.first_seen_at = now
            return product
        except ResearchServiceError:
            raise
        except Exception as exc:
            self._db_session.rollback()
            self._log_safe(
                "exception",
                "Failed to save or update product",
                asin=product_data.get("asin") if isinstance(product_data, dict) else None,
                error=sanitize_error_message(exc),
            )
            raise ResearchServiceError(
                build_user_friendly_error_message("db_save_failed", exc),
                error_type="db_save_failed",
            ) from exc

    def link_product_to_research_run(self, product, research_run):
        existing = ProductResearchRun.query.filter_by(
            product_id=product.id,
            research_run_id=research_run.id,
        ).first()
        if existing is not None:
            return existing

        link = ProductResearchRun(product=product, research_run=research_run)
        self._db_session.add(link)
        return link

    def finish_research_run(self, research_run, total_fetched: int, total_saved: int):
        research_run.status = ResearchRun.STATUS_COMPLETED
        research_run.total_fetched = total_fetched
        research_run.total_saved = total_saved
        research_run.finished_at = datetime.utcnow()
        research_run.error_message = None

        try:
            self._db_session.commit()
            return research_run
        except Exception as exc:
            self._db_session.rollback()
            self._log_safe(
                "exception",
                "Failed to finish research run",
                research_run_id=getattr(research_run, "id", None),
                error=sanitize_error_message(exc),
            )
            raise ResearchServiceError(
                build_user_friendly_error_message("db_save_failed", exc),
                error_type="db_save_failed",
            ) from exc

    def fail_research_run(self, research_run, error):
        self._db_session.rollback()
        research_run.status = ResearchRun.STATUS_FAILED
        research_run.error_message = self._build_safe_error_message(error)
        research_run.finished_at = datetime.utcnow()

        try:
            self._db_session.commit()
            return research_run
        except Exception as exc:
            self._db_session.rollback()
            self._log_safe(
                "exception",
                "Failed to update research run as failed",
                research_run_id=getattr(research_run, "id", None),
                original_error=sanitize_error_message(error),
                db_error=sanitize_error_message(exc),
            )
            return research_run

    def _get_research_run_by_id(self, research_run_id):
        if hasattr(self._db_session, "get"):
            return self._db_session.get(ResearchRun, research_run_id)
        return ResearchRun.query.get(research_run_id)

    def _get_keyword_token_status(self) -> dict | None:
        get_token_status = getattr(self._keepa_client, "get_token_status", None)
        if not callable(get_token_status):
            return None
        try:
            try:
                return get_token_status(allow_depleted=True)
            except TypeError:
                return get_token_status()
        except Exception as exc:
            self._log_safe(
                "warning",
                "Keyword token preflight could not read token status",
                error=sanitize_error_message(exc),
                error_type=getattr(exc, "error_type", "unknown"),
            )
            return None

    @classmethod
    def _extract_tokens_left(cls, token_status: dict | None) -> int | None:
        if not isinstance(token_status, dict):
            return None
        value = token_status.get("tokens_left", token_status.get("tokensLeft"))
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _load_conditions(conditions_json: str | None) -> dict:
        if not conditions_json:
            raise ResearchServiceError("Research run conditions are empty.")
        try:
            conditions = json.loads(conditions_json)
        except (TypeError, ValueError) as exc:
            raise ResearchServiceError("Research run conditions are invalid JSON.") from exc
        if not isinstance(conditions, dict):
            raise ResearchServiceError("Research run conditions must be an object.")
        return conditions

    @staticmethod
    def _get_value(values, key: str, default=None):
        if values is None:
            return default
        if hasattr(values, "get"):
            value = values.get(key, default)
        else:
            value = default
        return default if value is None else value

    @staticmethod
    def _clean_text(value) -> str:
        return str(value).strip() if value is not None else ""

    @classmethod
    def _parse_required_int(cls, value, field_name: str) -> int:
        text = cls._clean_text(value)
        try:
            return int(text)
        except (TypeError, ValueError) as exc:
            raise ResearchServiceError(f"{field_name} must be an integer.") from exc

    @classmethod
    def _parse_bool(cls, value) -> bool:
        return cls._clean_text(value).lower() in {"true", "on", "1"}

    @classmethod
    def _optional_int(cls, value) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _sanitize_error_message(cls, error) -> str:
        return sanitize_error_message(error)

    @classmethod
    def _build_safe_error_message(cls, error) -> str:
        error_type = getattr(error, "error_type", "unknown")
        if error_type in {
            "missing_api_key",
            "invalid_api_key",
            "token_insufficient",
            "keepa_connection_failed",
            "keepa_api_failed",
            "db_save_failed",
            "csv_export_failed",
            "data_insufficient",
        }:
            return build_user_friendly_error_message(error_type)
        return build_user_friendly_error_message(error_type, error)

    @staticmethod
    def _log_safe(level: str, message: str, **context) -> None:
        if not has_app_context():
            return
        log_safe(current_app.logger, level, message, **context)
