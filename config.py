import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
EXPORT_DIR = BASE_DIR / "exports"

load_dotenv(BASE_DIR / ".env")


def ensure_directories() -> None:
    for path in (DATA_DIR, LOG_DIR, EXPORT_DIR):
        path.mkdir(parents=True, exist_ok=True)


def _resolve_database_uri() -> str:
    raw_uri = os.getenv("DATABASE_URL", "sqlite:///data/app.db")
    sqlite_prefix = "sqlite:///"
    sqlite_abs_prefix = "sqlite:////"

    if raw_uri.startswith(sqlite_abs_prefix):
        return raw_uri

    if raw_uri.startswith(sqlite_prefix):
        relative_path = raw_uri[len(sqlite_prefix):]
        absolute_path = (BASE_DIR / relative_path).resolve()
        return f"sqlite:///{absolute_path.as_posix()}"

    return raw_uri


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    SQLALCHEMY_DATABASE_URI = _resolve_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
