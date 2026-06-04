import csv
from datetime import datetime
from pathlib import Path

from flask import current_app, has_app_context

from app.models import Product
from app.services.error_utils import (
    build_user_friendly_error_message,
    log_safe,
    mask_sensitive_text,
    sanitize_error_message,
)


class CsvExporterError(Exception):
    """CSV export common error."""


class CsvExporter:
    HEADERS = [
        "ASIN",
        "JAN",
        "商品名",
        "ブランド",
        "Amazon価格",
        "90日平均価格",
        "新品出品者数",
        "Amazon本体有無",
        "レビュー数",
        "評価",
        "90日ランキング変動回数",
        "価格安定スコア",
        "売れ行きスコア",
        "競合スコア",
        "リスクスコア",
        "Keepaスコア",
        "判定",
        "ステータス",
        "Amazon URL",
        "Keepa URL",
        "メモ",
        "取得日時",
    ]

    def __init__(self, export_dir: str | None = None):
        self.export_dir = Path(export_dir or "exports")
        try:
            self.export_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._log_csv_error("CSV export directory creation failed", error=exc)
            raise CsvExporterError(
                build_user_friendly_error_message("csv_export_failed", exc)
            ) from exc

    def build_default_filepath(self) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return str(self.export_dir / f"keepa_research_{timestamp}.csv")

    def export_products(self, products, filepath: str | None = None) -> str:
        try:
            output_path = Path(filepath or self.build_default_filepath())
            if output_path.parent:
                output_path.parent.mkdir(parents=True, exist_ok=True)

            with output_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(self.HEADERS)
                for product in products or []:
                    writer.writerow(self._build_row(product))
        except (OSError, csv.Error, Exception) as exc:
            self._log_csv_error(
                "CSV export failed",
                filepath=str(filepath) if filepath else None,
                error=exc,
            )
            raise CsvExporterError(
                build_user_friendly_error_message("csv_export_failed", exc)
            ) from exc

        return str(output_path)

    def export_candidates(self, filepath: str | None = None) -> str:
        products = Product.query.filter_by(status=Product.STATUS_CANDIDATE).all()
        return self.export_products(products, filepath=filepath)

    def _build_row(self, product) -> list[str]:
        return [
            self._format_value(product.asin),
            self._format_value(product.jan or product.ean),
            self._format_value(product.title),
            self._format_value(product.brand),
            self._format_value(product.current_price),
            self._format_value(product.avg_price_90),
            self._format_value(product.new_offer_count),
            self._format_value(product.amazon_in_stock),
            self._format_value(product.review_count),
            self._format_value(product.rating),
            self._format_value(product.sales_rank_drops_90),
            self._format_value(product.price_stability_score),
            self._format_value(product.sales_score),
            self._format_value(product.competition_score),
            self._format_value(product.risk_score),
            self._format_value(product.keepa_score),
            self._format_value(product.judgement),
            self._format_value(product.status),
            self._format_value(product.amazon_url),
            self._format_value(product.keepa_url),
            self._format_value(product.memo),
            self._format_value(product.last_checked_at),
        ]

    @staticmethod
    def _format_value(value) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            return str(value)
        return mask_sensitive_text(value)

    @staticmethod
    def _log_csv_error(message: str, **context) -> None:
        if not has_app_context():
            return
        safe_context = {
            key: sanitize_error_message(value) if key == "error" else value
            for key, value in context.items()
        }
        log_safe(current_app.logger, "error", message, **safe_context)
