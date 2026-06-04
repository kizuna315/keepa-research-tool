from pathlib import Path

import pytest

from app.extensions import db


@pytest.fixture()
def db_schema(app):
    with app.app_context():
        db.drop_all()
        db.create_all()
        yield
        db.session.remove()
        db.drop_all()


def test_mvp_health_endpoint_loads(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_mvp_core_pages_load(client, db_schema):
    paths = [
        "/",
        "/settings/",
        "/research/new",
        "/products/",
    ]

    for path in paths:
        response = client.get(path)
        text = response.get_data(as_text=True)

        assert response.status_code == 200
        assert "Traceback (most recent call last)" not in text
        assert "Keepa Research Tool" in text


def test_mvp_required_directories_are_created(isolated_dirs, app):
    assert isolated_dirs["data"].exists()
    assert isolated_dirs["exports"].exists()
    assert isolated_dirs["logs"].exists()

    log_file = isolated_dirs["logs"] / "app.log"
    app.logger.info("mvp smoke startup log")
    for handler in app.logger.handlers:
        if hasattr(handler, "flush"):
            handler.flush()

    assert log_file.exists()
    assert "Keepa Research Tool app initialized" in log_file.read_text(encoding="utf-8")


def test_mvp_no_out_of_scope_routes_exist(app):
    blocked_paths = {
        "/suppliers",
        "/profit",
        "/amazon-seller",
        "/pricetar",
        "/monitoring",
        "/notifications",
        "/login",
    }
    registered_rules = {rule.rule for rule in app.url_map.iter_rules()}

    for path in blocked_paths:
        assert path not in registered_rules


def test_mvp_readme_env_and_requirements_are_consistent():
    readme = Path("README.md").read_text(encoding="utf-8")
    env_example = Path(".env.example").read_text(encoding="utf-8")
    requirements = Path("requirements.txt").read_text(encoding="utf-8")

    assert "python -m venv .venv" in readme
    assert "pip install -r requirements.txt" in readme
    assert "copy .env.example .env" in readme
    assert "flask --app run.py db upgrade" in readme
    assert "python run.py" in readme
    assert "http://127.0.0.1:5000" in readme
    assert "Keepa API Keyは `.env` ではなく" in readme

    assert "FLASK_APP=run.py" in env_example
    assert "DATABASE_URL=sqlite:///data/app.db" in env_example
    assert "KEEPA_API_KEY=" not in env_example

    for package_name in (
        "Flask",
        "Flask-SQLAlchemy",
        "Flask-Migrate",
        "python-dotenv",
        "requests",
        "pytest",
    ):
        assert package_name in requirements


def test_mvp_docs_do_not_include_secret_like_samples():
    docs_text = "\n".join(
        [
            Path("README.md").read_text(encoding="utf-8"),
            Path(".env.example").read_text(encoding="utf-8"),
        ]
    )
    forbidden_samples = [
        "SECRET_KEEPA_KEY_123",
        "SECRET_TOKEN_456",
        "Bearer SECRET",
        "apiKey=SECRET",
        "key=SECRET",
    ]

    for sample in forbidden_samples:
        assert sample not in docs_text
