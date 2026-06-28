"""Application logging configuration.

Provides a single ``configure_logging`` entry point that installs a console
handler and a rotating file handler under the application's log directory, with
independently configurable levels and an optional JSON formatter for machine
ingestion. All application modules obtain loggers via :func:`get_logger`, which
namespaces them under ``vibephoto`` so third-party library noise can be tuned
separately.

The configuration is idempotent: calling it twice replaces handlers rather than
stacking duplicates, which matters when tests or plugins reconfigure logging.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
from pathlib import Path
from typing import Any

from vibephoto.core.config import LoggingSettings
from vibephoto.core.paths import AppPaths

ROOT_LOGGER_NAME = "vibephoto"

_STANDARD_RECORD_KEYS = frozenset(
    logging.makeLogRecord({}).__dict__.keys()
    | {"message", "asctime", "taskName"}
)


class JsonFormatter(logging.Formatter):
    """Format records as single-line JSON for log aggregation pipelines.

    Any non-standard attribute attached to the record (via ``logger.info(..., extra=...)``)
    is included, so structured context flows through without bespoke formatters.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_KEYS and not key.startswith("_"):
                payload[key] = value
        return json.dumps(payload, default=str, ensure_ascii=False)


def _level(name: str) -> int:
    return logging.getLevelNamesMapping()[name]


def configure_logging(settings: LoggingSettings, paths: AppPaths) -> Path:
    """Configure the ``vibephoto`` logger tree. Returns the active log file.

    Console and file handlers have independent levels; the logger's own level is
    set to the most permissive of the two so records aren't dropped before
    reaching a handler.
    """
    paths.log_dir.mkdir(parents=True, exist_ok=True)
    log_file = paths.log_dir / "vibephoto.log"

    root = logging.getLogger(ROOT_LOGGER_NAME)
    # Most-permissive effective level so per-handler levels actually take effect.
    root.setLevel(min(_level(settings.console_level), _level(settings.file_level)))
    root.propagate = False

    # Idempotent: drop any handlers we previously installed.
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    if settings.json_logs:
        formatter: logging.Formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    console = logging.StreamHandler()
    console.setLevel(_level(settings.console_level))
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=settings.max_bytes,
        backupCount=settings.backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(_level(settings.file_level))
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    root.debug("Logging configured (console=%s, file=%s)", settings.console_level, log_file)
    return log_file


def get_logger(name: str) -> logging.Logger:
    """Return a logger namespaced under ``vibephoto``.

    Pass ``__name__``; the ``vibephoto.`` prefix is added if absent so the
    whole tree is controlled by the root configuration.
    """
    if name == "__main__" or not name.startswith(ROOT_LOGGER_NAME):
        name = f"{ROOT_LOGGER_NAME}.{name}"
    return logging.getLogger(name)
