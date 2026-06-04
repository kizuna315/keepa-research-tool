import csv
import json
from datetime import datetime

import pytest

from app.extensions import db
from app.models import AppSetting, Product, ResearchRun
from app.services.csv_exporter import CsvExporter
from app.services.settings_service import SettingsService


SECRET_API_KEY = "SECRET_KEEPA_KEY_123"


@pytest.fixture()
def db_schema(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        yield
        db.session.remove()
        db.drop_all()


def _valid_settings_form(**overrides):
    values = {
        AppSetting.KEY_DEFAULT_DOMAIN_ID: "5",
        AppSetting.KEY_DEFAULT_MIN_PRICE: "1500",
        AppSetting.KEY_DEFAULT_MAX_PRICE: "10000",
        AppSetting.KEY_DEFAULT_MIN_OFFER_COUNT: "3",
        AppSetting.KEY_DEFAULT_MAX_OFFER_COUNT: "15",
        AppSetting.KEY_DEFAULT_MIN_SALES_RANK_DROPS_90: "10",
        AppSetting.KEY_CSV_EXPORT_DIR: "exports",
        AppSetting.KEY_EXCLUDE_AMAZON_IN_STOCK: "on",
    }
    values.update(overrides)
    return values


def _product_data(asin, title, **overrides):
    values = {
        "asin": asin,
        "jan": "4900000000001",
        "ean": "4900000000001",
        "title": title,
        "brand": "TestBrand",
        "manufacturer": "TestMaker",
        "category_id": "123",
        "category_name": "Test Category",
        "image_url": "",
        "amazon_url": f"https://www.amazon.co.jp/dp/{asin}",
        "keepa_url": f"https://keepa.com/#!product/5-{asin}",
        "current_price": 2500,
        "avg_price_30": 2600,
        "avg_price_90": 2700,
        "lowest_price_90": 2400,
        "highest_price_90": 2900,
        "sales_rank_current": 10000,
        "sales_rank_avg_30": 12000,
        "sales_rank_avg_90": 15000,
        "sales_rank_drops_30": 8,
        "sales_rank_drops_90": 24,
        "new_offer_count": 7,
        "used_offer_count": 0,
        "fba_offer_count": 5,
        "amazon_in_stock": False,
        "amazon_was_in_stock_90": False,
        "review_count": 30,
        "rating": 4.2,
        "raw_keepa_json": "{}",
    }
    values.update(overrides)
    return values


class FakeKeepaClient:
    def __init__(self):
        self.asin_calls = []
        self.keyword_calls = []

    def get_products_by_asins(self, asins):
        self.asin_calls.append(list(asins))
        return [
            _product_data("B0TESTASIN1", "E2E ASIN Product"),
        ]

    def search_products(self, keyword, category_id=None, limit=100, filters=None, fetch_mode="light"):
        self.keyword_calls.append(
            {
                "keyword": keyword,
                "category_id": category_id,
                "limit": limit,
                "filters": filters or {},
                "fetch_mode": fetch_mode,
            }
        )
        return [
            _product_data("B0KEYWORD01", "E2E Keyword Match Product"),
            _product_data(
                "B0KEYWORD02",
                "E2E Keyword Excluded Product",
                current_price=500,
                review_count=1,
                sales_rank_drops_90=1,
            ),
        ][:limit]

    def normalize_product(self, raw):
        return dict(raw)


@pytest.fixture()
def fake_keepa_client(monkeypatch):
    fake = FakeKeepaClient()
    monkeypatch.setattr("app.services.research_service.KeepaClient", lambda: fake)
    return fake


@pytest.fixture()
def csv_exporter_to_isolated_exports(monkeypatch, isolated_dirs):
    export_dir = isolated_dirs["exports"]
    monkeypatch.setattr(
        "app.routes.products.CsvExporter",
        lambda: CsvExporter(export_dir=str(export_dir)),
    )
    return export_dir


def _create_product(**overrides):
    values = _product_data("B0E2EDB001", "E2E DB Product")
    values.update(
        {
            "sales_score": 35,
            "price_stability_score": 18,
            "competition_score": 25,
            "risk_score": 10,
            "keepa_score": 88,
            "judgement": Product.JUDGEMENT_GOOD,
            "status": Product.STATUS_CANDIDATE,
            "memo": "",
            "first_seen_at": datetime.utcnow(),
            "last_checked_at": datetime.utcnow(),
        }
    )
    values.update(overrides)
    product = Product(**values)
    db.session.add(product)
    return product


def test_e2e_asin_research_to_product_detail_and_csv_export(
    client,
    app,
    db_schema,
    fake_keepa_client,
    csv_exporter_to_isolated_exports,
):
    settings_data = _valid_settings_form()
    settings_data[AppSetting.KEY_KEEPA_API_KEY] = SECRET_API_KEY
    settings_response = client.post("/settings/", data=settings_data, follow_redirects=True)
    assert settings_response.status_code == 200
    assert SECRET_API_KEY not in settings_response.get_data(as_text=True)

    response = client.post(
        "/research/new",
        data={
            "research_type": "asin",
            "name": "E2E ASIN Run",
            "asin_text": "B0TESTASIN1",
        },
        follow_redirects=True,
    )
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "ASINリサーチが完了しました。" in text
    assert SECRET_API_KEY not in text
    assert fake_keepa_client.asin_calls == [["B0TESTASIN1"]]

    with app.app_context():
        run = ResearchRun.query.filter_by(name="E2E ASIN Run").first()
        product = Product.query.filter_by(asin="B0TESTASIN1").first()
        assert run is not None
        assert run.status == ResearchRun.STATUS_COMPLETED
        assert run.total_fetched == 1
        assert run.total_saved == 1
        assert product is not None
        assert product.keepa_score is not None
        assert product.judgement == Product.JUDGEMENT_GOOD
        assert product.status == Product.STATUS_CANDIDATE
        product_id = product.id

    list_text = client.get("/products/").get_data(as_text=True)
    assert "E2E ASIN Product" in list_text
    assert "B0TESTASIN1" in list_text
    assert "good" in list_text
    assert "candidate" in list_text

    detail_text = client.get(f"/products/{product_id}").get_data(as_text=True)
    assert "E2E ASIN Product" in detail_text
    assert "B0TESTASIN1" in detail_text
    assert "TestBrand" in detail_text
    assert "candidate" in detail_text

    csv_response = client.get("/products/export?target=all")
    csv_text = csv_response.data.decode("utf-8-sig")
    rows = list(csv.reader(csv_text.splitlines()))

    assert csv_response.status_code == 200
    assert "attachment" in csv_response.headers["Content-Disposition"]
    assert "E2E ASIN Product" in csv_text
    assert "B0TESTASIN1" in csv_text
    assert "raw_keepa_json" not in rows[0]
    assert "raw_keepa_json" not in csv_text
    assert SECRET_API_KEY not in csv_text


def test_e2e_keyword_research_to_products_list(
    client,
    app,
    db_schema,
    fake_keepa_client,
):
    response = client.post(
        "/research/new",
        data={
            "research_type": "keyword",
            "name": "E2E Keyword Run",
            "keyword": "水筒",
            "category_id": "12345",
            "min_price": "1000",
            "max_price": "4000",
            "min_review_count": "10",
            "max_review_count": "100",
            "min_offer_count": "3",
            "max_offer_count": "15",
            "exclude_amazon_in_stock": "false",
            "min_sales_rank_drops_90": "10",
            "limit": "2",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert fake_keepa_client.keyword_calls
    assert fake_keepa_client.keyword_calls[0]["keyword"] == "水筒"
    assert fake_keepa_client.keyword_calls[0]["category_id"] == "12345"
    assert fake_keepa_client.keyword_calls[0]["limit"] == 2

    with app.app_context():
        run = ResearchRun.query.filter_by(name="E2E Keyword Run").first()
        matched = Product.query.filter_by(asin="B0KEYWORD01").first()
        excluded = Product.query.filter_by(asin="B0KEYWORD02").first()
        conditions = json.loads(run.conditions_json)

        assert conditions["type"] == "keyword"
        assert run.status == ResearchRun.STATUS_COMPLETED
        assert run.total_fetched == 2
        assert run.total_saved == 2
        assert matched is not None
        assert matched.keepa_score is not None
        assert matched.status == Product.STATUS_CANDIDATE
        assert excluded is not None
        assert excluded.judgement == Product.JUDGEMENT_BAD
        assert excluded.status == Product.STATUS_EXCLUDED

    list_text = client.get("/products/").get_data(as_text=True)
    assert "E2E Keyword Match Product" in list_text
    assert "E2E Keyword Excluded Product" in list_text
    assert "B0KEYWORD01" in list_text
    assert "B0KEYWORD02" in list_text


def test_e2e_settings_save_then_research_page_loads(client, app, db_schema):
    settings_data = _valid_settings_form(
        default_min_price="2200",
        default_max_price="8800",
    )
    settings_data[AppSetting.KEY_KEEPA_API_KEY] = SECRET_API_KEY

    response = client.post("/settings/", data=settings_data, follow_redirects=True)
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "設定を保存しました。" in text
    assert SECRET_API_KEY not in text

    with app.app_context():
        assert SettingsService.get(AppSetting.KEY_KEEPA_API_KEY) == SECRET_API_KEY
        assert SettingsService.get(AppSetting.KEY_DEFAULT_MIN_PRICE) == "2200"

    research_response = client.get("/research/new")
    research_text = research_response.get_data(as_text=True)

    assert research_response.status_code == 200
    assert "ASIN指定リサーチ" in research_text
    assert "キーワード検索リサーチ" in research_text
    assert 'name="asin_text"' in research_text
    assert 'name="keyword"' in research_text
    assert SECRET_API_KEY not in research_text


def test_e2e_status_and_memo_update_flow(client, app, db_schema):
    with app.app_context():
        product = _create_product(
            asin="B0E2EMEMO1",
            title="E2E Memo Product",
            status=Product.STATUS_UNREVIEWED,
            memo="",
        )
        db.session.commit()
        product_id = product.id

    detail_before = client.get(f"/products/{product_id}").get_data(as_text=True)
    assert "E2E Memo Product" in detail_before

    response = client.post(
        f"/products/{product_id}/update",
        data={
            "status": Product.STATUS_SUPPLIER_SEARCH_PENDING,
            "memo": "E2E memo saved",
        },
        follow_redirects=True,
    )
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "E2E memo saved" in text
    assert Product.STATUS_SUPPLIER_SEARCH_PENDING in text

    with app.app_context():
        updated = db.session.get(Product, product_id)
        assert updated.status == Product.STATUS_SUPPLIER_SEARCH_PENDING
        assert updated.memo == "E2E memo saved"


def test_e2e_dashboard_reflects_saved_products_and_research_runs(
    client,
    app,
    db_schema,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.routes.dashboard._get_keepa_token_summary",
        lambda: {
            "keepa_token_status": "available",
            "keepa_tokens_left": 123,
            "keepa_refill_rate": 20,
            "keepa_refill_in": 30000,
            "keepa_token_error": None,
        },
    )

    empty_text = client.get("/").get_data(as_text=True)
    assert "総取得商品数" in empty_text
    assert "まだリサーチ履歴はありません。" in empty_text
    assert "まだ取得商品はありません。" in empty_text

    with app.app_context():
        _create_product(
            asin="B0E2EDASH1",
            title="E2E Dashboard Candidate",
            status=Product.STATUS_CANDIDATE,
        )
        _create_product(
            asin="B0E2EDASH2",
            title="E2E Dashboard Hold",
            status=Product.STATUS_HOLD,
            judgement=Product.JUDGEMENT_UNKNOWN,
        )
        run = ResearchRun(
            name="E2E Dashboard Run",
            status=ResearchRun.STATUS_COMPLETED,
            conditions_json='{"type":"asin"}',
            total_requested=2,
            total_fetched=2,
            total_saved=2,
            started_at=datetime.utcnow(),
            finished_at=datetime.utcnow(),
        )
        db.session.add(run)
        db.session.commit()

    text = client.get("/").get_data(as_text=True)
    assert "E2E Dashboard Run" in text
    assert "completed" in text
    assert "E2E Dashboard Candidate" in text
    assert "E2E Dashboard Hold" in text
    assert "候補商品数" in text
    assert "保留商品数" in text
    assert "123" in text
