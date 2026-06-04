from datetime import timedelta, timezone

from flask import Flask

from config import BASE_DIR, Config, ensure_directories
from dotenv import load_dotenv

from app.extensions import db, migrate
from app.logging_config import configure_logging
from app.routes import register_blueprints

JST = timezone(timedelta(hours=9), name="JST")


def datetime_jst(value, fmt="%Y-%m-%d %H:%M"):
    if not value:
        return "-"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(JST).strftime(fmt)


def create_app(config_class=Config) -> Flask:
    load_dotenv(BASE_DIR / ".env")
    ensure_directories()

    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)

    with app.app_context():
        from app import models  # noqa: F401

    register_blueprints(app)
    app.jinja_env.filters["datetime_jst"] = datetime_jst
    configure_logging(app)
    app.logger.info("Keepa Research Tool app initialized")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app
