from __future__ import annotations

from app.models import Product


class ScoringService:
    @staticmethod
    def _to_int_or_none(value):
        try:
            if value is None:
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_float_or_none(value):
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_bool_or_none(value):
        if isinstance(value, bool):
            return value
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off"}:
                return False
        return None

    @staticmethod
    def calculate_sales_score(product) -> int:
        drops_90 = ScoringService._to_int_or_none(getattr(product, "sales_rank_drops_90", None))

        if drops_90 is None:
            return 0
        if drops_90 <= 3:
            return 0
        if drops_90 <= 9:
            return 10
        if drops_90 <= 19:
            return 25
        if drops_90 <= 49:
            return 35
        return 40

    @staticmethod
    def calculate_price_stability_score(product) -> int:
        current_price = ScoringService._to_float_or_none(getattr(product, "current_price", None))
        avg_price_90 = ScoringService._to_float_or_none(getattr(product, "avg_price_90", None))
        lowest_price_90 = ScoringService._to_float_or_none(getattr(product, "lowest_price_90", None))
        highest_price_90 = ScoringService._to_float_or_none(getattr(product, "highest_price_90", None))

        if (
            current_price is None
            or avg_price_90 is None
            or lowest_price_90 is None
            or highest_price_90 is None
        ):
            return 0

        if avg_price_90 <= 0:
            return 0

        price_drop_rate = (avg_price_90 - current_price) / avg_price_90
        price_range_rate = (highest_price_90 - lowest_price_90) / avg_price_90

        if price_drop_rate <= 0.05 and price_range_rate <= 0.20:
            return 25
        if price_drop_rate <= 0.10:
            return 18
        if price_drop_rate <= 0.20:
            return 10
        return 0

    @staticmethod
    def calculate_competition_score(product) -> int:
        new_offer_count = ScoringService._to_int_or_none(getattr(product, "new_offer_count", None))

        if new_offer_count is None:
            return 0
        if new_offer_count <= 0:
            return 0
        if new_offer_count == 1:
            return 5
        if new_offer_count == 2:
            return 15
        if 3 <= new_offer_count <= 10:
            return 25
        if 11 <= new_offer_count <= 15:
            return 20
        if 16 <= new_offer_count <= 30:
            return 10
        return 0

    @staticmethod
    def calculate_risk_score(product) -> int:
        amazon_in_stock = ScoringService._to_bool_or_none(getattr(product, "amazon_in_stock", None))
        amazon_was_in_stock_90 = ScoringService._to_bool_or_none(
            getattr(product, "amazon_was_in_stock_90", None)
        )

        if amazon_in_stock is True:
            return 0
        if amazon_in_stock is False and amazon_was_in_stock_90 is False:
            return 10
        if amazon_in_stock is False and amazon_was_in_stock_90 is True:
            return 5
        return 0

    @staticmethod
    def calculate_keepa_score(product) -> int:
        sales_score = ScoringService.calculate_sales_score(product)
        price_stability_score = ScoringService.calculate_price_stability_score(product)
        competition_score = ScoringService.calculate_competition_score(product)
        risk_score = ScoringService.calculate_risk_score(product)

        return sales_score + price_stability_score + competition_score + risk_score

    @staticmethod
    def has_required_data(product) -> bool:
        required_fields = [
            "current_price",
            "avg_price_90",
            "sales_rank_drops_90",
            "new_offer_count",
            "amazon_in_stock",
        ]
        return all(getattr(product, field, None) is not None for field in required_fields)

    @staticmethod
    def judge_product(product) -> str:
        if not ScoringService.has_required_data(product):
            return Product.JUDGEMENT_UNKNOWN

        keepa_score = ScoringService.calculate_keepa_score(product)
        if keepa_score >= 80:
            return Product.JUDGEMENT_GOOD
        if keepa_score >= 60:
            return Product.JUDGEMENT_WATCH
        return Product.JUDGEMENT_BAD

    @staticmethod
    def default_status_for_judgement(judgement: str) -> str:
        if judgement == Product.JUDGEMENT_GOOD:
            return Product.STATUS_CANDIDATE
        if judgement == Product.JUDGEMENT_WATCH:
            return Product.STATUS_UNREVIEWED
        if judgement == Product.JUDGEMENT_BAD:
            return Product.STATUS_EXCLUDED
        return Product.STATUS_HOLD

    @staticmethod
    def apply_scoring(product):
        product.sales_score = ScoringService.calculate_sales_score(product)
        product.price_stability_score = ScoringService.calculate_price_stability_score(product)
        product.competition_score = ScoringService.calculate_competition_score(product)
        product.risk_score = ScoringService.calculate_risk_score(product)
        product.keepa_score = (
            product.sales_score
            + product.price_stability_score
            + product.competition_score
            + product.risk_score
        )
        product.judgement = ScoringService.judge_product(product)
        product.status = ScoringService.default_status_for_judgement(product.judgement)
        return product

    @staticmethod
    def build_judgement_reasons(product) -> list[str]:
        reasons: list[str] = []

        sales_rank_drops_90 = ScoringService._to_int_or_none(
            getattr(product, "sales_rank_drops_90", None)
        )
        sales_score = ScoringService.calculate_sales_score(product)
        if sales_rank_drops_90 is None:
            reasons.append("ランキング変動データが不足しています。")
        elif sales_rank_drops_90 <= 3:
            reasons.append("90日ランキング変動が少なく、売れ行きは弱い可能性があります。")
        elif sales_rank_drops_90 <= 9:
            reasons.append("90日ランキング変動はありますが、売れ行きはまだ弱めです。")
        else:
            reasons.append(
                f"90日ランキング変動が{sales_rank_drops_90}回あり、売れている可能性があります。"
            )
        reasons.append(f"売れ行きスコアは{sales_score}点です。")

        current_price = ScoringService._to_float_or_none(getattr(product, "current_price", None))
        avg_price_90 = ScoringService._to_float_or_none(getattr(product, "avg_price_90", None))
        lowest_price_90 = ScoringService._to_float_or_none(getattr(product, "lowest_price_90", None))
        highest_price_90 = ScoringService._to_float_or_none(getattr(product, "highest_price_90", None))
        price_stability_score = ScoringService.calculate_price_stability_score(product)
        if (
            current_price is None
            or avg_price_90 is None
            or lowest_price_90 is None
            or highest_price_90 is None
            or avg_price_90 <= 0
        ):
            reasons.append("価格履歴データが不足しています。")
        elif price_stability_score >= 25:
            reasons.append("価格は90日平均と比較して安定しています。")
        elif price_stability_score >= 10:
            reasons.append("価格はやや変動しています。")
        else:
            reasons.append("価格下落または価格変動が大きい可能性があります。")
        reasons.append(f"価格安定スコアは{price_stability_score}点です。")

        new_offer_count = ScoringService._to_int_or_none(getattr(product, "new_offer_count", None))
        competition_score = ScoringService.calculate_competition_score(product)
        if new_offer_count is None:
            reasons.append("新品出品者数データが不足しています。")
        elif new_offer_count == 1:
            reasons.append(
                "新品出品者数が1人のため、独占・規制・売れにくさに注意が必要です。"
            )
        elif new_offer_count == 2:
            reasons.append("新品出品者数が2人で、競合は少なめです。")
        elif 3 <= new_offer_count <= 15:
            reasons.append(f"新品出品者数が{new_offer_count}人で、初心者でも確認しやすい範囲です。")
        elif 16 <= new_offer_count <= 30:
            reasons.append(f"新品出品者数が{new_offer_count}人で、値下げ競争に注意が必要です。")
        else:
            reasons.append(f"新品出品者数が{new_offer_count}人と多く、値下げ競争のリスクがあります。")
        reasons.append(f"競合スコアは{competition_score}点です。")

        amazon_in_stock = ScoringService._to_bool_or_none(getattr(product, "amazon_in_stock", None))
        amazon_was_in_stock_90 = ScoringService._to_bool_or_none(
            getattr(product, "amazon_was_in_stock_90", None)
        )
        risk_score = ScoringService.calculate_risk_score(product)
        if amazon_in_stock is True:
            reasons.append("Amazon本体が現在在庫を持っているため注意が必要です。")
        elif amazon_in_stock is False and amazon_was_in_stock_90 is True:
            reasons.append("Amazon本体は現在いませんが、過去90日に在庫があった可能性があります。")
        elif amazon_in_stock is False and amazon_was_in_stock_90 is False:
            reasons.append("Amazon本体は現在も過去90日も在庫なしです。")
        else:
            reasons.append("Amazon本体の在庫データが不足しています。")
        reasons.append(f"リスクスコアは{risk_score}点です。")

        keepa_score = ScoringService.calculate_keepa_score(product)
        judgement = ScoringService.judge_product(product)
        reasons.append(f"総合Keepaスコアは{keepa_score}点で、判定は{judgement}です。")
        return reasons
