import logging
import shutil
import uuid
from logging.handlers import RotatingFileHandler

import pytest

import config
from app import create_app


class TestConfig:
    TESTING = True
    SECRET_KEY = "test-secret-key"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False


@pytest.fixture()
def isolated_dirs(monkeypatch):
    root_dir = config.BASE_DIR / "tests_runtime" / uuid.uuid4().hex
    data_dir = root_dir / "data"
    export_dir = root_dir / "exports"
    log_dir = root_dir / "logs"

    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "EXPORT_DIR", export_dir)
    monkeypatch.setattr(config, "LOG_DIR", log_dir)

    yield {
        "root": root_dir,
        "data": data_dir,
        "exports": export_dir,
        "logs": log_dir,
    }

    logger = logging.getLogger("app")
    for handler in list(logger.handlers):
        if isinstance(handler, RotatingFileHandler):
            base_filename = getattr(handler, "baseFilename", "")
            if base_filename and str(root_dir) in base_filename:
                logger.removeHandler(handler)
                handler.close()

    shutil.rmtree(root_dir, ignore_errors=True)


@pytest.fixture()
def app(isolated_dirs):
    app = create_app(TestConfig)
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()
