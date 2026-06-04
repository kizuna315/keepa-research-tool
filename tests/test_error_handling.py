import csv
from pathlib import Path

import pytest

from app.extensions import db
from app.models import Product, ResearchRun
from app.services.csv_exporter import CsvExporter, CsvExporterError
from app.services.error_utils import build_user_friendly_error_message, log_safe
from app.services.keepa_client import (
    KeepaApiError,
    KeepaApiKeyMissingError,
    KeepaClient,
    KeepaTokenError,
)
from app.services.research_service import ResearchService, ResearchServiceError
from app.services.scoring_service import ScoringService


SECRET_API_KEY = "SECRET_KEEPA_KEY_123"
SECRET_TOKEN = "SECRET_TOKEN_456"
SECRET_BEARER = f"Bearer {SECRET_TOKEN}"
SECRET_PATTERNS = [
    SECRET_API_KEY,
    SECRET_TOKEN,
    SECRET_BEARER,
    f"apiKey={SECRET_API_KEY}",
    f"key={SECRET_API_KEY}",
]


@pytest.fixture()
def db_schema(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        yield
        db.session.remove()
        db.drop_all()


def _assert_no_secret(text):
    text = text or ""
    for secret in SECRET_PATTERNS:
        assert secret not in text
    assert "Traceback (most recent call last)" not in text


def _create_run(conditions=None):
    conditions = conditions or '{"type": "asin", "asins": ["B0SAFE0001"]}'
    run = ResearchRun(
        name="Safe Error Handling Run",
        status=ResearchRun.STATUS_PENDING,
        conditions_json=conditions,
        total_requested=1,
    )
    db.session.add(run)
    db.session.commit()
    return run


def test_missing_api_key_flow_returns_safe_message():
    client = KeepaClient(settings_service=type("Settings", (), {"get": staticmethod(lambda key: None)}))

    with pytest.raises(KeepaApiKeyMissingError) as exc_info:
        client.get_token_status()

    message = str(exc_info.value)
    assert exc_info.value.error_type == "missing_api_key"
    assert "Keepa API Key" in message
    _assert_no_secret(message)


def test_invalid_api_key_flow_does_not_leak_secret(app, caplog):
    with app.app_context():
        with pytest.raises(KeepaApiError) as exc_info:
            with caplog.at_level("ERROR"):
                KeepaClient._raise_for_api_errors(
                    {
                        "error": (
                            f"invalid apiKey={SECRET_API_KEY} "
                            f"Authorization: {SECRET_BEARER}"
                        )
                    },
                    path="/token",
                    params={"key": SECRET_API_KEY},
                )

    assert exc_info.value.error_type == "invalid_api_key"
    _assert_no_secret(str(exc_info.value))
    _assert_no_secret(caplog.text)
    assert "[REDACTED]" in caplog.text


class _FailingAsinKeepaClient:
    def __init__(self, error):
        self.error = error

    def get_products_by_asins(self, asins):
        raise self.error


def test_token_insufficient_flow_marks_research_failed_safely(app, db_schema):
    with app.app_context():
        run = _create_run()
        service = ResearchService(
            keepa_client=_FailingAsinKeepaClient(
                KeepaTokenError(
                    f"tokensLeft=0 key={SECRET_API_KEY}",
                    error_type="token_insufficient",
                )
            )
        )

        with pytest.raises(ResearchServiceError):
            service.execute_asin_research(run.id)

        failed = db.session.get(ResearchRun, run.id)

    assert failed.status == ResearchRun.STATUS_FAILED
    assert failed.finished_at is not None
    assert "Keepa API" in failed.error_message
    _assert_no_secret(failed.error_message)


def test_keepa_connection_failed_flow_marks_research_failed_safely(app, db_schema, caplog):
    with app.app_context():
        run = _create_run()
        service = ResearchService(
            keepa_client=_FailingAsinKeepaClient(
                KeepaApiError(
                    f"connection failed apiKey={SECRET_API_KEY} token={SECRET_TOKEN}",
                    error_type="keepa_connection_failed",
                )
            )
        )

        with pytest.raises(ResearchServiceError):
            with caplog.at_level("ERROR"):
                service.execute_asin_research(run.id)

        failed = db.session.get(ResearchRun, run.id)

    assert failed.status == ResearchRun.STATUS_FAILED
    assert failed.finished_at is not None
    _assert_no_secret(failed.error_message)
    _assert_no_secret(caplog.text)
    assert "[REDACTED]" in caplog.text


def test_db_save_failed_flow_does_not_leave_running_research_run(app, db_schema):
    with app.app_context():
        run = _create_run()
        service = ResearchService()
        service.mark_running(run)

        failing_error = ResearchServiceError(
            f"db failed apiKey={SECRET_API_KEY}",
            error_type="db_save_failed",
        )
        service.fail_research_run(run, failing_error)

        failed = db.session.get(ResearchRun, run.id)

    assert failed.status == ResearchRun.STATUS_FAILED
    assert failed.status != ResearchRun.STATUS_RUNNING
    assert failed.finished_at is not None
    _assert_no_secret(failed.error_message)


def test_csv_export_failed_flow_flashes_safe_message(client, db_schema, monkeypatch):
    class FailingExporter:
        def export_products(self, products):
            raise CsvExporterError(f"write failed key={SECRET_API_KEY}")

        def export_candidates(self):
            raise CsvExporterError(f"write failed key={SECRET_API_KEY}")

    monkeypatch.setattr("app.routes.products.CsvExporter", lambda: FailingExporter())

    response = client.get("/products/export?target=all", follow_redirects=True)
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert build_user_friendly_error_message("csv_export_failed") in text
    _assert_no_secret(text)


def test_data_insufficient_product_is_unknown_hold():
    product = Product(asin="B0SAFE0002", title="Incomplete Product")

    ScoringService().apply_scoring(product)

    assert product.judgement == Product.JUDGEMENT_UNKNOWN
    assert product.status == Product.STATUS_HOLD


def test_flash_messages_do_not_render_raw_traceback(client, db_schema, monkeypatch):
    class FailingResearchService:
        def create_research_run_for_asins(self, name, asin_text):
            raise ResearchServiceError(
                f"Traceback (most recent call last) key={SECRET_API_KEY}"
            )

    monkeypatch.setattr("app.routes.research.ResearchService", FailingResearchService)

    response = client.post(
        "/research/new",
        data={
            "research_type": "asin",
            "name": "flash safety",
            "asin_text": "B0SAFE0003",
        },
    )
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "ASINリサーチに失敗しました。" in text
    _assert_no_secret(text)


def test_logs_do_not_include_api_key_or_token(app, caplog):
    with app.app_context():
        with caplog.at_level("ERROR"):
            log_safe(
                app.logger,
                "error",
                f"operation failed key={SECRET_API_KEY}",
                authorization=SECRET_BEARER,
                detail=f"token={SECRET_TOKEN}",
            )

    _assert_no_secret(caplog.text)
    assert "[REDACTED]" in caplog.text


def test_error_message_does_not_include_api_key_or_token(app, db_schema):
    with app.app_context():
        run = _create_run()
        service = ResearchService()
        service.fail_research_run(
            run,
            ResearchServiceError(
                f"failed apiKey={SECRET_API_KEY} Authorization: {SECRET_BEARER}",
                error_type="keepa_api_failed",
            ),
        )
        failed = db.session.get(ResearchRun, run.id)

    assert failed.status == ResearchRun.STATUS_FAILED
    _assert_no_secret(failed.error_message)


def test_csv_body_does_not_include_api_key_or_token(app, db_schema, isolated_dirs):
    with app.app_context():
        product = Product(
            asin="B0SAFE0004",
            title="CSV Secret Safety",
            status=Product.STATUS_CANDIDATE,
            memo=f"memo key={SECRET_API_KEY} Authorization: {SECRET_BEARER}",
        )
        db.session.add(product)
        db.session.commit()

        filepath = CsvExporter(export_dir=str(isolated_dirs["exports"])).export_products(
            [product]
        )

    csv_text = Path(filepath).read_text(encoding="utf-8-sig")
    rows = list(csv.reader(csv_text.splitlines()))

    assert rows
    _assert_no_secret(csv_text)
    assert "[REDACTED]" in csv_text
    assert "raw_keepa_json" not in rows[0]
