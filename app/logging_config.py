import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import config


def configure_logging(app) -> None:
    log_file = config.LOG_DIR / "app.log"
    resolved_log_file = Path(log_file).resolve()

    for handler in app.logger.handlers:
        if isinstance(handler, RotatingFileHandler):
            if Path(handler.baseFilename).resolve() == resolved_log_file:
                return

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )

    app.logger.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)
