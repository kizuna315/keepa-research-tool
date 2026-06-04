from datetime import datetime

from flask import Blueprint, render_template
from sqlalchemy.exc import SQLAlchemyError

from app.models import Product, ResearchRun
from app.services.keepa_client import (
    KeepaApiKeyMissingError,
    KeepaClient,
    KeepaClientError,
    KeepaTokenError,
)


dashboard_bp = Blueprint("dashboard", __name__)


def format_seconds(seconds):
    if seconds is None:
        return "不明"
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return "不明"

    if seconds < 0:
        return "不明"

    minutes = seconds // 60
    remaining_seconds = seconds % 60

    if minutes > 0:
        return f"{minutes}分{remaining_seconds}秒"
    return f"{remaining_seconds}秒"


def _normalize_refill_seconds(value):
    if value is None:
        return None
    try:
        refill = int(value)
    except (TypeError, ValueError):
        return None
    if refill < 0:
        return None

    # Keepa's refillIn is commonly milliseconds; tests and summaries may pass seconds.
    if refill >= 1000:
        return max(1, round(refill / 1000))
    return refill


def _empty_stats():
    return {
        "total_products": 0,
        "candidate_products": 0,
        "hold_products": 0,
        "excluded_products": 0,
        "unreviewed_products": 0,
        "supplier_search_pending_products": 0,
        "latest_research": None,
        "latest_research_status": None,
        "latest_research_started_at": None,
        "latest_research_finished_at": None,
        "today_products": 0,
        "failed_research_runs": 0,
    }


def _keyword_limit_recommendation(tokens_available):
    if tokens_available is None:
        return "キーワード検索は少数件で実行してください。"
    try:
        tokens = int(tokens_available)
    except (TypeError, ValueError):
        return "キーワード検索は少数件で実行してください。"

    if tokens < 10:
        return "キーワード検索は1件までが目安です。"
    if tokens < 30:
        return "キーワード検索は1〜2件までが目安です。"
    return "キーワード検索は5件程度までが目安です。"


def _get_keepa_token_summary():
    summary = {
        "keepa_token_status": "unavailable",
        "keepa_tokens_left": None,
        "keepa_tokens_available": None,
        "keepa_refill_rate": None,
        "keepa_refill_in": None,
        "keepa_refill_seconds": None,
        "keepa_refill_display": "不明",
        "keepa_token_error": "Keepa APIトークン情報を取得できませんでした。",
        "keyword_limit_recommendation": "キーワード検索は少数件で実行してください。",
    }

    try:
        try:
            token_status = KeepaClient().get_token_status(allow_depleted=True)
        except TypeError:
            # Tests may monkeypatch the method with the original no-argument shape.
            token_status = KeepaClient().get_token_status()
    except KeepaApiKeyMissingError:
        summary["keepa_token_error"] = "Keepa API Keyが未設定です。"
        return summary
    except KeepaTokenError:
        summary["keepa_token_error"] = "Keepa APIトークンが不足しています。"
        return summary
    except KeepaClientError:
        return summary
    except Exception:
        return summary

    tokens_left = token_status.get("tokens_left")
    summary["keepa_token_status"] = "depleted" if tokens_left is not None and tokens_left <= 0 else "available"
    summary["keepa_tokens_left"] = tokens_left
    summary["keepa_tokens_available"] = max(0, tokens_left) if tokens_left is not None else None
    summary["keyword_limit_recommendation"] = _keyword_limit_recommendation(
        summary["keepa_tokens_available"]
    )
    summary["keepa_refill_rate"] = token_status.get("refill_rate")
    summary["keepa_refill_in"] = token_status.get("refill_in")
    refill_seconds = _normalize_refill_seconds(
        token_status.get("time_to_refill", token_status.get("refill_in"))
    )
    summary["keepa_refill_seconds"] = refill_seconds
    summary["keepa_refill_display"] = format_seconds(refill_seconds)
    if tokens_left is not None and tokens_left <= 0:
        summary["keepa_token_error"] = "Keepa APIトークンが不足しています。"
    else:
        summary["keepa_token_error"] = None
    return summary


@dashboard_bp.get("/")
def index():
    recent_research_runs = []
    recent_products = []

    try:
        latest_research = ResearchRun.query.order_by(ResearchRun.created_at.desc()).first()
        recent_research_runs = (
            ResearchRun.query.order_by(ResearchRun.created_at.desc()).limit(5).all()
        )
        recent_products = (
            Product.query.order_by(Product.last_checked_at.desc(), Product.created_at.desc())
            .limit(5)
            .all()
        )
        today_start = datetime.utcnow().replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        stats = {
            "total_products": Product.query.count(),
            "candidate_products": Product.query.filter_by(
                status=Product.STATUS_CANDIDATE
            ).count(),
            "hold_products": Product.query.filter_by(status=Product.STATUS_HOLD).count(),
            "excluded_products": Product.query.filter_by(
                status=Product.STATUS_EXCLUDED
            ).count(),
            "unreviewed_products": Product.query.filter_by(
                status=Product.STATUS_UNREVIEWED
            ).count(),
            "supplier_search_pending_products": Product.query.filter_by(
                status=Product.STATUS_SUPPLIER_SEARCH_PENDING
            ).count(),
            "latest_research": latest_research.name if latest_research else None,
            "latest_research_status": latest_research.status if latest_research else None,
            "latest_research_started_at": (
                latest_research.started_at if latest_research else None
            ),
            "latest_research_finished_at": (
                latest_research.finished_at if latest_research else None
            ),
            "today_products": Product.query.filter(
                Product.created_at >= today_start
            ).count(),
            "failed_research_runs": ResearchRun.query.filter_by(
                status=ResearchRun.STATUS_FAILED
            ).count(),
        }
    except SQLAlchemyError:
        stats = _empty_stats()

    stats.update(_get_keepa_token_summary())
    if stats.get("keepa_tokens_available") is None and stats.get("keepa_tokens_left") is not None:
        stats["keepa_tokens_available"] = max(0, stats["keepa_tokens_left"])
    if not stats.get("keepa_refill_display"):
        stats["keepa_refill_display"] = format_seconds(
            _normalize_refill_seconds(stats.get("keepa_refill_in"))
        )
    if not stats.get("keyword_limit_recommendation"):
        stats["keyword_limit_recommendation"] = _keyword_limit_recommendation(
            stats.get("keepa_tokens_available")
        )
    return render_template(
        "dashboard.html",
        stats=stats,
        recent_research_runs=recent_research_runs,
        recent_products=recent_products,
    )
