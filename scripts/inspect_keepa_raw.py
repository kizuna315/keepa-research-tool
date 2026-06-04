from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app
from app.models import Product
from app.services.keepa_client import KeepaClient

INSPECT_FIELDS = [
    "asin",
    "title",
    "current_price",
    "avg_price_30",
    "avg_price_90",
    "lowest_price_90",
    "highest_price_90",
    "sales_rank_drops_30",
    "sales_rank_drops_90",
    "new_offer_count",
    "fba_offer_count",
    "amazon_in_stock",
    "amazon_was_in_stock_90",
    "review_count",
    "rating",
    "price_stability_score",
    "sales_score",
    "competition_score",
    "risk_score",
    "keepa_score",
    "judgement",
    "status",
    "raw_keepa_json",
]

RAW_KEYS_OF_INTEREST = [
    "stats",
    "csv",
    "data",
    "offers",
    "buyBoxSellerIdHistory",
    "liveOffersOrder",
    "imagesCSV",
    "images",
    "reviews",
    "reviewCount",
    "rating",
    "hasReviews",
    "salesRanks",
    "newOfferCount",
    "offerCount",
    "availabilityAmazon",
]

STATS_KEYS_OF_INTEREST = [
    "current",
    "avg30",
    "avg90",
    "min",
    "max",
    "minInInterval",
    "maxInInterval",
    "salesRankDrops30",
    "salesRankDrops90",
    "totalOfferCount",
    "retrievedOfferCount",
    "offerCountFBA",
    "offerCountFBM",
    "buyBoxIsAmazon",
    "outOfStockPercentage90",
    "outOfStockCountAmazon90",
]


def safe_type(value):
    if value is None:
        return "none"
    if isinstance(value, list):
        return f"list[{len(value)}]"
    if isinstance(value, dict):
        return f"dict[{len(value)}]"
    return type(value).__name__


def compact_sequence(value, limit=12):
    if not isinstance(value, list):
        return safe_type(value)
    return [safe_type(item) if isinstance(item, (list, dict)) else item for item in value[:limit]]


def load_raw(product):
    if not product.raw_keepa_json:
        return None
    try:
        raw = json.loads(product.raw_keepa_json)
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def main():
    app = create_app()
    with app.app_context():
        products = (
            Product.query.order_by(Product.last_checked_at.desc(), Product.created_at.desc())
            .limit(10)
            .all()
        )
        print(f"products inspected: {len(products)}")
        print("Note: raw JSON bodies and secret-like values are not printed.\n")

        null_counts = Counter()
        raw_key_counts = Counter()
        stats_key_counts = Counter()

        for product in products:
            for field in INSPECT_FIELDS:
                if getattr(product, field) is None:
                    null_counts[field] += 1
            raw = load_raw(product)
            if raw:
                raw_key_counts.update(raw.keys())
                stats = raw.get("stats")
                if isinstance(stats, dict):
                    stats_key_counts.update(stats.keys())

        print("DB null counts:")
        for field in INSPECT_FIELDS:
            print(f"  {field}: {null_counts[field]}")

        print("\nRaw key presence:")
        for key in RAW_KEYS_OF_INTEREST:
            print(f"  {key}: {raw_key_counts[key]}/{len(products)}")

        print("\nStats key presence:")
        for key in STATS_KEYS_OF_INTEREST:
            print(f"  {key}: {stats_key_counts[key]}/{len(products)}")

        client = KeepaClient(settings_service=type("NoSettings", (), {"get": staticmethod(lambda key, default=None: default)})())
        print("\nPer-product extraction comparison:")
        for product in products:
            raw = load_raw(product)
            if not raw:
                print(f"ASIN {product.asin}: raw missing or invalid")
                continue
            stats = raw.get("stats") if isinstance(raw.get("stats"), dict) else {}
            print(f"ASIN: {product.asin}")
            print(f"  stored: current={product.current_price}, avg90={product.avg_price_90}, "
                  f"low90={product.lowest_price_90}, high90={product.highest_price_90}, "
                  f"offers={product.new_offer_count}, fba={product.fba_offer_count}, "
                  f"amazon={product.amazon_in_stock}, amazon90={product.amazon_was_in_stock_90}, "
                  f"reviews={product.review_count}, rating={product.rating}, "
                  f"price_score={product.price_stability_score}, competition_score={product.competition_score}, "
                  f"risk_score={product.risk_score}, score={product.keepa_score}, "
                  f"judgement={product.judgement}, status={product.status}, "
                  f"last_checked_at={product.last_checked_at}")
            print(f"  top-level keys sample: {sorted(raw.keys())[:35]}")
            print(f"  stats keys sample: {sorted(stats.keys())[:35]}")
            for key in ["current", "avg30", "avg90", "min", "max", "minInInterval", "maxInInterval"]:
                print(f"  stats.{key}: {compact_sequence(stats.get(key))}")
            for key in ["totalOfferCount", "retrievedOfferCount", "offerCountFBA", "offerCountFBM", "outOfStockPercentage90", "outOfStockCountAmazon90", "buyBoxIsAmazon"]:
                print(f"  stats.{key}: {stats.get(key)}")
            print(f"  raw.availabilityAmazon: {raw.get('availabilityAmazon')}")
            print(f"  raw.hasReviews: {raw.get('hasReviews')}, raw.rating exists: {'rating' in raw}, raw.reviews exists: {'reviews' in raw}")
            normalized = client.normalize_product(raw)
            print(f"  current normalize result: current={normalized.get('current_price')}, avg90={normalized.get('avg_price_90')}, "
                  f"low90={normalized.get('lowest_price_90')}, high90={normalized.get('highest_price_90')}, "
                  f"offers={normalized.get('new_offer_count')}, fba={normalized.get('fba_offer_count')}, "
                  f"amazon={normalized.get('amazon_in_stock')}, amazon90={normalized.get('amazon_was_in_stock_90')}, "
                  f"reviews={normalized.get('review_count')}, rating={normalized.get('rating')}")
            print()

        print("KeepaClient product request params currently include:")
        print("  asin, stats=90, offers=20, plus automatic key/domain")
        print("Potential missing params to verify with Keepa docs/API sample:")
        print("  history, buybox, rating")


if __name__ == "__main__":
    main()
