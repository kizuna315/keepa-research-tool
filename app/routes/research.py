from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.models import AppSetting, ResearchRun
from app.services.research_service import (
    InvalidAsinInputError,
    ResearchService,
    ResearchServiceError,
)
from app.services.settings_defaults import DEFAULT_SETTINGS


research_bp = Blueprint("research", __name__, url_prefix="/research")


def _get_recent_research_runs(limit: int = 10):
    return ResearchRun.query.order_by(ResearchRun.created_at.desc()).limit(limit).all()


def _default_keyword_values() -> dict:
    return {
        "name": "",
        "keyword": "",
        "category_id": "",
        "min_price": DEFAULT_SETTINGS[AppSetting.KEY_DEFAULT_MIN_PRICE],
        "max_price": DEFAULT_SETTINGS[AppSetting.KEY_DEFAULT_MAX_PRICE],
        "min_review_count": "10",
        "max_review_count": "99999",
        "min_offer_count": DEFAULT_SETTINGS[AppSetting.KEY_DEFAULT_MIN_OFFER_COUNT],
        "max_offer_count": DEFAULT_SETTINGS[AppSetting.KEY_DEFAULT_MAX_OFFER_COUNT],
        "exclude_amazon_in_stock": DEFAULT_SETTINGS[AppSetting.KEY_EXCLUDE_AMAZON_IN_STOCK],
        "min_sales_rank_drops_90": DEFAULT_SETTINGS[
            AppSetting.KEY_DEFAULT_MIN_SALES_RANK_DROPS_90
        ],
        "limit": "100",
        "fetch_mode": "light",
    }


def _keyword_values_from_form(form) -> dict:
    values = _default_keyword_values()
    for key in values:
        if key == "exclude_amazon_in_stock":
            values[key] = form.get(key, "false")
        else:
            values[key] = form.get(key, values[key])
    return values


def _get_keyword_token_guidance():
    try:
        service = ResearchService()
        if hasattr(service, "build_keyword_token_guidance"):
            return service.build_keyword_token_guidance()
    except Exception:
        pass
    return {
        "available": False,
        "tokens_left": None,
        "tokens_available": None,
        "recommended_limit": 1,
        "estimated_for_limit_5": 31,
        "message": "トークン状態を取得できませんでした。キーワード検索は少数件で実行してください。",
    }


def _render_new_research(**context):
    defaults = {
        "name": "",
        "asin_text": "",
        "keyword_values": _default_keyword_values(),
        "recent_runs": _get_recent_research_runs(),
        "keyword_token_guidance": _get_keyword_token_guidance(),
    }
    defaults.update(context)
    return render_template("research_new.html", **defaults)


@research_bp.route("/new", methods=["GET", "POST"])
def new_research():
    if request.method == "GET":
        return _render_new_research()

    research_type = request.form.get("research_type", "asin").strip() or "asin"
    service = ResearchService()

    if research_type == "asin":
        name = request.form.get("name", "").strip()
        asin_text = request.form.get("asin_text", "")
        try:
            research_run = service.create_research_run_for_asins(name, asin_text)
            service.execute_asin_research(research_run.id)
            flash("ASINリサーチが完了しました。", "success")
            return redirect(url_for("research.new_research"))
        except (InvalidAsinInputError, ResearchServiceError):
            flash(
                "ASINリサーチに失敗しました。入力内容またはKeepa API設定を確認してください。",
                "danger",
            )
            return _render_new_research(name=name, asin_text=asin_text)

    if research_type == "keyword":
        keyword_values = _keyword_values_from_form(request.form)
        try:
            if hasattr(service, "build_keyword_conditions") and hasattr(
                service, "check_keyword_research_token_preflight"
            ):
                conditions = service.build_keyword_conditions(keyword_values)
                service.check_keyword_research_token_preflight(
                    conditions["limit"],
                    fetch_mode=conditions.get("fetch_mode", "light"),
                )
            research_run = service.create_research_run_for_keyword(request.form)
            service.execute_keyword_research(research_run.id)
            flash("キーワード検索リサーチが完了しました。", "success")
            return redirect(url_for("research.new_research"))
        except ResearchServiceError as exc:
            if getattr(exc, "error_type", "") == "token_insufficient":
                flash(str(exc), "warning")
            else:
                flash(
                    "キーワード検索リサーチに失敗しました。入力内容またはKeepa API設定を確認してください。",
                    "danger",
                )
            return _render_new_research(keyword_values=keyword_values)

    flash("不明なリサーチ種別が指定されました。", "danger")
    return _render_new_research(
        name=request.form.get("name", "").strip(),
        asin_text=request.form.get("asin_text", ""),
        keyword_values=_keyword_values_from_form(request.form),
    )

