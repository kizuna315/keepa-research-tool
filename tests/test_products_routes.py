import csv
from datetime import datetime, timedelta

import pytest

from app.extensions import db
from app.models import Product
from app.services.csv_exporter import CsvExporter, CsvExporterError


@pytest.fixture()
def db_schema(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        yield
        db.session.remove()
        db.drop_all()


def _create_product(**kwargs):
    defaults = {
        "asin": "B0TEST0001",
        "title": "Sample Product",
        "jan": "4900000000001",
        "ean": "4900000000001",
        "brand": "Sample Brand",
        "manufacturer": "Sample Maker",
        "category_id": "123",
        "category_name": "Category A",
        "image_url": "https://example.com/image.jpg",
        "amazon_url": "https://www.amazon.co.jp/dp/B0TEST0001",
        "keepa_url": "https://keepa.com/#!product/5-B0TEST0001",
        "current_price": 1980,
        "avg_price_30": 1990,
        "avg_price_90": 2100,
        "lowest_price_90": 1900,
        "highest_price_90": 2200,
        "sales_rank_current": 1000,
        "sales_rank_avg_30": 1100,
        "sales_rank_avg_90": 1200,
        "sales_rank_drops_30": 8,
        "sales_rank_drops_90": 24,
        "new_offer_count": 7,
        "used_offer_count": 1,
        "fba_offer_count": 5,
        "amazon_in_stock": False,
        "amazon_was_in_stock_90": False,
        "review_count": 123,
        "rating": 4.5,
        "sales_score": 35,
        "price_stability_score": 25,
        "competition_score": 25,
        "risk_score": 10,
        "keepa_score": 95,
        "judgement": Product.JUDGEMENT_GOOD,
        "status": Product.STATUS_CANDIDATE,
        "memo": "memo text",
        "first_seen_at": datetime.utcnow() - timedelta(days=2),
        "last_checked_at": datetime.utcnow(),
    }
    defaults.update(kwargs)
    product = Product(**defaults)
    db.session.add(product)
    return product


def test_get_products_returns_200(client, db_schema):
    assert client.get("/products/").status_code == 200


def test_get_products_without_trailing_slash_returns_200(client, db_schema):
    assert client.get("/products").status_code == 200


def test_products_page_renders_when_no_products(client, db_schema):
    response = client.get("/products/")
    assert response.status_code == 200
    assert "まだ商品データはありません。" in response.get_data(as_text=True)


def test_products_page_shows_basic_product_fields(client, app, db_schema):
    with app.app_context():
        _create_product(asin="B0SHOW0001", title="Display Product", brand="Display Brand")
        db.session.commit()

    text = client.get("/products/").get_data(as_text=True)
    assert "Display Product" in text
    assert "B0SHOW0001" in text
    assert "Display Brand" in text


def test_products_page_shows_price_offer_stock_score_and_links(client, app, db_schema):
    with app.app_context():
        _create_product(
            asin="B0SHOW0002",
            title="Price Product",
            current_price=2500,
            avg_price_90=2700,
            new_offer_count=7,
            amazon_in_stock=True,
            keepa_score=88,
            judgement=Product.JUDGEMENT_WATCH,
            status=Product.STATUS_UNREVIEWED,
            amazon_url="https://www.amazon.co.jp/dp/B0SHOW0002",
            keepa_url="https://keepa.com/#!product/5-B0SHOW0002",
        )
        db.session.commit()

    text = client.get("/products/").get_data(as_text=True)
    assert "2500" in text
    assert "2700" in text
    assert "7" in text
    assert "あり" in text
    assert "88" in text
    assert Product.JUDGEMENT_WATCH in text
    assert Product.STATUS_UNREVIEWED in text
    assert 'href="https://www.amazon.co.jp/dp/B0SHOW0002"' in text
    assert 'href="https://keepa.com/#!product/5-B0SHOW0002"' in text


def test_products_list_displays_last_checked_at_as_jst(client, app, db_schema):
    with app.app_context():
        _create_product(
            asin="B0JSTLIST1",
            title="JST List Product",
            last_checked_at=datetime(2026, 6, 4, 0, 30, 0),
        )
        db.session.commit()

    text = client.get("/products/").get_data(as_text=True)

    assert "取得日時（JST）" in text
    assert "2026-06-04 09:30" in text
    assert "2026-06-04 00:30" not in text


def test_products_page_limits_to_100_rows(client, app, db_schema):
    with app.app_context():
        base = datetime.utcnow()
        for index in range(105):
            _create_product(
                asin=f"B0LIMIT{index:04d}",
                title=f"Limit Product {index}",
                last_checked_at=base - timedelta(minutes=index),
            )
        db.session.commit()

    text = client.get("/products/").get_data(as_text=True)
    assert text.count('data-testid="product-row"') == 100
    assert "Limit Product 0" in text
    assert "Limit Product 99" in text
    assert "Limit Product 100" not in text


def test_products_list_contains_link_to_detail_page(client, app, db_schema):
    with app.app_context():
        product = _create_product(asin="B0DETAIL01", title="Detail Link Product")
        db.session.commit()
        product_id = product.id

    text = client.get("/products/").get_data(as_text=True)
    assert f'href="/products/{product_id}"' in text


def test_get_product_detail_returns_200(client, app, db_schema):
    with app.app_context():
        product = _create_product(asin="B0DETAIL02", title="Detail Product")
        db.session.commit()
        product_id = product.id

    response = client.get(f"/products/{product_id}")
    assert response.status_code == 200


def test_product_detail_shows_core_fields(client, app, db_schema):
    with app.app_context():
        product = _create_product(
            asin="B0DETAIL03",
            title="Detail Core Product",
            brand="Core Brand",
            manufacturer="Core Maker",
        )
        db.session.commit()
        product_id = product.id

    text = client.get(f"/products/{product_id}").get_data(as_text=True)
    assert "Detail Core Product" in text
    assert "B0DETAIL03" in text
    assert "Core Brand" in text
    assert "Core Maker" in text


def test_products_detail_displays_dates_as_jst(client, app, db_schema):
    with app.app_context():
        product = _create_product(
            asin="B0JSTDTL1",
            title="JST Detail Product",
            first_seen_at=datetime(2026, 6, 4, 0, 30, 0),
            last_checked_at=datetime(2026, 6, 4, 1, 0, 0),
        )
        db.session.commit()
        product_id = product.id

    text = client.get(f"/products/{product_id}").get_data(as_text=True)

    assert "初回取得（JST）" in text
    assert "最終確認（JST）" in text
    assert "2026-06-04 09:30" in text
    assert "2026-06-04 10:00" in text
    assert "2026-06-04 00:30" not in text


def test_product_detail_shows_prices_ranks_offers_reviews_scores_status(client, app, db_schema):
    with app.app_context():
        product = _create_product(asin="B0DETAIL04", title="Metric Product")
        db.session.commit()
        product_id = product.id

    text = client.get(f"/products/{product_id}").get_data(as_text=True)
    assert "1980" in text
    assert "1990" in text
    assert "2100" in text
    assert "1900" in text
    assert "2200" in text
    assert "1000" in text
    assert "1100" in text
    assert "1200" in text
    assert "8" in text
    assert "24" in text
    assert "7" in text
    assert "123" in text
    assert "4.5" in text
    assert "35" in text
    assert "25" in text
    assert "95" in text
    assert Product.JUDGEMENT_GOOD in text
    assert Product.STATUS_CANDIDATE in text


def test_product_detail_shows_amazon_keepa_links_and_reasons(client, app, db_schema, monkeypatch):
    with app.app_context():
        product = _create_product(asin="B0DETAIL05", title="Reason Product")
        db.session.commit()
        product_id = product.id

    monkeypatch.setattr(
        "app.routes.products.ScoringService.build_judgement_reasons",
        lambda self, product: ["reason-1", "reason-2"],
    )

    text = client.get(f"/products/{product_id}").get_data(as_text=True)
    assert 'href="https://www.amazon.co.jp/dp/B0TEST0001"' in text
    assert 'href="https://keepa.com/#!product/5-B0TEST0001"' in text
    assert "reason-1" in text
    assert "reason-2" in text


def test_product_detail_returns_404_when_not_found(client, db_schema):
    response = client.get("/products/999999")
    assert response.status_code == 404


def test_product_detail_handles_none_values_without_crashing(client, app, db_schema, monkeypatch):
    with app.app_context():
        product = _create_product(
            asin="B0DETAIL06",
            title="None Product",
            jan=None,
            ean=None,
            brand=None,
            manufacturer=None,
            category_id=None,
            category_name=None,
            image_url=None,
            amazon_url=None,
            keepa_url=None,
            current_price=None,
            avg_price_30=None,
            avg_price_90=None,
            lowest_price_90=None,
            highest_price_90=None,
            sales_rank_current=None,
            sales_rank_avg_30=None,
            sales_rank_avg_90=None,
            sales_rank_drops_30=None,
            sales_rank_drops_90=None,
            new_offer_count=None,
            used_offer_count=None,
            fba_offer_count=None,
            amazon_in_stock=None,
            amazon_was_in_stock_90=None,
            review_count=None,
            rating=None,
            sales_score=None,
            price_stability_score=None,
            competition_score=None,
            risk_score=None,
            keepa_score=None,
            judgement=Product.JUDGEMENT_UNKNOWN,
            status=Product.STATUS_HOLD,
            memo=None,
            first_seen_at=None,
            last_checked_at=None,
        )
        db.session.commit()
        product_id = product.id

    monkeypatch.setattr(
        "app.routes.products.ScoringService.build_judgement_reasons",
        lambda self, product: [],
    )

    response = client.get(f"/products/{product_id}")
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "None Product" in text
    assert "-" in text


def test_navigation_contains_products_link(client, db_schema):
    text = client.get("/").get_data(as_text=True)
    assert 'href="/products/"' in text


@pytest.mark.parametrize(
    "next_status",
    [
        Product.STATUS_CANDIDATE,
        Product.STATUS_HOLD,
        Product.STATUS_EXCLUDED,
        Product.STATUS_SUPPLIER_SEARCH_PENDING,
    ],
)
def test_update_product_status_allows_manual_statuses(client, app, db_schema, next_status):
    with app.app_context():
        product = _create_product(asin=f"B0UPD{next_status[:4].upper()}01")
        db.session.commit()
        product_id = product.id

    response = client.post(
        f"/products/{product_id}/update",
        data={"status": next_status, "memo": "status updated"},
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"/products/{product_id}")

    with app.app_context():
        saved = db.session.get(Product, product_id)
        assert saved.status == next_status


def test_update_product_saves_memo_and_redirects_to_detail(client, app, db_schema):
    with app.app_context():
        product = _create_product(asin="B0UPDMEMO1", memo=None)
        db.session.commit()
        product_id = product.id

    response = client.post(
        f"/products/{product_id}/update",
        data={"status": Product.STATUS_HOLD, "memo": "memo saved from detail"},
        follow_redirects=True,
    )
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "商品情報を保存しました。" in text
    assert "memo saved from detail" in text
    assert 'option value="hold" selected' in text

    with app.app_context():
        saved = db.session.get(Product, product_id)
        assert saved.memo == "memo saved from detail"
        assert saved.status == Product.STATUS_HOLD


def test_update_product_invalid_status_is_rejected_without_saving(client, app, db_schema):
    with app.app_context():
        product = _create_product(asin="B0BADSTAT01", status=Product.STATUS_UNREVIEWED, memo="old")
        db.session.commit()
        product_id = product.id

    response = client.post(
        f"/products/{product_id}/update",
        data={"status": "invalid_status", "memo": "new memo should not persist"},
        follow_redirects=True,
    )
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "不正なステータスが指定されました。" in text

    with app.app_context():
        saved = db.session.get(Product, product_id)
        assert saved.status == Product.STATUS_UNREVIEWED
        assert saved.memo == "old"


def test_update_product_returns_404_for_unknown_product(client, db_schema):
    response = client.post(
        "/products/999999/update",
        data={"status": Product.STATUS_CANDIDATE, "memo": "x"},
    )
    assert response.status_code == 404


def test_update_product_rolls_back_when_commit_fails(client, app, db_schema, monkeypatch):
    with app.app_context():
        product = _create_product(asin="B0ROLLBACK1", status=Product.STATUS_UNREVIEWED, memo="before")
        db.session.commit()
        product_id = product.id

    rollback_called = {"value": False}
    original_rollback = db.session.rollback

    def failing_commit():
        raise RuntimeError("db failure")

    def tracking_rollback():
        rollback_called["value"] = True
        return original_rollback()

    monkeypatch.setattr(db.session, "commit", failing_commit)
    monkeypatch.setattr(db.session, "rollback", tracking_rollback)

    response = client.post(
        f"/products/{product_id}/update",
        data={"status": Product.STATUS_CANDIDATE, "memo": "after"},
        follow_redirects=True,
    )
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "データベース保存中にエラーが発生しました。" in text
    assert rollback_called["value"] is True

    with app.app_context():
        saved = db.session.get(Product, product_id)
        assert saved.status == Product.STATUS_UNREVIEWED
        assert saved.memo == "before"


def test_products_list_reflects_updated_status(client, app, db_schema):
    with app.app_context():
        product = _create_product(asin="B0LISTUPD01", status=Product.STATUS_UNREVIEWED)
        db.session.commit()
        product_id = product.id

    client.post(
        f"/products/{product_id}/update",
        data={"status": Product.STATUS_CANDIDATE, "memo": "updated"},
    )
    text = client.get("/products/").get_data(as_text=True)
    assert Product.STATUS_CANDIDATE in text


def test_products_filter_by_status_candidate(client, app, db_schema):
    with app.app_context():
        _create_product(asin="B0FST0001", title="Status Candidate", status=Product.STATUS_CANDIDATE)
        _create_product(asin="B0FST0002", title="Status Excluded", status=Product.STATUS_EXCLUDED)
        db.session.commit()

    text = client.get("/products/?status=candidate").get_data(as_text=True)
    assert "Status Candidate" in text
    assert "Status Excluded" not in text


def test_products_filter_by_status_excluded(client, app, db_schema):
    with app.app_context():
        _create_product(asin="B0FST1001", title="Excluded Target", status=Product.STATUS_EXCLUDED)
        _create_product(asin="B0FST1002", title="Hold Target", status=Product.STATUS_HOLD)
        db.session.commit()

    text = client.get("/products/?status=excluded").get_data(as_text=True)
    assert "Excluded Target" in text
    assert "Hold Target" not in text


def test_products_filter_by_judgement_good(client, app, db_schema):
    with app.app_context():
        _create_product(asin="B0FJG0001", title="Good Target", judgement=Product.JUDGEMENT_GOOD)
        _create_product(asin="B0FJG0002", title="Bad Target", judgement=Product.JUDGEMENT_BAD)
        db.session.commit()

    text = client.get("/products/?judgement=good").get_data(as_text=True)
    assert "Good Target" in text
    assert "Bad Target" not in text


def test_products_filter_by_brand_partial_match(client, app, db_schema):
    with app.app_context():
        _create_product(asin="B0FBR0001", title="Brand Hit", brand="Alpha Brand")
        _create_product(asin="B0FBR0002", title="Brand Miss", brand="Beta Corp")
        db.session.commit()

    text = client.get("/products/?brand=alpha").get_data(as_text=True)
    assert "Brand Hit" in text
    assert "Brand Miss" not in text


def test_products_filter_by_min_score(client, app, db_schema):
    with app.app_context():
        _create_product(asin="B0FMIN001", title="Score 65", keepa_score=65)
        _create_product(asin="B0FMIN002", title="Score 55", keepa_score=55)
        db.session.commit()

    text = client.get("/products/?min_score=60").get_data(as_text=True)
    assert "Score 65" in text
    assert "Score 55" not in text


def test_products_filter_by_max_score(client, app, db_schema):
    with app.app_context():
        _create_product(asin="B0FMAX001", title="Score 80", keepa_score=80)
        _create_product(asin="B0FMAX002", title="Score 95", keepa_score=95)
        db.session.commit()

    text = client.get("/products/?max_score=85").get_data(as_text=True)
    assert "Score 80" in text
    assert "Score 95" not in text


def test_products_filter_invalid_score_params_do_not_crash(client, app, db_schema):
    with app.app_context():
        _create_product(asin="B0FINV001", title="Invalid Score A", keepa_score=70)
        _create_product(asin="B0FINV002", title="Invalid Score B", keepa_score=75)
        db.session.commit()

    response = client.get("/products/?min_score=abc&max_score=xyz")
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Invalid Score A" in text
    assert "Invalid Score B" in text


def test_products_sort_score_desc(client, app, db_schema):
    with app.app_context():
        _create_product(asin="B0SRTS001", title="Score Top", keepa_score=90)
        _create_product(asin="B0SRTS002", title="Score Low", keepa_score=60)
        db.session.commit()

    text = client.get("/products/?sort=score_desc").get_data(as_text=True)
    assert text.index("Score Top") < text.index("Score Low")


def test_products_sort_sales_rank_drops_desc(client, app, db_schema):
    with app.app_context():
        _create_product(asin="B0SRD0001", title="Drops Top", sales_rank_drops_90=40)
        _create_product(asin="B0SRD0002", title="Drops Low", sales_rank_drops_90=5)
        db.session.commit()

    text = client.get("/products/?sort=sales_rank_drops_desc").get_data(as_text=True)
    assert text.index("Drops Top") < text.index("Drops Low")


def test_products_sort_price_stability_desc(client, app, db_schema):
    with app.app_context():
        _create_product(asin="B0SPS0001", title="Stability Top", price_stability_score=30)
        _create_product(asin="B0SPS0002", title="Stability Low", price_stability_score=10)
        db.session.commit()

    text = client.get("/products/?sort=price_stability_desc").get_data(as_text=True)
    assert text.index("Stability Top") < text.index("Stability Low")


def test_products_sort_new_offer_count_asc(client, app, db_schema):
    with app.app_context():
        _create_product(asin="B0SOC0001", title="Offer Few", new_offer_count=2)
        _create_product(asin="B0SOC0002", title="Offer Many", new_offer_count=9)
        db.session.commit()

    text = client.get("/products/?sort=new_offer_count_asc").get_data(as_text=True)
    assert text.index("Offer Few") < text.index("Offer Many")


def test_products_invalid_sort_falls_back_to_last_checked_desc(client, app, db_schema):
    with app.app_context():
        now = datetime.utcnow()
        _create_product(asin="B0ISRT001", title="Newest Checked", last_checked_at=now)
        _create_product(
            asin="B0ISRT002",
            title="Old Checked",
            last_checked_at=now - timedelta(days=1),
        )
        db.session.commit()

    text = client.get("/products/?sort=unknown_sort").get_data(as_text=True)
    assert text.index("Newest Checked") < text.index("Old Checked")


def test_products_filter_form_is_rendered(client, db_schema):
    text = client.get("/products/").get_data(as_text=True)
    assert 'name="status"' in text
    assert 'name="judgement"' in text
    assert 'name="brand"' in text
    assert 'name="min_score"' in text
    assert 'name="max_score"' in text
    assert 'name="sort"' in text
    assert "表示件数:" in text


def test_products_filter_values_are_preserved(client, app, db_schema):
    with app.app_context():
        _create_product(
            asin="B0KEEP0001",
            title="Keep Filter Value",
            status=Product.STATUS_CANDIDATE,
            judgement=Product.JUDGEMENT_GOOD,
            brand="Keep Brand",
            keepa_score=88,
        )
        db.session.commit()

    text = client.get(
        "/products/?status=candidate&judgement=good&brand=Keep&min_score=60&max_score=90&sort=score_desc"
    ).get_data(as_text=True)
    assert 'option value="candidate" selected' in text
    assert 'option value="good" selected' in text
    assert 'value="Keep"' in text
    assert 'name="min_score"' in text and 'value="60"' in text
    assert 'name="max_score"' in text and 'value="90"' in text
    assert 'option value="score_desc" selected' in text


def test_products_integration_list_detail_update_and_filter_flow(client, app, db_schema):
    with app.app_context():
        product = _create_product(
            asin="B0FLOW0001",
            title="Flow Product",
            status=Product.STATUS_UNREVIEWED,
            memo="before memo",
        )
        db.session.commit()
        product_id = product.id

    list_text_before = client.get("/products/").get_data(as_text=True)
    assert "Flow Product" in list_text_before
    assert f'href="/products/{product_id}"' in list_text_before

    detail_text_before = client.get(f"/products/{product_id}").get_data(as_text=True)
    assert detail_text_before
    assert "Flow Product" in detail_text_before
    assert Product.STATUS_UNREVIEWED in detail_text_before

    update_response = client.post(
        f"/products/{product_id}/update",
        data={"status": Product.STATUS_CANDIDATE, "memo": "flow memo updated"},
        follow_redirects=True,
    )
    update_text = update_response.get_data(as_text=True)
    assert update_response.status_code == 200
    assert "商品情報を保存しました。" in update_text
    assert "flow memo updated" in update_text

    list_text_after = client.get("/products/").get_data(as_text=True)
    assert "Flow Product" in list_text_after
    assert Product.STATUS_CANDIDATE in list_text_after

    candidate_text = client.get("/products/?status=candidate").get_data(as_text=True)
    assert "Flow Product" in candidate_text

    excluded_text = client.get("/products/?status=excluded").get_data(as_text=True)
    assert "Flow Product" not in excluded_text


def test_products_filter_and_sort_combination_keeps_page_stable(client, app, db_schema):
    with app.app_context():
        _create_product(
            asin="B0COMBO001",
            title="Combo Candidate Product",
            status=Product.STATUS_CANDIDATE,
            keepa_score=91,
            judgement=Product.JUDGEMENT_GOOD,
        )
        _create_product(
            asin="B0COMBO002",
            title="Combo Excluded Product",
            status=Product.STATUS_EXCLUDED,
            keepa_score=99,
            judgement=Product.JUDGEMENT_GOOD,
        )
        db.session.commit()

    response = client.get("/products/?status=candidate&min_score=60&sort=score_desc")
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Combo Candidate Product" in text
    assert "Combo Excluded Product" not in text
    assert 'option value="candidate" selected' in text
    assert 'option value="score_desc" selected' in text
    assert 'name="min_score"' in text and 'value="60"' in text


def test_phase7_acceptance_end_to_end_products_views_edit_filters_and_sort(client, app, db_schema):
    with app.app_context():
        first = _create_product(
            asin="B0PH700001",
            title="Phase7 Product A",
            brand="Phase Brand",
            keepa_score=85,
            judgement=Product.JUDGEMENT_GOOD,
            status=Product.STATUS_UNREVIEWED,
        )
        _create_product(
            asin="B0PH700002",
            title="Phase7 Product B",
            brand="Other Brand",
            keepa_score=72,
            judgement=Product.JUDGEMENT_WATCH,
            status=Product.STATUS_HOLD,
        )
        _create_product(
            asin="B0PH700003",
            title="Phase7 Product C",
            brand="Phase Brand",
            keepa_score=92,
            judgement=Product.JUDGEMENT_GOOD,
            status=Product.STATUS_EXCLUDED,
        )
        db.session.commit()
        first_id = first.id

    list_response = client.get("/products/")
    list_text = list_response.get_data(as_text=True)
    assert list_response.status_code == 200
    assert "Phase7 Product A" in list_text
    assert "Phase7 Product B" in list_text

    detail_response = client.get(f"/products/{first_id}")
    detail_text = detail_response.get_data(as_text=True)
    assert detail_response.status_code == 200
    assert "Phase7 Product A" in detail_text

    update_response = client.post(
        f"/products/{first_id}/update",
        data={"status": Product.STATUS_CANDIDATE, "memo": "phase7 updated memo"},
        follow_redirects=True,
    )
    update_text = update_response.get_data(as_text=True)
    assert update_response.status_code == 200
    assert "商品情報を保存しました。" in update_text
    assert "phase7 updated memo" in update_text

    status_filter_text = client.get("/products/?status=candidate").get_data(as_text=True)
    assert "Phase7 Product A" in status_filter_text

    judgement_filter_text = client.get("/products/?judgement=good").get_data(as_text=True)
    assert "Phase7 Product A" in judgement_filter_text
    assert "Phase7 Product C" in judgement_filter_text
    assert "Phase7 Product B" not in judgement_filter_text

    brand_filter_text = client.get("/products/?brand=phase").get_data(as_text=True)
    assert "Phase7 Product A" in brand_filter_text
    assert "Phase7 Product C" in brand_filter_text
    assert "Phase7 Product B" not in brand_filter_text

    sort_text = client.get("/products/?sort=score_desc").get_data(as_text=True)
    assert sort_text.index("Phase7 Product C") < sort_text.index("Phase7 Product A")


@pytest.fixture()
def csv_exporter_to_isolated_exports(monkeypatch, isolated_dirs):
    export_dir = isolated_dirs["exports"]
    monkeypatch.setattr(
        "app.routes.products.CsvExporter",
        lambda: CsvExporter(export_dir=str(export_dir)),
    )
    return export_dir


def test_export_all_csv_downloads_all_products(client, app, db_schema, csv_exporter_to_isolated_exports):
    with app.app_context():
        _create_product(asin="B0CSVALL01", title="CSV All Candidate", status=Product.STATUS_CANDIDATE)
        _create_product(asin="B0CSVALL02", title="CSV All Excluded", status=Product.STATUS_EXCLUDED)
        db.session.commit()

    response = client.get("/products/export?target=all")
    csv_text = response.data.decode("utf-8-sig")

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("text/csv")
    assert "attachment" in response.headers["Content-Disposition"]
    assert "CSV All Candidate" in csv_text
    assert "CSV All Excluded" in csv_text


def test_export_candidates_csv_downloads_only_candidate_products(
    client, app, db_schema, csv_exporter_to_isolated_exports
):
    with app.app_context():
        _create_product(asin="B0CSVCAN01", title="CSV Candidate Product", status=Product.STATUS_CANDIDATE)
        _create_product(asin="B0CSVCAN02", title="CSV Excluded Product", status=Product.STATUS_EXCLUDED)
        db.session.commit()

    response = client.get("/products/export?target=candidates")
    csv_text = response.data.decode("utf-8-sig")

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("text/csv")
    assert "attachment" in response.headers["Content-Disposition"]
    assert "CSV Candidate Product" in csv_text
    assert "CSV Excluded Product" not in csv_text


def test_products_export_invalid_target_flashes_safe_message(
    client, app, db_schema, csv_exporter_to_isolated_exports
):
    with app.app_context():
        _create_product(asin="B0CSVINV01", title="CSV Invalid Target Product")
        db.session.commit()

    response = client.get("/products/export?target=unknown", follow_redirects=True)
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "CSV出力対象が不正です。" in text
    assert "CSV Invalid Target Product" in text


def test_export_csv_error_redirects_to_products_list(client, db_schema, monkeypatch):
    class FailingExporter:
        def export_products(self, products):
            raise CsvExporterError("internal path secret")

        def export_candidates(self):
            raise CsvExporterError("internal path secret")

    monkeypatch.setattr("app.routes.products.CsvExporter", lambda: FailingExporter())

    response = client.get("/products/export?target=all")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/products/")


def test_export_csv_error_shows_safe_message(client, db_schema, monkeypatch):
    class FailingExporter:
        def export_products(self, products):
            raise CsvExporterError("internal path secret key=SECRET_KEEPA_KEY_123")

        def export_candidates(self):
            raise CsvExporterError("internal path secret key=SECRET_KEEPA_KEY_123")

    monkeypatch.setattr("app.routes.products.CsvExporter", lambda: FailingExporter())

    response = client.get("/products/export?target=all", follow_redirects=True)
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "CSV出力中にエラーが発生しました。" in text
    assert "internal path secret" not in text
    assert "SECRET_KEEPA_KEY_123" not in text


def test_products_export_csv_error_does_not_leak_secret(client, db_schema, monkeypatch, caplog):
    class FailingExporter:
        def export_products(self, products):
            raise CsvExporterError("failed apiKey=SECRET_KEEPA_KEY_123")

        def export_candidates(self):
            raise CsvExporterError("failed apiKey=SECRET_KEEPA_KEY_123")

    monkeypatch.setattr("app.routes.products.CsvExporter", lambda: FailingExporter())

    with caplog.at_level("ERROR"):
        response = client.get("/products/export?target=all", follow_redirects=True)

    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "SECRET_KEEPA_KEY_123" not in text
    assert "SECRET_KEEPA_KEY_123" not in caplog.text
    assert "[REDACTED]" in caplog.text


def test_products_list_shows_csv_export_buttons(client, db_schema):
    text = client.get("/products/").get_data(as_text=True)

    assert "全商品CSV出力" in text
    assert "候補商品のみCSV出力" in text
    assert 'href="/products/export?target=all"' in text
    assert 'href="/products/export?target=candidates"' in text


def test_phase9_acceptance_csv_export_service_and_routes(
    client, app, db_schema, csv_exporter_to_isolated_exports
):
    with app.app_context():
        _create_product(
            asin="B0P9CSV001",
            title="Phase9 Candidate CSV Product",
            status=Product.STATUS_CANDIDATE,
        )
        _create_product(
            asin="B0P9CSV002",
            title="Phase9 Excluded CSV Product",
            status=Product.STATUS_EXCLUDED,
        )
        db.session.commit()

    with app.app_context():
        products = Product.query.order_by(Product.asin.asc()).all()
        service_filepath = CsvExporter(export_dir=str(csv_exporter_to_isolated_exports)).export_products(products)

    with open(service_filepath, "rb") as csv_file:
        assert csv_file.read(3) == b"\xef\xbb\xbf"

    with open(service_filepath, encoding="utf-8-sig", newline="") as csv_file:
        rows = list(csv.reader(csv_file))

    assert len(rows[0]) == 22
    assert "raw_keepa_json" not in rows[0]
    assert "Phase9 Candidate CSV Product" in str(rows)
    assert "Phase9 Excluded CSV Product" in str(rows)

    list_text = client.get("/products/").get_data(as_text=True)
    assert "全商品CSV出力" in list_text
    assert "候補商品のみCSV出力" in list_text

    all_response = client.get("/products/export?target=all")
    assert all_response.status_code == 200
    assert all_response.data.startswith(b"\xef\xbb\xbf")
    assert "attachment" in all_response.headers["Content-Disposition"]
    all_csv_text = all_response.data.decode("utf-8-sig")
    assert "Phase9 Candidate CSV Product" in all_csv_text
    assert "Phase9 Excluded CSV Product" in all_csv_text

    candidates_response = client.get("/products/export?target=candidates")
    assert candidates_response.status_code == 200
    assert candidates_response.data.startswith(b"\xef\xbb\xbf")
    assert "attachment" in candidates_response.headers["Content-Disposition"]
    candidates_csv_text = candidates_response.data.decode("utf-8-sig")
    assert "Phase9 Candidate CSV Product" in candidates_csv_text
    assert "Phase9 Excluded CSV Product" not in candidates_csv_text



