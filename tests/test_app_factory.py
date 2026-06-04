from logging.handlers import RotatingFileHandler
from pathlib import Path

import config
from flask import Flask

from app import create_app


def test_create_app_returns_flask_instance(app):
    assert isinstance(app, Flask)


def test_directories_created_on_app_init(isolated_dirs, app):
    assert isolated_dirs["data"].exists()
    assert isolated_dirs["exports"].exists()
    assert isolated_dirs["logs"].exists()


def test_dashboard_endpoint_returns_html(client):
    response = client.get("/")

    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "Keepa Research Tool" in text
    assert "総取得商品数" in text


def test_health_endpoint_returns_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_logging_writes_to_app_log(isolated_dirs, app):
    log_file = isolated_dirs["logs"] / "app.log"

    app.logger.info("test info log")
    for handler in app.logger.handlers:
        if hasattr(handler, "flush"):
            handler.flush()

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "Keepa Research Tool app initialized" in content
    assert "test info log" in content


def test_rotating_file_handler_is_not_duplicated(isolated_dirs):
    create_app()
    app_two = create_app()

    log_path = (isolated_dirs["logs"] / "app.log").resolve()
    rotating_handlers = [
        handler
        for handler in app_two.logger.handlers
        if isinstance(handler, RotatingFileHandler)
        and handler.baseFilename
        and Path(handler.baseFilename).resolve() == log_path
    ]

    assert len(rotating_handlers) == 1
