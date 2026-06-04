from datetime import datetime, timedelta

import pytest

from app.extensions import db
from app.models import ResearchRun
from app.services.research_service import InvalidAsinInputError, ResearchServiceError


@pytest.fixture()
def db_schema(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        yield
        db.session.remove()
        db.drop_all()


class FakeResearchRun:
    def __init__(self, run_id=1):
        self.id = run_id


class FakeResearchService:
    def __init__(self):
        self.create_called = False
        self.execute_called = False
        self.keyword_create_called = False
        self.keyword_execute_called = False
        self.created_with = None
        self.executed_with = None
        self.keyword_created_with = None
        self.keyword_executed_with = None
        self.preflight_called = False
        self.preflight_fetch_mode = None

    def build_keyword_conditions(self, values):
        return {
            "limit": int(values.get("limit", 100)),
            "fetch_mode": values.get("fetch_mode", "light"),
        }

    def check_keyword_research_token_preflight(self, limit, fetch_mode="light"):
        self.preflight_called = True
        self.preflight_fetch_mode = fetch_mode
        return {"estimated_total": 31, "recommended_limit": min(int(limit), 5)}

    def build_keyword_token_guidance(self):
        return {
            "available": True,
            "tokens_left": 40,
            "tokens_available": 40,
            "recommended_limit": 5,
            "estimated_for_limit_5": 31,
            "message": "現在のトークンでは、キーワード検索は5件程度までが目安です。",
        }

    def create_research_run_for_asins(self, name, asin_text):
        self.create_called = True
        self.created_with = (name, asin_text)
        return FakeResearchRun(1)

    def execute_asin_research(self, research_run_id):
        self.execute_called = True
        self.executed_with = research_run_id
        return FakeResearchRun(research_run_id)

    def create_research_run_for_keyword(self, values):
        self.keyword_create_called = True
        self.keyword_created_with = values
        return FakeResearchRun(2)

    def execute_keyword_research(self, research_run_id):
        self.keyword_execute_called = True
        self.keyword_executed_with = research_run_id
        return FakeResearchRun(research_run_id)


@pytest.fixture()
def fake_service(monkeypatch):
    service = FakeResearchService()
    monkeypatch.setattr("app.routes.research.ResearchService", lambda: service)
    return service


def _create_run(
    name: str,
    status: str,
    total_requested: int = 0,
    total_fetched: int = 0,
    total_saved: int = 0,
    error_message: str | None = None,
    created_at: datetime | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
):
    run = ResearchRun(
        name=name,
        status=status,
        conditions_json='{"type":"asin"}',
        total_requested=total_requested,
        total_fetched=total_fetched,
        total_saved=total_saved,
        error_message=error_message,
        started_at=started_at,
        finished_at=finished_at,
        created_at=created_at or datetime.utcnow(),
    )
    db.session.add(run)
    return run


def _valid_keyword_form(**overrides):
    values = {
        "research_type": "keyword",
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


def test_get_research_new_returns_200(client, db_schema):
    response = client.get("/research/new")
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "新規リサーチ" in text


def test_get_research_new_shows_form_fields(client, db_schema):
    response = client.get("/research/new")
    text = response.get_data(as_text=True)
    assert 'name="name"' in text
    assert 'name="asin_text"' in text
    assert "ASIN指定リサーチ" in text
    assert "ASINを改行またはカンマ区切り" in text


def test_get_research_new_shows_keyword_form(client, db_schema):
    text = client.get("/research/new").get_data(as_text=True)
    assert "キーワード検索リサーチ" in text
    assert "キーワードリサーチ開始" in text
    assert "実行処理は次のTaskで実装します" not in text
    assert "検索条件だけを保存" not in text
    assert 'name="keyword"' in text
    assert 'name="category_id"' in text
    assert 'name="min_price"' in text
    assert 'name="max_price"' in text
    assert 'name="min_review_count"' in text
    assert 'name="max_review_count"' in text
    assert 'name="min_offer_count"' in text
    assert 'name="max_offer_count"' in text
    assert 'name="exclude_amazon_in_stock"' in text
    assert 'name="min_sales_rank_drops_90"' in text
    assert 'name="limit"' in text
    assert 'name="fetch_mode"' in text
    assert 'value="light"' in text
    assert 'value="detail"' in text
    assert "軽量モード" in text
    assert "詳細モード" in text


def test_research_new_displays_token_recommendation(client, db_schema, monkeypatch):
    monkeypatch.setattr(
        "app.routes.research._get_keyword_token_guidance",
        lambda: {
            "available": True,
            "tokens_left": 8,
            "tokens_available": 8,
            "recommended_limit": 1,
            "estimated_for_limit_5": 31,
            "message": "現在のトークンでは、キーワード検索は1件程度がおすすめです。",
        },
    )

    text = client.get("/research/new").get_data(as_text=True)

    assert "キーワード検索のトークン目安" in text
    assert "現在使えるトークン: 8" in text
    assert "推奨取得上限: 1件程度" in text
    assert "取得上限5件の目安: 約31トークン" in text
    assert "ASIN指定より多くのトークンを消費します" in text


def test_research_forms_have_research_type_hidden_fields(client, db_schema):
    text = client.get("/research/new").get_data(as_text=True)
    assert 'name="research_type" value="asin"' in text
    assert 'name="research_type" value="keyword"' in text


def test_get_research_new_shows_empty_history_message(client, db_schema):
    response = client.get("/research/new")
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "まだリサーチ履歴はありません。" in text


def test_get_research_new_shows_recent_history_rows(client, app, db_schema):
    with app.app_context():
        _create_run("Completed Run", ResearchRun.STATUS_COMPLETED, 3, 2, 2)
        _create_run(
            "Failed Run",
            ResearchRun.STATUS_FAILED,
            4,
            0,
            0,
            error_message="Keepa request failed",
        )
        db.session.commit()

    response = client.get("/research/new")
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Completed Run" in text
    assert "Failed Run" in text
    assert "completed" in text
    assert "failed" in text
    assert "3" in text
    assert "2" in text
    assert "4" in text
    assert "Keepa request failed" in text


def test_research_new_recent_runs_display_jst(client, app, db_schema):
    with app.app_context():
        _create_run(
            "JST Run",
            ResearchRun.STATUS_COMPLETED,
            1,
            1,
            1,
            started_at=datetime(2026, 6, 4, 0, 30, 0),
            finished_at=datetime(2026, 6, 4, 1, 0, 0),
        )
        db.session.commit()

    response = client.get("/research/new")
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "開始日時（JST）" in text
    assert "終了日時（JST）" in text
    assert "2026-06-04 09:30" in text
    assert "2026-06-04 10:00" in text
    assert "2026-06-04 00:30" not in text


def test_get_research_new_limits_history_to_10(client, app, db_schema):
    with app.app_context():
        now = datetime.utcnow()
        for index in range(12):
            _create_run(
                name=f"Run {index}",
                status=ResearchRun.STATUS_COMPLETED,
                created_at=now - timedelta(minutes=index),
            )
        db.session.commit()

    response = client.get("/research/new")
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    for index in range(10):
        assert f"Run {index}" in text
    assert "Run 10" not in text
    assert "Run 11" not in text


def test_post_research_new_calls_create_and_execute(client, db_schema, fake_service):
    response = client.post(
        "/research/new",
        data={"research_type": "asin", "name": "My Run", "asin_text": "B0ABC11111"},
    )
    assert response.status_code == 302
    assert fake_service.create_called is True
    assert fake_service.execute_called is True
    assert fake_service.created_with == ("My Run", "B0ABC11111")
    assert fake_service.executed_with == 1
    assert fake_service.keyword_create_called is False


def test_post_research_new_without_research_type_keeps_existing_asin_flow(
    client, db_schema, fake_service
):
    response = client.post(
        "/research/new",
        data={"name": "My Run", "asin_text": "B0ABC11111"},
    )
    assert response.status_code == 302
    assert fake_service.create_called is True
    assert fake_service.execute_called is True


def test_post_research_new_success_redirects_and_flashes(client, db_schema, fake_service):
    response = client.post(
        "/research/new",
        data={"research_type": "asin", "name": "My Run", "asin_text": "B0ABC11111"},
        follow_redirects=True,
    )
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "ASINリサーチが完了しました。" in text


def test_post_research_new_failure_rerenders_form_with_200_and_keeps_input(
    client, db_schema, monkeypatch
):
    class FailingService:
        def create_research_run_for_asins(self, name, asin_text):
            raise ResearchServiceError("something failed")

        def execute_asin_research(self, research_run_id):
            return None

    monkeypatch.setattr("app.routes.research.ResearchService", lambda: FailingService())

    response = client.post(
        "/research/new",
        data={
            "research_type": "asin",
            "name": "失敗テスト",
            "asin_text": "B0ABC11111\nB0DEF22222",
        },
    )
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "ASINリサーチに失敗しました。" in text
    assert "失敗テスト" in text
    assert "B0ABC11111" in text
    assert "B0DEF22222" in text


def test_post_research_new_invalid_asin_shows_error(client, db_schema, monkeypatch):
    class InvalidInputService:
        def create_research_run_for_asins(self, name, asin_text):
            raise InvalidAsinInputError("invalid")

        def execute_asin_research(self, research_run_id):
            return None

    monkeypatch.setattr("app.routes.research.ResearchService", lambda: InvalidInputService())

    response = client.post(
        "/research/new",
        data={"research_type": "asin", "name": "bad", "asin_text": "@@@"},
    )
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "ASINリサーチに失敗しました。" in text
    assert "@@@" in text


def test_post_keyword_calls_create_research_run_for_keyword(client, db_schema, fake_service):
    response = client.post("/research/new", data=_valid_keyword_form())
    assert response.status_code == 302
    assert fake_service.preflight_called is True
    assert fake_service.preflight_fetch_mode == "light"
    assert fake_service.keyword_create_called is True
    assert fake_service.keyword_execute_called is True
    assert fake_service.create_called is False
    assert fake_service.execute_called is False
    assert fake_service.keyword_created_with.get("keyword") == "水筒"
    assert fake_service.keyword_created_with.get("fetch_mode") == "light"
    assert fake_service.keyword_executed_with == 2


def test_post_keyword_preflight_blocks_before_run_creation(client, db_schema, monkeypatch):
    class TokenBlockingKeywordService:
        def __init__(self):
            self.keyword_create_called = False

        def build_keyword_conditions(self, values):
            return {
                "limit": int(values.get("limit", 5)),
                "fetch_mode": values.get("fetch_mode", "light"),
            }

        def check_keyword_research_token_preflight(self, limit, fetch_mode="light"):
            raise ResearchServiceError(
                "現在使えるトークンは 8 です。取得上限5件には約31トークン以上を推奨します。",
                error_type="token_insufficient",
            )

        def create_research_run_for_keyword(self, values):
            self.keyword_create_called = True
            return FakeResearchRun(3)

        def execute_keyword_research(self, research_run_id):
            return FakeResearchRun(research_run_id)

        def build_keyword_token_guidance(self):
            return {
                "available": True,
                "tokens_available": 8,
                "recommended_limit": 1,
                "estimated_for_limit_5": 31,
                "message": "現在のトークンでは、キーワード検索は1件程度がおすすめです。",
            }

    service = TokenBlockingKeywordService()
    monkeypatch.setattr("app.routes.research.ResearchService", lambda: service)

    response = client.post("/research/new", data=_valid_keyword_form(limit="5"))
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "現在使えるトークンは 8" in text
    assert service.keyword_create_called is False


def test_post_keyword_success_redirects_and_flashes(client, db_schema, fake_service):
    response = client.post("/research/new", data=_valid_keyword_form(), follow_redirects=True)
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "キーワード検索リサーチが完了しました。" in text


def test_post_keyword_failure_rerenders_form_and_keeps_input(client, db_schema, monkeypatch):
    class FailingKeywordService:
        def create_research_run_for_keyword(self, values):
            raise ResearchServiceError("invalid keyword")

        def execute_keyword_research(self, research_run_id):
            return None

    monkeypatch.setattr("app.routes.research.ResearchService", lambda: FailingKeywordService())

    response = client.post(
        "/research/new",
        data=_valid_keyword_form(keyword="保存失敗キーワード", min_price="9999", max_price="1000"),
    )
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "キーワード検索リサーチに失敗しました。" in text
    assert "保存失敗キーワード" in text
    assert 'value="9999"' in text
    assert 'value="1000"' in text


def test_post_keyword_execute_failure_rerenders_without_leaking_error_details(
    client, db_schema, monkeypatch
):
    class ExecuteFailingKeywordService:
        def create_research_run_for_keyword(self, values):
            return FakeResearchRun(7)

        def execute_keyword_research(self, research_run_id):
            raise ResearchServiceError("apiKey=SECRET-KEEP-A-KEY")

    monkeypatch.setattr(
        "app.routes.research.ResearchService",
        lambda: ExecuteFailingKeywordService(),
    )

    response = client.post(
        "/research/new",
        data=_valid_keyword_form(keyword="実行失敗キーワード", min_price="2000"),
    )
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "キーワード検索リサーチに失敗しました。" in text
    assert "実行失敗キーワード" in text
    assert 'value="2000"' in text
    assert "SECRET-KEEP-A-KEY" not in text
    assert "apiKey" not in text


def test_research_route_failure_flashes_safe_error_message(client, db_schema, monkeypatch):
    class FailingService:
        def create_research_run_for_asins(self, name, asin_text):
            raise ResearchServiceError("unexpected key=SECRET_KEEPA_KEY_123")

        def execute_asin_research(self, research_run_id):
            return None

    monkeypatch.setattr("app.routes.research.ResearchService", lambda: FailingService())

    response = client.post(
        "/research/new",
        data={"research_type": "asin", "name": "Safe Flash", "asin_text": "B0ABC11111"},
    )
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "ASINリサーチに失敗しました。" in text
    assert "SECRET_KEEPA_KEY_123" not in text
    assert "unexpected" not in text


def test_research_route_failure_does_not_leak_api_key(client, db_schema, monkeypatch):
    class FailingKeywordService:
        def create_research_run_for_keyword(self, values):
            return FakeResearchRun(99)

        def execute_keyword_research(self, research_run_id):
            raise ResearchServiceError("apiKey=SECRET_KEEPA_KEY_123")

    monkeypatch.setattr("app.routes.research.ResearchService", lambda: FailingKeywordService())

    response = client.post("/research/new", data=_valid_keyword_form(), follow_redirects=True)
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "キーワード検索リサーチに失敗しました。" in text
    assert "SECRET_KEEPA_KEY_123" not in text
    assert "apiKey" not in text


def test_post_unknown_research_type_shows_error(client, db_schema):
    response = client.post(
        "/research/new",
        data={"research_type": "unknown", "name": "Unknown", "asin_text": "B0ABC11111"},
    )
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "不明なリサーチ種別が指定されました。" in text


def test_post_success_redirect_page_shows_completed_history(client, db_schema, monkeypatch):
    class PersistingSuccessService:
        def create_research_run_for_asins(self, name, asin_text):
            run = ResearchRun(
                name=name or "Route Success Run",
                status=ResearchRun.STATUS_PENDING,
                conditions_json='{"type":"asin","asins":["B0ABC11111"]}',
                total_requested=1,
                total_fetched=0,
                total_saved=0,
            )
            db.session.add(run)
            db.session.commit()
            return run

        def execute_asin_research(self, research_run_id):
            run = db.session.get(ResearchRun, research_run_id)
            run.status = ResearchRun.STATUS_COMPLETED
            run.total_fetched = 1
            run.total_saved = 1
            run.error_message = None
            run.started_at = datetime.utcnow()
            run.finished_at = datetime.utcnow()
            db.session.commit()
            return run

    monkeypatch.setattr(
        "app.routes.research.ResearchService",
        lambda: PersistingSuccessService(),
    )

    response = client.post(
        "/research/new",
        data={"research_type": "asin", "name": "Route Success Run", "asin_text": "B0ABC11111"},
        follow_redirects=True,
    )
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Route Success Run" in text
    assert "completed" in text
    assert "1" in text


def test_phase10_keyword_research_acceptance_route_flow(client, db_schema, fake_service):
    get_text = client.get("/research/new").get_data(as_text=True)
    assert "ASIN指定リサーチ" in get_text
    assert "キーワード検索リサーチ" in get_text

    keyword_response = client.post(
        "/research/new",
        data=_valid_keyword_form(keyword="水筒"),
        follow_redirects=True,
    )
    keyword_text = keyword_response.get_data(as_text=True)
    assert keyword_response.status_code == 200
    assert "キーワード検索リサーチが完了しました。" in keyword_text
    assert fake_service.keyword_create_called is True
    assert fake_service.keyword_execute_called is True
    assert fake_service.keyword_created_with.get("keyword") == "水筒"
    assert fake_service.keyword_executed_with == 2

    asin_response = client.post(
        "/research/new",
        data={"research_type": "asin", "name": "ASIN Route Run", "asin_text": "B0ABC11111"},
    )
    assert asin_response.status_code == 302
    assert fake_service.create_called is True
    assert fake_service.execute_called is True
    assert fake_service.executed_with == 1


def test_navigation_contains_link_to_research_new(client, db_schema):
    response = client.get("/")
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'href="/research/new"' in text
