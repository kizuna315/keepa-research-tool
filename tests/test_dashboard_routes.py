from datetime import datetime, timedelta

import pytest

from app.extensions import db
from app.models import Product, ResearchRun
from app.services.keepa_client import (
    KeepaApiKeyMissingError,
    KeepaClientError,
    KeepaTokenError,
)


@pytest.fixture()
def db_schema(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        yield
        db.session.remove()
        db.drop_all()


def _create_product(*, asin, title, status, created_at=None, **kwargs):
    payload = {
        "asin": asin,
        "title": title,
        "status": status,
        "judgement": Product.JUDGEMENT_UNKNOWN,
        "created_at": created_at or datetime.utcnow(),
    }
    payload.update(kwargs)
    product = Product(**payload)
    db.session.add(product)
    return product


def _create_research_run(
    *, name, status, created_at, started_at=None, finished_at=None, **kwargs
):
    payload = {
        "name": name,
        "status": status,
        "created_at": created_at,
        "started_at": started_at,
        "finished_at": finished_at,
    }
    payload.update(kwargs)
    run = ResearchRun(**payload)
    db.session.add(run)
    return run


def _assert_metric(text, label, expected):
    assert label in text
    start = text.index(label)
    window = text[start : start + 300]
    assert f">{expected}<" in window or f" {expected}<" in window


def test_dashboard_get_root_returns_200(client, db_schema):
    response = client.get("/")
    assert response.status_code == 200


def test_dashboard_renders_with_zero_data(client, db_schema):
    text = client.get("/").get_data(as_text=True)

    _assert_metric(text, "総取得商品数", 0)
    _assert_metric(text, "候補商品数", 0)
    _assert_metric(text, "保留商品数", 0)
    _assert_metric(text, "除外商品数", 0)
    _assert_metric(text, "未確認商品数", 0)
    _assert_metric(text, "仕入れ先検索待ち商品数", 0)
    _assert_metric(text, "本日取得件数", 0)
    _assert_metric(text, "エラー件数", 0)
    assert "直近リサーチ名:" in text
    assert "直近リサーチステータス:" in text


def test_dashboard_displays_product_status_counts(client, app, db_schema):
    with app.app_context():
        now = datetime.utcnow()
        _create_product(
            asin="B0DSH00001",
            title="Candidate 1",
            status=Product.STATUS_CANDIDATE,
            created_at=now,
        )
        _create_product(
            asin="B0DSH00002",
            title="Candidate 2",
            status=Product.STATUS_CANDIDATE,
            created_at=now,
        )
        _create_product(
            asin="B0DSH00003",
            title="Hold 1",
            status=Product.STATUS_HOLD,
            created_at=now,
        )
        _create_product(
            asin="B0DSH00004",
            title="Excluded 1",
            status=Product.STATUS_EXCLUDED,
            created_at=now,
        )
        _create_product(
            asin="B0DSH00005",
            title="Unreviewed 1",
            status=Product.STATUS_UNREVIEWED,
            created_at=now,
        )
        _create_product(
            asin="B0DSH00006",
            title="Supplier Pending 1",
            status=Product.STATUS_SUPPLIER_SEARCH_PENDING,
            created_at=now,
        )
        db.session.commit()

    text = client.get("/").get_data(as_text=True)

    _assert_metric(text, "総取得商品数", 6)
    _assert_metric(text, "候補商品数", 2)
    _assert_metric(text, "保留商品数", 1)
    _assert_metric(text, "除外商品数", 1)
    _assert_metric(text, "未確認商品数", 1)
    _assert_metric(text, "仕入れ先検索待ち商品数", 1)


def test_dashboard_displays_latest_research_info_and_failed_count(client, app, db_schema):
    with app.app_context():
        now = datetime.utcnow()
        _create_research_run(
            name="Older Failed",
            status=ResearchRun.STATUS_FAILED,
            created_at=now - timedelta(hours=3),
            started_at=now - timedelta(hours=3),
            finished_at=now - timedelta(hours=2),
        )
        _create_research_run(
            name="Latest Completed",
            status=ResearchRun.STATUS_COMPLETED,
            created_at=now,
            started_at=now - timedelta(minutes=30),
            finished_at=now - timedelta(minutes=5),
        )
        _create_research_run(
            name="Another Failed",
            status=ResearchRun.STATUS_FAILED,
            created_at=now - timedelta(hours=1),
            started_at=now - timedelta(hours=1),
            finished_at=now - timedelta(minutes=45),
        )
        db.session.commit()

    text = client.get("/").get_data(as_text=True)

    assert "Latest Completed" in text
    assert "completed" in text
    _assert_metric(text, "エラー件数", 2)


def test_dashboard_displays_today_products_count(client, app, db_schema):
    with app.app_context():
        now = datetime.utcnow()
        yesterday = now - timedelta(days=1)
        _create_product(
            asin="B0TODAY001",
            title="Today 1",
            status=Product.STATUS_UNREVIEWED,
            created_at=now,
        )
        _create_product(
            asin="B0TODAY002",
            title="Today 2",
            status=Product.STATUS_UNREVIEWED,
            created_at=now - timedelta(hours=1),
        )
        _create_product(
            asin="B0TODAY003",
            title="Yesterday",
            status=Product.STATUS_UNREVIEWED,
            created_at=yesterday,
        )
        db.session.commit()

    text = client.get("/").get_data(as_text=True)
    _assert_metric(text, "本日取得件数", 2)


def test_dashboard_contains_navigation_links(client, db_schema):
    text = client.get("/").get_data(as_text=True)

    assert 'href="/research/new"' in text
    assert 'href="/products/"' in text
    assert 'href="/settings/"' in text


def test_dashboard_displays_keepa_token_status_on_success(client, db_schema, monkeypatch):
    monkeypatch.setattr(
        "app.routes.dashboard.KeepaClient.get_token_status",
        lambda self: {
            "tokens_left": 123,
            "refill_rate": 20,
            "refill_in": 30000,
            "token_flow_reduction": 0,
            "tokens_consumed": 5,
            "raw": {},
        },
    )

    text = client.get("/").get_data(as_text=True)
    assert "Keepa APIトークン" in text
    assert "available" in text
    assert "123" in text
    assert "20" in text
    assert "30秒" in text


def test_dashboard_displays_token_refill_time_in_minutes_seconds(
    client, db_schema, monkeypatch
):
    monkeypatch.setattr(
        "app.routes.dashboard.KeepaClient.get_token_status",
        lambda self: {
            "tokens_left": 12,
            "refill_rate": 20,
            "refill_in": None,
            "time_to_refill": 95,
            "raw": {},
        },
    )

    text = client.get("/").get_data(as_text=True)

    assert "1分35秒" in text
    assert "あと 95 秒" in text


def test_dashboard_displays_token_refill_seconds_when_less_than_minute(
    client, db_schema, monkeypatch
):
    monkeypatch.setattr(
        "app.routes.dashboard.KeepaClient.get_token_status",
        lambda self: {
            "tokens_left": 8,
            "refill_rate": 20,
            "refill_in": None,
            "time_to_refill": 45,
            "raw": {},
        },
    )

    text = client.get("/").get_data(as_text=True)

    assert "45秒" in text


def test_dashboard_displays_keyword_limit_recommendation(client, db_schema, monkeypatch):
    monkeypatch.setattr(
        "app.routes.dashboard.KeepaClient.get_token_status",
        lambda self, allow_depleted=False: {
            "tokens_left": 8,
            "refill_rate": 1,
            "refill_in": 45000,
            "raw": {},
        },
    )

    text = client.get("/").get_data(as_text=True)

    assert "キーワード検索の目安" in text
    assert "キーワード検索は1件までが目安です。" in text


def test_dashboard_displays_keyword_limit_recommendation_when_tokens_sufficient(
    client, db_schema, monkeypatch
):
    monkeypatch.setattr(
        "app.routes.dashboard.KeepaClient.get_token_status",
        lambda self, allow_depleted=False: {
            "tokens_left": 40,
            "refill_rate": 1,
            "refill_in": 45000,
            "raw": {},
        },
    )

    text = client.get("/").get_data(as_text=True)

    assert "キーワード検索は5件程度までが目安です。" in text
    assert "あと 45 秒" in text


def test_dashboard_handles_unknown_token_refill_time(client, db_schema, monkeypatch):
    monkeypatch.setattr(
        "app.routes.dashboard.KeepaClient.get_token_status",
        lambda self: {
            "tokens_left": 8,
            "refill_rate": 20,
            "refill_in": None,
            "raw": {},
        },
    )

    text = client.get("/").get_data(as_text=True)

    assert "不明" in text


def test_dashboard_token_status_does_not_leak_api_key(client, db_schema, monkeypatch):
    monkeypatch.setattr(
        "app.routes.dashboard.KeepaClient.get_token_status",
        lambda self: (_ for _ in ()).throw(
            KeepaClientError("failed key=SECRET_KEEPA_KEY_123")
        ),
    )

    text = client.get("/").get_data(as_text=True)

    assert "Keepa APIトークン情報を取得できませんでした。" in text
    assert "SECRET_KEEPA_KEY_123" not in text
    assert "key=" not in text


def test_dashboard_handles_missing_keepa_api_key_safely(client, db_schema, monkeypatch):
    monkeypatch.setattr(
        "app.routes.dashboard.KeepaClient.get_token_status",
        lambda self: (_ for _ in ()).throw(KeepaApiKeyMissingError("missing key")),
    )

    response = client.get("/")
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Keepa API Keyが未設定です。" in text
    assert 'href="/settings/"' in text


def test_dashboard_handles_keepa_token_error_safely(client, db_schema, monkeypatch):
    monkeypatch.setattr(
        "app.routes.dashboard.KeepaClient.get_token_status",
        lambda self: (_ for _ in ()).throw(KeepaTokenError("depleted")),
    )

    response = client.get("/")
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Keepa APIトークンが不足しています。" in text
    assert "unavailable" in text


def test_dashboard_displays_depleted_token_refill_wait_time(
    client, db_schema, monkeypatch
):
    monkeypatch.setattr(
        "app.routes.dashboard.KeepaClient.get_token_status",
        lambda self, allow_depleted=False: {
            "tokens_left": 0,
            "refill_rate": 20,
            "refill_in": 95000,
            "raw": {},
        },
    )

    response = client.get("/")
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "depleted" in text
    assert "Keepa APIトークンが不足しています。" in text
    _assert_metric(text, "現在使えるトークン", 0)
    assert "1分35秒" in text
    assert "あと 95 秒" in text


def test_dashboard_handles_keepa_client_error_safely(client, db_schema, monkeypatch):
    monkeypatch.setattr(
        "app.routes.dashboard.KeepaClient.get_token_status",
        lambda self: (_ for _ in ()).throw(KeepaClientError("network failed")),
    )

    response = client.get("/")
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Keepa APIトークン情報を取得できませんでした。" in text


def test_dashboard_does_not_show_sensitive_message_from_token_exception(
    client, db_schema, monkeypatch
):
    monkeypatch.setattr(
        "app.routes.dashboard.KeepaClient.get_token_status",
        lambda self: (_ for _ in ()).throw(Exception("apiKey=SECRET-12345")),
    )

    response = client.get("/")
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Keepa APIトークン情報を取得できませんでした。" in text
    assert "SECRET-12345" not in text
    assert "apiKey=" not in text


def test_dashboard_recent_research_runs_shows_max_five(client, app, db_schema):
    with app.app_context():
        now = datetime.utcnow()
        for index in range(6):
            _create_research_run(
                name=f"Run {index}",
                status=ResearchRun.STATUS_COMPLETED,
                created_at=now - timedelta(minutes=index),
            )
        db.session.commit()

    text = client.get("/").get_data(as_text=True)
    assert text.count('data-testid="recent-research-row"') == 5
    assert "Run 0" in text
    assert "Run 4" in text
    assert "Run 5" not in text


def test_dashboard_recent_research_runs_empty_state(client, db_schema):
    text = client.get("/").get_data(as_text=True)
    assert "まだリサーチ履歴はありません。" in text


def test_dashboard_recent_research_runs_shows_status_and_error_message(client, app, db_schema):
    with app.app_context():
        now = datetime.utcnow()
        _create_research_run(
            name="Completed Run",
            status=ResearchRun.STATUS_COMPLETED,
            created_at=now,
            total_requested=10,
            total_fetched=8,
            total_saved=7,
        )
        _create_research_run(
            name="Failed Run",
            status=ResearchRun.STATUS_FAILED,
            created_at=now - timedelta(minutes=1),
            total_requested=10,
            total_fetched=0,
            total_saved=0,
            error_message="failed message",
        )
        db.session.commit()

    text = client.get("/").get_data(as_text=True)
    assert "Completed Run" in text
    assert "Failed Run" in text
    assert "completed" in text
    assert "failed" in text
    assert "failed message" in text


def test_dashboard_recent_research_started_at_displays_jst(client, app, db_schema):
    with app.app_context():
        _create_research_run(
            name="JST Started Run",
            status=ResearchRun.STATUS_COMPLETED,
            created_at=datetime(2026, 6, 4, 0, 0, 0),
            started_at=datetime(2026, 6, 4, 0, 30, 0),
            finished_at=datetime(2026, 6, 4, 1, 0, 0),
        )
        db.session.commit()

    text = client.get("/").get_data(as_text=True)

    assert "開始日時（JST）" in text
    assert "2026-06-04 09:30" in text
    assert "2026-06-04 10:00" in text
    assert "2026-06-04 00:30" not in text


def test_dashboard_recent_research_started_at_handles_none(client, app, db_schema):
    with app.app_context():
        _create_research_run(
            name="Pending JST Run",
            status=ResearchRun.STATUS_PENDING,
            created_at=datetime(2026, 6, 4, 0, 0, 0),
            started_at=None,
            finished_at=None,
        )
        db.session.commit()

    response = client.get("/")
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Pending JST Run" in text
    assert "開始日時（JST）" in text
    assert ">-<" in text or ">\n                  -\n                <" in text


def test_dashboard_recent_products_shows_max_five(client, app, db_schema):
    with app.app_context():
        now = datetime.utcnow()
        for index in range(6):
            _create_product(
                asin=f"B0RCP{index:05d}",
                title=f"Recent Product {index}",
                status=Product.STATUS_UNREVIEWED,
                keepa_score=50 + index,
                last_checked_at=now - timedelta(minutes=index),
            )
        db.session.commit()

    text = client.get("/").get_data(as_text=True)
    assert text.count('data-testid="recent-product-row"') == 5
    assert "Recent Product 0" in text
    assert "Recent Product 4" in text
    assert "Recent Product 5" not in text


def test_dashboard_recent_products_empty_state(client, db_schema):
    text = client.get("/").get_data(as_text=True)
    assert "まだ取得商品はありません。" in text


def test_dashboard_recent_products_shows_fields_and_detail_link(client, app, db_schema):
    with app.app_context():
        product = _create_product(
            asin="B0RECENT01",
            title="Recent Target Product",
            status=Product.STATUS_CANDIDATE,
            brand="Recent Brand",
            keepa_score=88,
            judgement=Product.JUDGEMENT_GOOD,
            last_checked_at=datetime.utcnow(),
        )
        db.session.commit()
        product_id = product.id

    text = client.get("/").get_data(as_text=True)
    assert "Recent Target Product" in text
    assert "B0RECENT01" in text
    assert "88" in text
    assert Product.JUDGEMENT_GOOD in text
    assert Product.STATUS_CANDIDATE in text
    assert f'href="/products/{product_id}"' in text


def test_dashboard_contains_candidate_and_excluded_quick_links(client, db_schema):
    text = client.get("/").get_data(as_text=True)
    assert 'href="/products/?status=candidate"' in text
    assert 'href="/products/?status=excluded"' in text


def test_phase8_acceptance_dashboard_summary_token_recent_runs_and_products(
    client, app, db_schema, monkeypatch
):
    monkeypatch.setattr(
        "app.routes.dashboard.KeepaClient.get_token_status",
        lambda self: {
            "tokens_left": 222,
            "refill_rate": 20,
            "refill_in": 30000,
            "token_flow_reduction": 0,
            "tokens_consumed": 1,
            "raw": {},
        },
    )

    with app.app_context():
        now = datetime.utcnow()

        p1 = _create_product(
            asin="B0P8ACC001",
            title="Phase8 Product Candidate",
            status=Product.STATUS_CANDIDATE,
            judgement=Product.JUDGEMENT_GOOD,
            keepa_score=88,
            last_checked_at=now,
            created_at=now,
        )
        _create_product(
            asin="B0P8ACC002",
            title="Phase8 Product Hold",
            status=Product.STATUS_HOLD,
            judgement=Product.JUDGEMENT_WATCH,
            keepa_score=70,
            last_checked_at=now - timedelta(minutes=1),
            created_at=now - timedelta(minutes=1),
        )
        _create_product(
            asin="B0P8ACC003",
            title="Phase8 Product Excluded",
            status=Product.STATUS_EXCLUDED,
            judgement=Product.JUDGEMENT_BAD,
            keepa_score=40,
            last_checked_at=now - timedelta(minutes=2),
            created_at=now - timedelta(minutes=2),
        )

        _create_research_run(
            name="Phase8 Latest Run",
            status=ResearchRun.STATUS_COMPLETED,
            created_at=now,
            started_at=now - timedelta(minutes=20),
            finished_at=now - timedelta(minutes=5),
            total_requested=3,
            total_fetched=3,
            total_saved=3,
        )
        _create_research_run(
            name="Phase8 Failed Run",
            status=ResearchRun.STATUS_FAILED,
            created_at=now - timedelta(minutes=10),
            started_at=now - timedelta(minutes=15),
            finished_at=now - timedelta(minutes=12),
            total_requested=2,
            total_fetched=0,
            total_saved=0,
            error_message="phase8 failed",
        )
        db.session.commit()
        first_product_id = p1.id

    response = client.get("/")
    text = response.get_data(as_text=True)

    assert response.status_code == 200

    _assert_metric(text, "総取得商品数", 3)
    _assert_metric(text, "候補商品数", 1)
    _assert_metric(text, "保留商品数", 1)
    _assert_metric(text, "除外商品数", 1)
    _assert_metric(text, "エラー件数", 1)
    assert "Phase8 Latest Run" in text
    assert "completed" in text
    assert "222" in text
    assert "30秒" in text
    assert 'data-testid="recent-research-row"' in text
    assert 'data-testid="recent-product-row"' in text
    assert "Phase8 Product Candidate" in text
    assert f'href="/products/{first_product_id}"' in text
    assert 'href="/products/?status=candidate"' in text
    assert 'href="/products/?status=excluded"' in text
