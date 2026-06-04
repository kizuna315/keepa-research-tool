import json
from datetime import datetime

import pytest

from app.extensions import db
from app.models import Product, ProductResearchRun, ResearchRun
from app.services.keepa_client import KeepaApiError
from app.services.research_service import (
    InvalidAsinInputError,
    ResearchService,
    ResearchServiceError,
)
from app.services.scoring_service import ScoringService


@pytest.fixture()
def db_schema(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        yield
        db.session.remove()
        db.drop_all()


def test_parse_asins_supports_newline_and_comma_with_dedup_and_uppercase():
    service = ResearchService()
    asin_text = "b0abc11111\nB0DEF22222\n\nB0ABC11111, b0ghi33333"

    result = service.parse_asins(asin_text)

    assert result == ["B0ABC11111", "B0DEF22222", "B0GHI33333"]


def test_parse_asins_filters_invalid_values_and_keeps_valid():
    service = ResearchService()
    asin_text = "b0abc11111\ninvalid-asin\n@@@@\n1234567\nb0def22222"

    result = service.parse_asins(asin_text)

    assert result == ["B0ABC11111", "B0DEF22222"]


def test_parse_asins_raises_when_no_valid_asins():
    service = ResearchService()
    with pytest.raises(InvalidAsinInputError):
        service.parse_asins(" \n,\n@@@\n123")


def test_build_asin_conditions_sets_expected_shape():
    service = ResearchService()
    asins = ["B0ABC11111", "B0DEF22222"]

    result = service.build_asin_conditions(None, asins)

    assert result == {
        "type": "asin",
        "name": "ASIN指定リサーチ",
        "asins": ["B0ABC11111", "B0DEF22222"],
        "total_requested": 2,
    }


def test_create_research_run_for_asins_creates_pending_row(app, db_schema):
    service = ResearchService()
    asin_text = "b0abc11111\nb0def22222"

    with app.app_context():
        run = service.create_research_run_for_asins(None, asin_text)
        saved = ResearchRun.query.get(run.id)

    assert run.id is not None
    assert saved is not None
    assert saved.status == ResearchRun.STATUS_PENDING
    assert saved.name == "ASIN指定リサーチ"
    assert saved.keyword is None
    assert saved.category_id is None
    assert saved.total_requested == 2
    assert saved.total_fetched == 0
    assert saved.total_saved == 0
    assert saved.error_message is None
    assert saved.started_at is None
    assert saved.finished_at is None

    conditions = json.loads(saved.conditions_json)
    assert conditions["type"] == "asin"
    assert conditions["name"] == "ASIN指定リサーチ"
    assert conditions["asins"] == ["B0ABC11111", "B0DEF22222"]
    assert conditions["total_requested"] == 2
    assert "ASIN指定リサーチ" in saved.conditions_json


def test_create_research_run_for_asins_uses_given_name(app, db_schema):
    service = ResearchService()

    with app.app_context():
        run = service.create_research_run_for_asins("  テスト実行  ", "b0abc11111")
        saved = ResearchRun.query.get(run.id)

    assert saved is not None
    assert saved.name == "テスト実行"
    conditions = json.loads(saved.conditions_json)
    assert conditions["name"] == "テスト実行"


class FailingSession:
    def __init__(self):
        self.added = []
        self.rollback_called = False

    def add(self, item):
        self.added.append(item)

    def commit(self):
        raise RuntimeError("commit failure")

    def rollback(self):
        self.rollback_called = True


def test_create_research_run_for_asins_rolls_back_on_commit_failure():
    failing_session = FailingSession()
    service = ResearchService(db_session=failing_session)

    with pytest.raises(ResearchServiceError):
        service.create_research_run_for_asins(None, "b0abc11111")

    assert len(failing_session.added) == 1
    assert failing_session.rollback_called is True


def test_mark_running_updates_status_and_started_at(app, db_schema):
    service = ResearchService()

    with app.app_context():
        run = service.create_research_run_for_asins(None, "b0abc11111")
        assert run.status == ResearchRun.STATUS_PENDING
        assert run.started_at is None

        service.mark_running(run)
        saved = ResearchRun.query.get(run.id)

    assert saved is not None
    assert saved.status == ResearchRun.STATUS_RUNNING
    assert saved.started_at is not None


class CommitFailSession:
    def __init__(self):
        self.rollback_called = False

    def commit(self):
        raise RuntimeError("commit failure")

    def rollback(self):
        self.rollback_called = True


def test_mark_running_rolls_back_on_commit_failure():
    session = CommitFailSession()
    service = ResearchService(db_session=session)
    run = ResearchRun(status=ResearchRun.STATUS_PENDING)

    with pytest.raises(ResearchServiceError):
        service.mark_running(run)

    assert session.rollback_called is True


class FakeKeepaClient:
    def __init__(self, raw_products, normalized_products=None, error=None):
        self._raw_products = raw_products
        self._normalized_products = normalized_products or {}
        self._error = error
        self.called_asins = None
        self.normalized_inputs = []

    def get_products_by_asins(self, asins):
        self.called_asins = asins
        if self._error is not None:
            raise self._error
        return self._raw_products

    def normalize_product(self, raw):
        self.normalized_inputs.append(raw)
        asin = raw["asin"].upper()
        if asin in self._normalized_products:
            return self._normalized_products[asin]
        return {
            "asin": asin,
            "title": raw["title"],
            "brand": "Test Brand",
            "manufacturer": None,
            "category_id": None,
            "category_name": None,
            "image_url": None,
            "amazon_url": f"https://www.amazon.co.jp/dp/{asin}",
            "keepa_url": f"https://keepa.com/#!product/5-{asin}",
            "current_price": 1980,
            "avg_price_30": 2000,
            "avg_price_90": 2100,
            "lowest_price_90": 1900,
            "highest_price_90": 2200,
            "sales_rank_current": None,
            "sales_rank_avg_30": None,
            "sales_rank_avg_90": None,
            "sales_rank_drops_30": 6,
            "sales_rank_drops_90": 12,
            "new_offer_count": 5,
            "used_offer_count": None,
            "fba_offer_count": None,
            "amazon_in_stock": False,
            "amazon_was_in_stock_90": False,
            "review_count": None,
            "rating": None,
            "raw_keepa_json": "{}",
            "jan": None,
            "ean": None,
        }


class FakeScoringService:
    def __init__(self):
        self.called_asins = []

    def apply_scoring(self, product):
        self.called_asins.append(product.asin)
        product.keepa_score = 77
        product.judgement = "watch"
        product.status = "unreviewed"
        return product


class MultiFakeKeepaClient:
    def __init__(self):
        self.called_asins = None

    def get_products_by_asins(self, asins):
        self.called_asins = list(asins)
        return [{"asin": asin, "title": f"商品 {asin}"} for asin in asins]

    def normalize_product(self, raw):
        asin = raw["asin"].upper()
        return {
            "asin": asin,
            "title": raw["title"],
            "brand": "Test Brand",
            "manufacturer": None,
            "category_id": None,
            "category_name": None,
            "image_url": None,
            "amazon_url": f"https://www.amazon.co.jp/dp/{asin}",
            "keepa_url": f"https://keepa.com/#!product/5-{asin}",
            "current_price": 1980,
            "avg_price_30": 2000,
            "avg_price_90": 2100,
            "lowest_price_90": 1900,
            "highest_price_90": 2200,
            "sales_rank_current": None,
            "sales_rank_avg_30": None,
            "sales_rank_avg_90": None,
            "sales_rank_drops_30": 6,
            "sales_rank_drops_90": 12,
            "new_offer_count": 5,
            "used_offer_count": None,
            "fba_offer_count": None,
            "amazon_in_stock": False,
            "amazon_was_in_stock_90": False,
            "review_count": None,
            "rating": None,
            "raw_keepa_json": "{}",
            "jan": None,
            "ean": None,
        }


def test_execute_asin_research_happy_path(app, db_schema):
    raw_products = [{"asin": "b0abc11111", "title": "Product A"}]
    keepa = FakeKeepaClient(raw_products=raw_products)
    scoring = FakeScoringService()
    service = ResearchService(keepa_client=keepa, scoring_service=scoring)

    with app.app_context():
        run = service.create_research_run_for_asins("Run A", "b0abc11111")
        finished = service.execute_asin_research(run.id)

        saved_run = db.session.get(ResearchRun, run.id)
        saved_product = Product.query.filter_by(asin="B0ABC11111").first()
        links = ProductResearchRun.query.filter_by(research_run_id=run.id).all()

    assert keepa.called_asins == ["B0ABC11111"]
    assert keepa.normalized_inputs == raw_products
    assert saved_product is not None
    assert saved_product.keepa_score == 77
    assert saved_product.judgement == "watch"
    assert saved_product.status == "unreviewed"
    assert saved_product.first_seen_at is not None
    assert saved_product.last_checked_at is not None
    assert len(links) == 1
    assert links[0].product_id == saved_product.id
    assert saved_run is not None
    assert finished.id == saved_run.id
    assert saved_run.status == ResearchRun.STATUS_COMPLETED
    assert saved_run.total_fetched == 1
    assert saved_run.total_saved == 1
    assert saved_run.error_message is None
    assert saved_run.finished_at is not None


def test_execute_asin_research_updates_existing_product_without_duplicate(app, db_schema):
    raw_products = [{"asin": "b0abc11111", "title": "Updated Title"}]
    keepa = FakeKeepaClient(
        raw_products=raw_products,
        normalized_products={
            "B0ABC11111": {
                "asin": "B0ABC11111",
                "title": "Updated Title",
                "brand": "Updated Brand",
                "manufacturer": None,
                "category_id": None,
                "category_name": None,
                "image_url": None,
                "amazon_url": "https://www.amazon.co.jp/dp/B0ABC11111",
                "keepa_url": "https://keepa.com/#!product/5-B0ABC11111",
                "current_price": 2200,
                "avg_price_30": 2300,
                "avg_price_90": 2400,
                "lowest_price_90": 2100,
                "highest_price_90": 2600,
                "sales_rank_current": None,
                "sales_rank_avg_30": None,
                "sales_rank_avg_90": None,
                "sales_rank_drops_30": 8,
                "sales_rank_drops_90": 15,
                "new_offer_count": 4,
                "used_offer_count": None,
                "fba_offer_count": None,
                "amazon_in_stock": False,
                "amazon_was_in_stock_90": False,
                "review_count": None,
                "rating": None,
                "raw_keepa_json": "{}",
                "jan": None,
                "ean": None,
            }
        },
    )
    scoring = FakeScoringService()
    service = ResearchService(keepa_client=keepa, scoring_service=scoring)

    with app.app_context():
        existing = Product(asin="B0ABC11111", title="Old Title")
        existing.first_seen_at = datetime(2024, 1, 1, 0, 0, 0)
        existing.last_checked_at = None
        db.session.add(existing)
        db.session.commit()
        existing_id = existing.id
        old_first_seen = existing.first_seen_at

        run = service.create_research_run_for_asins(None, "b0abc11111")
        service.execute_asin_research(run.id)

        products = Product.query.filter_by(asin="B0ABC11111").all()
        updated = products[0]

    assert len(products) == 1
    assert updated.id == existing_id
    assert updated.title == "Updated Title"
    assert updated.brand == "Updated Brand"
    assert updated.first_seen_at == old_first_seen
    assert updated.last_checked_at is not None


def test_link_product_to_research_run_does_not_duplicate(app, db_schema):
    raw_products = [{"asin": "b0abc11111", "title": "Product A"}]
    keepa = FakeKeepaClient(raw_products=raw_products)
    scoring = FakeScoringService()
    service = ResearchService(keepa_client=keepa, scoring_service=scoring)

    with app.app_context():
        run = service.create_research_run_for_asins(None, "b0abc11111")
        service.execute_asin_research(run.id)
        service.execute_asin_research(run.id)
        product = Product.query.filter_by(asin="B0ABC11111").first()
        links = ProductResearchRun.query.filter_by(
            product_id=product.id,
            research_run_id=run.id,
        ).all()

    assert product is not None
    assert len(links) == 1


def test_execute_asin_research_marks_failed_and_redacts_sensitive_error(app, db_schema):
    keepa = FakeKeepaClient(
        raw_products=[],
        error=RuntimeError("apiKey=SECRET123 key=TOPSECRET accessKey=XYZ"),
    )
    service = ResearchService(keepa_client=keepa, scoring_service=FakeScoringService())

    with app.app_context():
        run = service.create_research_run_for_asins(None, "b0abc11111")
        with pytest.raises(ResearchServiceError):
            service.execute_asin_research(run.id)
        failed = db.session.get(ResearchRun, run.id)

    assert failed is not None
    assert failed.status == ResearchRun.STATUS_FAILED
    assert failed.error_message is not None
    assert "[REDACTED]" in failed.error_message
    assert "SECRET123" not in failed.error_message
    assert "TOPSECRET" not in failed.error_message
    assert "XYZ" not in failed.error_message
    assert failed.finished_at is not None


def test_execute_asin_research_raises_for_missing_run(app, db_schema):
    service = ResearchService(keepa_client=FakeKeepaClient([]), scoring_service=FakeScoringService())
    with app.app_context():
        with pytest.raises(ResearchServiceError):
            service.execute_asin_research(999999)


def test_execute_asin_research_invalid_conditions_json_fails_run(app, db_schema):
    service = ResearchService(keepa_client=FakeKeepaClient([]), scoring_service=FakeScoringService())

    with app.app_context():
        run = ResearchRun(
            name="Broken Conditions",
            status=ResearchRun.STATUS_PENDING,
            conditions_json="{not-json}",
            total_requested=1,
            total_fetched=0,
            total_saved=0,
        )
        db.session.add(run)
        db.session.commit()

        with pytest.raises(ResearchServiceError):
            service.execute_asin_research(run.id)
        failed = db.session.get(ResearchRun, run.id)

    assert failed is not None
    assert failed.status == ResearchRun.STATUS_FAILED
    assert failed.error_message is not None


def test_execute_asin_research_multiple_asins_saves_products_scores_and_links(app, db_schema):
    keepa = MultiFakeKeepaClient()
    scoring = FakeScoringService()
    service = ResearchService(keepa_client=keepa, scoring_service=scoring)

    with app.app_context():
        run = service.create_research_run_for_asins(
            "Multi ASIN Run",
            "b0abc11111\nb0def22222",
        )
        finished = service.execute_asin_research(run.id)

        products = Product.query.order_by(Product.asin.asc()).all()
        links = ProductResearchRun.query.filter_by(research_run_id=run.id).all()
        saved_run = db.session.get(ResearchRun, run.id)

    assert keepa.called_asins == ["B0ABC11111", "B0DEF22222"]
    assert finished.status == ResearchRun.STATUS_COMPLETED
    assert saved_run is not None
    assert saved_run.total_fetched == 2
    assert saved_run.total_saved == 2
    assert len(products) == 2
    assert len(links) == 2
    for product in products:
        assert product.keepa_score == 77
        assert product.judgement == "watch"
        assert product.status == "unreviewed"
        assert product.last_checked_at is not None
    assert set(scoring.called_asins) == {"B0ABC11111", "B0DEF22222"}


def test_reresearch_same_asins_updates_products_without_duplicates_and_adds_new_run_links(
    app, db_schema
):
    keepa = MultiFakeKeepaClient()
    scoring = FakeScoringService()
    service = ResearchService(keepa_client=keepa, scoring_service=scoring)

    with app.app_context():
        run1 = service.create_research_run_for_asins(None, "b0abc11111\nb0def22222")
        service.execute_asin_research(run1.id)

        run2 = service.create_research_run_for_asins(None, "b0abc11111\nb0def22222")
        service.execute_asin_research(run2.id)

        products = Product.query.order_by(Product.asin.asc()).all()
        run1_links = ProductResearchRun.query.filter_by(research_run_id=run1.id).all()
        run2_links = ProductResearchRun.query.filter_by(research_run_id=run2.id).all()
        all_links = ProductResearchRun.query.all()

    assert len(products) == 2
    assert len(run1_links) == 2
    assert len(run2_links) == 2
    assert len(all_links) == 4


def test_phase6_acceptance_end_to_end_for_save_update_score_and_links(app, db_schema):
    keepa = MultiFakeKeepaClient()
    scoring = FakeScoringService()
    service = ResearchService(keepa_client=keepa, scoring_service=scoring)

    with app.app_context():
        run1 = service.create_research_run_for_asins("Phase6 Acceptance", "b0abc11111")
        service.execute_asin_research(run1.id)

        first_run = db.session.get(ResearchRun, run1.id)
        product = Product.query.filter_by(asin="B0ABC11111").first()
        first_product_id = product.id
        first_checked_at = product.last_checked_at
        first_seen_at = product.first_seen_at
        first_links = ProductResearchRun.query.filter_by(research_run_id=run1.id).all()

        run2 = service.create_research_run_for_asins("Phase6 Acceptance Rerun", "b0abc11111")
        service.execute_asin_research(run2.id)

        second_run = db.session.get(ResearchRun, run2.id)
        products = Product.query.filter_by(asin="B0ABC11111").all()
        updated = products[0]
        second_links = ProductResearchRun.query.filter_by(research_run_id=run2.id).all()
        all_links = ProductResearchRun.query.filter_by(product_id=updated.id).all()

        first_run_status = first_run.status
        first_run_total_fetched = first_run.total_fetched
        first_run_total_saved = first_run.total_saved
        first_product_keepa_score = product.keepa_score
        first_product_judgement = product.judgement
        first_product_status = product.status
        second_run_status = second_run.status
        updated_first_seen_at = updated.first_seen_at
        updated_last_checked_at = updated.last_checked_at

    assert first_run is not None
    assert first_run_status == ResearchRun.STATUS_COMPLETED
    assert first_run_total_fetched == 1
    assert first_run_total_saved == 1

    assert product is not None
    assert first_product_keepa_score is not None
    assert first_product_judgement is not None
    assert first_product_status is not None
    assert len(first_links) == 1

    assert second_run is not None
    assert second_run_status == ResearchRun.STATUS_COMPLETED
    assert len(products) == 1
    assert updated.id == first_product_id
    assert updated_first_seen_at == first_seen_at
    assert updated_last_checked_at is not None
    assert updated_last_checked_at >= first_checked_at
    assert len(second_links) == 1
    assert len(all_links) == 2


def _valid_keyword_values(**overrides):
    values = {
        "name": "Keyword Run",
        "keyword": "水筒",
        "category_id": "12345",
        "min_price": "1500",
        "max_price": "10000",
        "min_review_count": "10",
        "max_review_count": "99999",
        "min_offer_count": "3",
        "max_offer_count": "15",
        "exclude_amazon_in_stock": "true",
        "min_sales_rank_drops_90": "10",
        "limit": "100",
        "fetch_mode": "light",
    }
    values.update(overrides)
    return values


def test_build_keyword_conditions_returns_expected_shape():
    service = ResearchService()

    conditions = service.build_keyword_conditions(_valid_keyword_values())

    assert conditions == {
        "type": "keyword",
        "name": "Keyword Run",
        "keyword": "水筒",
        "category_id": "12345",
        "filters": {
            "min_price": 1500,
            "max_price": 10000,
            "min_review_count": 10,
            "max_review_count": 99999,
            "min_offer_count": 3,
            "max_offer_count": 15,
            "exclude_amazon_in_stock": True,
            "min_sales_rank_drops_90": 10,
        },
        "limit": 100,
        "fetch_mode": "light",
    }


@pytest.mark.parametrize(
    "values",
    [
        {"keyword": ""},
        {"keyword": "   "},
    ],
)
def test_build_keyword_conditions_raises_when_keyword_empty(values):
    service = ResearchService()
    with pytest.raises(ResearchServiceError):
        service.build_keyword_conditions(_valid_keyword_values(**values))


def test_build_keyword_conditions_raises_when_min_price_gt_max_price():
    service = ResearchService()
    with pytest.raises(ResearchServiceError):
        service.build_keyword_conditions(_valid_keyword_values(min_price="10001", max_price="10000"))


def test_build_keyword_conditions_raises_when_min_review_gt_max_review():
    service = ResearchService()
    with pytest.raises(ResearchServiceError):
        service.build_keyword_conditions(
            _valid_keyword_values(min_review_count="100", max_review_count="99")
        )


def test_build_keyword_conditions_raises_when_min_offer_gt_max_offer():
    service = ResearchService()
    with pytest.raises(ResearchServiceError):
        service.build_keyword_conditions(_valid_keyword_values(min_offer_count="16", max_offer_count="15"))


@pytest.mark.parametrize("limit", ["0", "101"])
def test_build_keyword_conditions_raises_when_limit_out_of_range(limit):
    service = ResearchService()
    with pytest.raises(ResearchServiceError):
        service.build_keyword_conditions(_valid_keyword_values(limit=limit))


@pytest.mark.parametrize("raw_value", ["true", "on", "1"])
def test_build_keyword_conditions_parses_true_like_exclude_amazon(raw_value):
    service = ResearchService()
    conditions = service.build_keyword_conditions(
        _valid_keyword_values(exclude_amazon_in_stock=raw_value)
    )
    assert conditions["filters"]["exclude_amazon_in_stock"] is True


@pytest.mark.parametrize("raw_value", ["false", "", "0"])
def test_build_keyword_conditions_parses_false_like_exclude_amazon(raw_value):
    service = ResearchService()
    conditions = service.build_keyword_conditions(
        _valid_keyword_values(exclude_amazon_in_stock=raw_value)
    )
    assert conditions["filters"]["exclude_amazon_in_stock"] is False


def test_build_keyword_conditions_uses_defaults_for_optional_empty_values():
    service = ResearchService()
    conditions = service.build_keyword_conditions(
        {
            "keyword": "ボトル",
            "category_id": "",
        }
    )

    assert conditions["name"] == ResearchService.DEFAULT_KEYWORD_RUN_NAME
    assert conditions["category_id"] is None
    assert conditions["filters"]["min_price"] == 1500
    assert conditions["filters"]["max_price"] == 10000
    assert conditions["filters"]["min_review_count"] == 10
    assert conditions["filters"]["max_review_count"] == 99999
    assert conditions["limit"] == 100


def test_create_research_run_for_keyword_creates_pending_row(app, db_schema):
    service = ResearchService()

    with app.app_context():
        run = service.create_research_run_for_keyword(_valid_keyword_values())
        saved = db.session.get(ResearchRun, run.id)

    assert saved is not None
    assert saved.status == ResearchRun.STATUS_PENDING
    assert saved.name == "Keyword Run"
    assert saved.keyword == "水筒"
    assert saved.category_id == "12345"
    assert saved.total_requested == 100
    assert saved.total_fetched == 0
    assert saved.total_saved == 0
    assert saved.error_message is None
    assert saved.started_at is None
    assert saved.finished_at is None

    conditions = json.loads(saved.conditions_json)
    assert conditions["type"] == "keyword"
    assert conditions["keyword"] == "水筒"
    assert conditions["filters"]["min_price"] == 1500
    assert conditions["filters"]["exclude_amazon_in_stock"] is True
    assert conditions["limit"] == 100
    assert conditions["fetch_mode"] == "light"


def test_create_research_run_for_keyword_rolls_back_on_commit_failure():
    failing_session = FailingSession()
    service = ResearchService(db_session=failing_session)

    with pytest.raises(ResearchServiceError):
        service.create_research_run_for_keyword(_valid_keyword_values())

    assert len(failing_session.added) == 1
    assert failing_session.rollback_called is True


class FakeKeywordKeepaClient:
    def __init__(self, raw_products=None, error=None, token_status=None):
        self.search_calls = []
        self.normalized_inputs = []
        self._raw_products = raw_products
        self._error = error
        self._token_status = token_status

    def get_token_status(self, allow_depleted=False):
        if self._token_status is None:
            raise AttributeError("token status unavailable")
        return self._token_status

    def search_products(self, keyword, category_id=None, limit=100, filters=None, fetch_mode="light"):
        self.search_calls.append(
            {
                "keyword": keyword,
                "category_id": category_id,
                "limit": limit,
                "filters": filters,
                "fetch_mode": fetch_mode,
            }
        )
        if self._error is not None:
            raise self._error
        if self._raw_products is not None:
            return self._raw_products
        return [
            {"asin": "B0GOOD0001", "title": "条件一致商品"},
            {"asin": "B0BAD00002", "title": "条件不一致商品"},
        ]

    def normalize_product(self, raw):
        self.normalized_inputs.append(raw)
        if raw["asin"] == "B0GOOD0001":
            return {
                "asin": raw["asin"],
                "title": raw["title"],
                "brand": "Test Brand",
                "current_price": 1980,
                "avg_price_90": 2100,
                "lowest_price_90": 1900,
                "highest_price_90": 2200,
                "review_count": 30,
                "sales_rank_drops_90": 12,
                "new_offer_count": 5,
                "amazon_in_stock": False,
                "amazon_was_in_stock_90": False,
                "raw_keepa_json": "{}",
            }
        return {
            "asin": raw["asin"],
            "title": raw["title"],
            "brand": "Test Brand",
            "current_price": 500,
            "avg_price_90": 600,
            "lowest_price_90": 500,
            "highest_price_90": 700,
            "review_count": 1,
            "sales_rank_drops_90": 1,
            "new_offer_count": 50,
            "amazon_in_stock": True,
            "amazon_was_in_stock_90": True,
            "raw_keepa_json": "{}",
        }


class FakeKeywordScoringService:
    def __init__(self):
        self.called_asins = []

    def apply_scoring(self, product):
        self.called_asins.append(product.asin)
        product.keepa_score = 88
        product.judgement = Product.JUDGEMENT_GOOD
        product.status = Product.STATUS_CANDIDATE
        return product


def test_product_matches_keyword_filters_returns_true_for_matching_data():
    service = ResearchService()
    assert service.product_matches_keyword_filters(
        {
            "current_price": 1980,
            "review_count": 30,
            "new_offer_count": 5,
            "amazon_in_stock": False,
            "sales_rank_drops_90": 12,
        },
        _valid_keyword_values(),
    ) is True


def test_estimate_keyword_research_tokens_for_limit_5():
    service = ResearchService()

    estimate = service.estimate_keyword_research_tokens(
        limit=5,
        tokens_left=8,
        fetch_mode="detail",
    )

    assert estimate["search_tokens"] == 1
    assert estimate["detail_tokens"] == 30
    assert estimate["estimated_total"] == 31
    assert estimate["recommended_limit"] == 1


def test_keyword_token_estimate_differs_by_fetch_mode():
    service = ResearchService()

    light = service.estimate_keyword_research_tokens(
        limit=5,
        tokens_left=8,
        fetch_mode="light",
    )
    detail = service.estimate_keyword_research_tokens(
        limit=5,
        tokens_left=8,
        fetch_mode="detail",
    )

    assert light["fetch_mode"] == "light"
    assert detail["fetch_mode"] == "detail"
    assert light["estimated_total"] == 6
    assert detail["estimated_total"] == 31
    assert light["estimated_total"] < detail["estimated_total"]


def test_keyword_research_preflight_blocks_when_tokens_insufficient():
    service = ResearchService()

    with pytest.raises(ResearchServiceError) as exc_info:
        service.check_keyword_research_token_preflight(
            limit=5,
            token_status={"tokens_left": 8},
            fetch_mode="detail",
        )

    assert exc_info.value.error_type == "token_insufficient"
    assert "現在使えるトークンは 8" in str(exc_info.value)
    assert "取得上限5件" in str(exc_info.value)


def test_keyword_research_preflight_allows_when_tokens_sufficient():
    service = ResearchService()

    estimate = service.check_keyword_research_token_preflight(
        limit=5,
        token_status={"tokens_left": 40},
        fetch_mode="detail",
    )

    assert estimate["estimated_total"] == 31
    assert estimate["recommended_limit"] == 5


def test_token_preflight_message_does_not_leak_api_key():
    service = ResearchService()
    estimate = service.estimate_keyword_research_tokens(
        limit=5,
        tokens_left=8,
        fetch_mode="detail",
    )

    message = service.build_keyword_token_preflight_message(
        "8",
        {**estimate, "secret": "apiKey=SECRET_KEEPA_KEY_123"},
    )

    assert "SECRET_KEEPA_KEY_123" not in message
    assert "apiKey" not in message


@pytest.mark.parametrize(
    "product_data",
    [
        {"current_price": 1000, "review_count": 30, "new_offer_count": 5, "amazon_in_stock": False, "sales_rank_drops_90": 12},
        {"current_price": 12000, "review_count": 30, "new_offer_count": 5, "amazon_in_stock": False, "sales_rank_drops_90": 12},
        {"current_price": 1980, "review_count": 1, "new_offer_count": 5, "amazon_in_stock": False, "sales_rank_drops_90": 12},
        {"current_price": 1980, "review_count": 100000, "new_offer_count": 5, "amazon_in_stock": False, "sales_rank_drops_90": 12},
        {"current_price": 1980, "review_count": 30, "new_offer_count": 1, "amazon_in_stock": False, "sales_rank_drops_90": 12},
        {"current_price": 1980, "review_count": 30, "new_offer_count": 20, "amazon_in_stock": False, "sales_rank_drops_90": 12},
        {"current_price": 1980, "review_count": 30, "new_offer_count": 5, "amazon_in_stock": True, "sales_rank_drops_90": 12},
        {"current_price": 1980, "review_count": 30, "new_offer_count": 5, "amazon_in_stock": False, "sales_rank_drops_90": 1},
    ],
)
def test_product_matches_keyword_filters_returns_false_for_non_matching_data(product_data):
    service = ResearchService()
    assert service.product_matches_keyword_filters(product_data, _valid_keyword_values()) is False


def test_execute_keyword_research_searches_normalizes_saves_scores_links_and_completes(app, db_schema):
    keepa = FakeKeywordKeepaClient()
    scoring = FakeKeywordScoringService()
    service = ResearchService(keepa_client=keepa, scoring_service=scoring)

    with app.app_context():
        run = service.create_research_run_for_keyword(_valid_keyword_values(limit="50"))
        finished = service.execute_keyword_research(run.id)

        saved_run = db.session.get(ResearchRun, run.id)
        products = Product.query.order_by(Product.asin.asc()).all()
        links = ProductResearchRun.query.filter_by(research_run_id=run.id).all()

    assert keepa.search_calls == [
        {
            "keyword": "水筒",
            "category_id": "12345",
            "limit": 50,
            "filters": {
                "min_price": 1500,
                "max_price": 10000,
                "min_review_count": 10,
                "max_review_count": 99999,
                "min_offer_count": 3,
                "max_offer_count": 15,
                "exclude_amazon_in_stock": True,
                "min_sales_rank_drops_90": 10,
            },
            "fetch_mode": "light",
        }
    ]
    assert keepa.normalized_inputs == [
        {"asin": "B0GOOD0001", "title": "条件一致商品"},
        {"asin": "B0BAD00002", "title": "条件不一致商品"},
    ]
    assert finished.id == saved_run.id
    assert saved_run.status == ResearchRun.STATUS_COMPLETED
    assert saved_run.total_fetched == 2
    assert saved_run.total_saved == 2
    assert len(products) == 2
    assert len(links) == 2
    assert set(scoring.called_asins) == {"B0GOOD0001", "B0BAD00002"}

    good = Product.query.filter_by(asin="B0GOOD0001").first()
    bad = Product.query.filter_by(asin="B0BAD00002").first()
    assert good.keepa_score == 88
    assert good.judgement == Product.JUDGEMENT_GOOD
    assert good.status == Product.STATUS_CANDIDATE
    assert bad.keepa_score == 88
    assert bad.judgement == Product.JUDGEMENT_BAD
    assert bad.status == Product.STATUS_EXCLUDED


def test_keyword_light_mode_does_not_break_existing_flow(app, db_schema):
    keepa = FakeKeywordKeepaClient(token_status={"tokens_left": 8})
    scoring = FakeKeywordScoringService()
    service = ResearchService(keepa_client=keepa, scoring_service=scoring)

    with app.app_context():
        run = service.create_research_run_for_keyword(
            _valid_keyword_values(limit="5", fetch_mode="light")
        )
        service.execute_keyword_research(run.id)
        saved_run = db.session.get(ResearchRun, run.id)

    assert saved_run.status == ResearchRun.STATUS_COMPLETED
    assert saved_run.total_fetched == 2
    assert keepa.search_calls[0]["fetch_mode"] == "light"


def test_execute_keyword_research_updates_existing_product_without_duplicate(app, db_schema):
    keepa = FakeKeywordKeepaClient(raw_products=[{"asin": "B0GOOD0001", "title": "更新タイトル"}])
    scoring = FakeKeywordScoringService()
    service = ResearchService(keepa_client=keepa, scoring_service=scoring)

    with app.app_context():
        existing = Product(asin="B0GOOD0001", title="古いタイトル")
        existing.first_seen_at = datetime(2024, 1, 1, 0, 0, 0)
        db.session.add(existing)
        db.session.commit()
        existing_id = existing.id
        first_seen_at = existing.first_seen_at

        run = service.create_research_run_for_keyword(_valid_keyword_values())
        service.execute_keyword_research(run.id)
        products = Product.query.filter_by(asin="B0GOOD0001").all()
        updated = products[0]

    assert len(products) == 1
    assert updated.id == existing_id
    assert updated.title == "更新タイトル"
    assert updated.first_seen_at == first_seen_at
    assert updated.last_checked_at is not None


def test_execute_keyword_research_marks_failed_on_keepa_error_and_redacts_secret(app, db_schema):
    keepa = FakeKeywordKeepaClient(error=RuntimeError("apiKey=SECRET123 key=TOPSECRET"))
    service = ResearchService(keepa_client=keepa, scoring_service=FakeKeywordScoringService())

    with app.app_context():
        run = service.create_research_run_for_keyword(_valid_keyword_values())
        with pytest.raises(ResearchServiceError):
            service.execute_keyword_research(run.id)
        failed = db.session.get(ResearchRun, run.id)

    assert failed.status == ResearchRun.STATUS_FAILED
    assert failed.error_message is not None
    assert "SECRET123" not in failed.error_message
    assert "TOPSECRET" not in failed.error_message
    assert "[REDACTED]" in failed.error_message
    assert failed.finished_at is not None


def test_execute_keyword_research_preflight_blocks_before_keepa_search(app, db_schema):
    keepa = FakeKeywordKeepaClient(token_status={"tokens_left": 8})
    service = ResearchService(
        keepa_client=keepa,
        scoring_service=FakeKeywordScoringService(),
    )

    with app.app_context():
        run = service.create_research_run_for_keyword(
            _valid_keyword_values(limit="5", fetch_mode="detail")
        )
        with pytest.raises(ResearchServiceError):
            service.execute_keyword_research(run.id)
        failed = db.session.get(ResearchRun, run.id)

    assert keepa.search_calls == []
    assert failed.status == ResearchRun.STATUS_FAILED
    assert failed.error_message is not None
    assert "SECRET" not in failed.error_message


def test_execute_keyword_research_raises_for_missing_run(app, db_schema):
    service = ResearchService(keepa_client=FakeKeywordKeepaClient(), scoring_service=FakeKeywordScoringService())
    with app.app_context():
        with pytest.raises(ResearchServiceError):
            service.execute_keyword_research(999999)


def test_execute_keyword_research_invalid_conditions_json_fails_run(app, db_schema):
    service = ResearchService(keepa_client=FakeKeywordKeepaClient(), scoring_service=FakeKeywordScoringService())

    with app.app_context():
        run = ResearchRun(
            name="Broken Keyword Conditions",
            status=ResearchRun.STATUS_PENDING,
            conditions_json="{not-json}",
            total_requested=1,
            total_fetched=0,
            total_saved=0,
        )
        db.session.add(run)
        db.session.commit()

        with pytest.raises(ResearchServiceError):
            service.execute_keyword_research(run.id)
        failed = db.session.get(ResearchRun, run.id)

    assert failed.status == ResearchRun.STATUS_FAILED
    assert failed.error_message is not None


def test_execute_keyword_research_non_keyword_conditions_fail_run(app, db_schema):
    service = ResearchService(keepa_client=FakeKeywordKeepaClient(), scoring_service=FakeKeywordScoringService())

    with app.app_context():
        run = service.create_research_run_for_asins("ASIN Run", "B0ABC11111")
        with pytest.raises(ResearchServiceError):
            service.execute_keyword_research(run.id)
        failed = db.session.get(ResearchRun, run.id)

    assert failed.status == ResearchRun.STATUS_FAILED
    assert failed.error_message is not None


def test_phase10_keyword_research_acceptance_service_flow(app, db_schema):
    keepa = FakeKeywordKeepaClient()
    scoring = FakeKeywordScoringService()
    service = ResearchService(keepa_client=keepa, scoring_service=scoring)

    with app.app_context():
        values = _valid_keyword_values(keyword="Bottle", category_id="98765", limit="25")
        run1 = service.create_research_run_for_keyword(values)
        service.execute_keyword_research(run1.id)

        run2 = service.create_research_run_for_keyword(values)
        service.execute_keyword_research(run2.id)

        saved_run1 = db.session.get(ResearchRun, run1.id)
        saved_run2 = db.session.get(ResearchRun, run2.id)
        products = Product.query.order_by(Product.asin.asc()).all()
        good = Product.query.filter_by(asin="B0GOOD0001").first()
        bad = Product.query.filter_by(asin="B0BAD00002").first()
        run1_links = ProductResearchRun.query.filter_by(research_run_id=run1.id).all()
        run2_links = ProductResearchRun.query.filter_by(research_run_id=run2.id).all()
        all_links = ProductResearchRun.query.all()

    assert keepa.search_calls[0] == {
        "keyword": "Bottle",
        "category_id": "98765",
        "limit": 25,
        "filters": {
            "min_price": 1500,
            "max_price": 10000,
            "min_review_count": 10,
            "max_review_count": 99999,
            "min_offer_count": 3,
            "max_offer_count": 15,
            "exclude_amazon_in_stock": True,
            "min_sales_rank_drops_90": 10,
        },
        "fetch_mode": "light",
    }
    assert len(keepa.search_calls) == 2
    assert saved_run1.status == ResearchRun.STATUS_COMPLETED
    assert saved_run1.total_fetched == 2
    assert saved_run1.total_saved == 2
    assert saved_run2.status == ResearchRun.STATUS_COMPLETED
    assert len(products) == 2
    assert good.keepa_score == 88
    assert good.judgement == Product.JUDGEMENT_GOOD
    assert good.status == Product.STATUS_CANDIDATE
    assert bad.judgement == Product.JUDGEMENT_BAD
    assert bad.status == Product.STATUS_EXCLUDED
    assert len(run1_links) == 2
    assert len(run2_links) == 2
    assert len(all_links) == 4


def test_execute_asin_research_keepa_error_marks_run_failed_safely(app, db_schema):
    secret = "SECRET_KEEPA_KEY_123"
    keepa = FakeKeepaClient(
        raw_products=[],
        error=KeepaApiError(f"apiKey={secret}", error_type="invalid_api_key"),
    )
    service = ResearchService(keepa_client=keepa, scoring_service=FakeScoringService())

    with app.app_context():
        run = service.create_research_run_for_asins("Safe ASIN Failure", "B0ABC11111")
        with pytest.raises(ResearchServiceError):
            service.execute_asin_research(run.id)
        failed = db.session.get(ResearchRun, run.id)

    assert failed.status == ResearchRun.STATUS_FAILED
    assert "Keepa API Keyが正しくない可能性があります。" in failed.error_message
    assert secret not in failed.error_message
    assert "apiKey" not in failed.error_message
    assert failed.finished_at is not None


def test_execute_keyword_research_keepa_error_marks_run_failed_safely(app, db_schema):
    secret = "SECRET_KEEPA_KEY_123"
    keepa = FakeKeywordKeepaClient(
        error=KeepaApiError(f"key={secret}", error_type="token_insufficient")
    )
    service = ResearchService(keepa_client=keepa, scoring_service=FakeKeywordScoringService())

    with app.app_context():
        run = service.create_research_run_for_keyword(_valid_keyword_values())
        with pytest.raises(ResearchServiceError):
            service.execute_keyword_research(run.id)
        failed = db.session.get(ResearchRun, run.id)

    assert failed.status == ResearchRun.STATUS_FAILED
    assert "Keepa APIのトークンが不足しています。" in failed.error_message
    assert secret not in failed.error_message
    assert "key=" not in failed.error_message
    assert failed.finished_at is not None


def test_fail_research_run_masks_api_key_in_error_message(app, db_schema):
    secret = "SECRET_KEEPA_KEY_123"
    service = ResearchService()

    with app.app_context():
        run = service.create_research_run_for_asins("Manual Fail", "B0ABC11111")
        service.fail_research_run(run, RuntimeError(f"request failed key={secret}"))
        failed = db.session.get(ResearchRun, run.id)

    assert failed.status == ResearchRun.STATUS_FAILED
    assert secret not in failed.error_message
    assert "[REDACTED]" in failed.error_message


def test_execute_asin_research_db_save_error_rolls_back_and_fails_run(
    app, db_schema, monkeypatch
):
    keepa = FakeKeepaClient(raw_products=[{"asin": "B0ABC11111", "title": "Product A"}])
    service = ResearchService(keepa_client=keepa, scoring_service=FakeScoringService())

    def fail_save(product_data):
        raise ResearchServiceError(
            "DB save failed apiKey=SECRET_KEEPA_KEY_123",
            error_type="db_save_failed",
        )

    monkeypatch.setattr(service, "save_or_update_product", fail_save)

    with app.app_context():
        run = service.create_research_run_for_asins("DB Fail ASIN", "B0ABC11111")
        with pytest.raises(ResearchServiceError):
            service.execute_asin_research(run.id)
        failed = db.session.get(ResearchRun, run.id)

    assert failed.status == ResearchRun.STATUS_FAILED
    assert "データベース保存中にエラーが発生しました。" in failed.error_message
    assert "SECRET_KEEPA_KEY_123" not in failed.error_message
    assert failed.status != ResearchRun.STATUS_RUNNING


def test_execute_keyword_research_db_save_error_rolls_back_and_fails_run(
    app, db_schema, monkeypatch
):
    service = ResearchService(
        keepa_client=FakeKeywordKeepaClient(raw_products=[{"asin": "B0GOOD0001", "title": "Product A"}]),
        scoring_service=FakeKeywordScoringService(),
    )

    def fail_save(product_data):
        raise ResearchServiceError(
            "DB save failed token=SECRET_TOKEN_456",
            error_type="db_save_failed",
        )

    monkeypatch.setattr(service, "save_or_update_product", fail_save)

    with app.app_context():
        run = service.create_research_run_for_keyword(_valid_keyword_values())
        with pytest.raises(ResearchServiceError):
            service.execute_keyword_research(run.id)
        failed = db.session.get(ResearchRun, run.id)

    assert failed.status == ResearchRun.STATUS_FAILED
    assert "データベース保存中にエラーが発生しました。" in failed.error_message
    assert "SECRET_TOKEN_456" not in failed.error_message
    assert failed.status != ResearchRun.STATUS_RUNNING


def test_research_run_does_not_remain_running_on_unexpected_error(app, db_schema):
    class UnexpectedNormalizeErrorKeepa(FakeKeepaClient):
        def normalize_product(self, raw):
            raise RuntimeError("unexpected Authorization: Bearer SECRET_TOKEN_456")

    service = ResearchService(
        keepa_client=UnexpectedNormalizeErrorKeepa(
            raw_products=[{"asin": "B0ABC11111", "title": "Product A"}]
        ),
        scoring_service=FakeScoringService(),
    )

    with app.app_context():
        run = service.create_research_run_for_asins("Unexpected Fail", "B0ABC11111")
        with pytest.raises(ResearchServiceError):
            service.execute_asin_research(run.id)
        failed = db.session.get(ResearchRun, run.id)

    assert failed.status == ResearchRun.STATUS_FAILED
    assert "SECRET_TOKEN_456" not in failed.error_message
    assert failed.status != ResearchRun.STATUS_RUNNING


def test_data_insufficient_product_becomes_unknown_or_hold(app, db_schema):
    class MissingDataKeepa(FakeKeepaClient):
        def normalize_product(self, raw):
            return {
                "asin": raw["asin"],
                "title": raw["title"],
                "current_price": None,
                "avg_price_90": None,
                "sales_rank_drops_90": None,
                "new_offer_count": None,
                "amazon_in_stock": None,
                "raw_keepa_json": "{}",
            }

    service = ResearchService(
        keepa_client=MissingDataKeepa(raw_products=[{"asin": "B0ABC11111", "title": "Missing Data"}]),
        scoring_service=ScoringService(),
    )

    with app.app_context():
        run = service.create_research_run_for_asins("Missing Data Run", "B0ABC11111")
        service.execute_asin_research(run.id)
        product = Product.query.filter_by(asin="B0ABC11111").first()
        finished = db.session.get(ResearchRun, run.id)

    assert finished.status == ResearchRun.STATUS_COMPLETED
    assert product.judgement == Product.JUDGEMENT_UNKNOWN
    assert product.status == Product.STATUS_HOLD


def test_research_service_logs_do_not_leak_api_key(app, db_schema, caplog):
    secret = "SECRET_KEEPA_KEY_123"
    keepa = FakeKeepaClient(
        raw_products=[],
        error=KeepaApiError(f"request failed key={secret}", error_type="keepa_api_failed"),
    )
    service = ResearchService(keepa_client=keepa, scoring_service=FakeScoringService())

    with app.app_context(), caplog.at_level("ERROR"):
        run = service.create_research_run_for_asins("Logged Failure", "B0ABC11111")
        with pytest.raises(ResearchServiceError):
            service.execute_asin_research(run.id)

    assert secret not in caplog.text
    assert "[REDACTED]" in caplog.text
