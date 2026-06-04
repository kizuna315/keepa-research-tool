import os

from flask import Blueprint, current_app, flash, redirect, render_template, request, send_file, url_for

from app.extensions import db
from app.models import Product
from app.services.csv_exporter import CsvExporter, CsvExporterError
from app.services.error_utils import (
    build_user_friendly_error_message,
    log_safe,
    sanitize_error_message,
)
from app.services.scoring_service import ScoringService


products_bp = Blueprint("products", __name__, url_prefix="/products")
ALLOWED_PRODUCT_STATUSES = {
    Product.STATUS_UNREVIEWED,
    Product.STATUS_CANDIDATE,
    Product.STATUS_HOLD,
    Product.STATUS_EXCLUDED,
    Product.STATUS_SUPPLIER_SEARCH_PENDING,
}
ALLOWED_JUDGEMENTS = {
    Product.JUDGEMENT_GOOD,
    Product.JUDGEMENT_WATCH,
    Product.JUDGEMENT_BAD,
    Product.JUDGEMENT_UNKNOWN,
}
DEFAULT_SORT = "last_checked_desc"
ALLOWED_SORTS = {
    "last_checked_desc",
    "score_desc",
    "sales_rank_drops_desc",
    "price_stability_desc",
    "new_offer_count_asc",
}


def _parse_int(value):
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    try:
        return int(text)
    except ValueError:
        return None


@products_bp.route("/", methods=["GET"], strict_slashes=False)
def list_products():
    query = Product.query

    status = request.args.get("status", "").strip()
    if status in ALLOWED_PRODUCT_STATUSES:
        query = query.filter(Product.status == status)
    else:
        status = ""

    judgement = request.args.get("judgement", "").strip()
    if judgement in ALLOWED_JUDGEMENTS:
        query = query.filter(Product.judgement == judgement)
    else:
        judgement = ""

    brand = request.args.get("brand", "").strip()
    if brand:
        query = query.filter(Product.brand.ilike(f"%{brand}%"))

    min_score_raw = request.args.get("min_score", "").strip()
    min_score = _parse_int(min_score_raw)
    if min_score is not None:
        query = query.filter(Product.keepa_score >= min_score)

    max_score_raw = request.args.get("max_score", "").strip()
    max_score = _parse_int(max_score_raw)
    if max_score is not None:
        query = query.filter(Product.keepa_score <= max_score)

    sort = request.args.get("sort", DEFAULT_SORT).strip()
    if sort not in ALLOWED_SORTS:
        sort = DEFAULT_SORT

    if sort == "score_desc":
        query = query.order_by(
            Product.keepa_score.desc(),
            Product.last_checked_at.desc(),
            Product.created_at.desc(),
        )
    elif sort == "sales_rank_drops_desc":
        query = query.order_by(
            Product.sales_rank_drops_90.desc(),
            Product.last_checked_at.desc(),
            Product.created_at.desc(),
        )
    elif sort == "price_stability_desc":
        query = query.order_by(
            Product.price_stability_score.desc(),
            Product.last_checked_at.desc(),
            Product.created_at.desc(),
        )
    elif sort == "new_offer_count_asc":
        query = query.order_by(
            Product.new_offer_count.asc(),
            Product.last_checked_at.desc(),
            Product.created_at.desc(),
        )
    else:
        query = query.order_by(Product.last_checked_at.desc(), Product.created_at.desc())

    products = query.limit(100).all()
    filters = {
        "status": status,
        "judgement": judgement,
        "brand": brand,
        "min_score": min_score_raw,
        "max_score": max_score_raw,
        "sort": sort,
    }
    return render_template(
        "products_list.html",
        products=products,
        filters=filters,
    )


@products_bp.route("/export", methods=["GET"])
def export_products_csv():
    target = request.args.get("target", "all").strip()
    if target not in {"all", "candidates"}:
        flash("CSV出力対象が不正です。", "warning")
        return redirect(url_for("products.list_products"))

    try:
        exporter = CsvExporter()
        if target == "candidates":
            filepath = exporter.export_candidates()
        else:
            products = (
                Product.query.order_by(Product.last_checked_at.desc(), Product.created_at.desc())
                .all()
            )
            filepath = exporter.export_products(products)

        absolute_filepath = os.path.abspath(filepath)
        return send_file(
            absolute_filepath,
            mimetype="text/csv; charset=utf-8",
            as_attachment=True,
            download_name=os.path.basename(filepath),
        )
    except (CsvExporterError, Exception) as exc:
        log_safe(
            current_app.logger,
            "error",
            "CSV export route failed",
            target=target,
            error=sanitize_error_message(exc),
        )
        flash(build_user_friendly_error_message("csv_export_failed"), "danger")
        return redirect(url_for("products.list_products"))


@products_bp.route("/<int:product_id>", methods=["GET"])
def detail_product(product_id):
    product = Product.query.get_or_404(product_id)
    judgement_reasons = ScoringService().build_judgement_reasons(product)
    return render_template(
        "products_detail.html",
        product=product,
        judgement_reasons=judgement_reasons,
    )


@products_bp.route("/<int:product_id>/update", methods=["POST"])
def update_product(product_id):
    product = Product.query.get_or_404(product_id)
    status = request.form.get("status", "").strip()
    memo = request.form.get("memo", "")

    if status not in ALLOWED_PRODUCT_STATUSES:
        flash("不正なステータスが指定されました。", "danger")
        return redirect(url_for("products.detail_product", product_id=product.id))

    product.status = status
    product.memo = memo
    try:
        db.session.commit()
        flash("商品情報を保存しました。", "success")
    except Exception as exc:
        db.session.rollback()
        log_safe(
            current_app.logger,
            "error",
            "Product update failed",
            product_id=product.id,
            error=sanitize_error_message(exc),
        )
        flash(build_user_friendly_error_message("db_save_failed"), "danger")

    return redirect(url_for("products.detail_product", product_id=product.id))


