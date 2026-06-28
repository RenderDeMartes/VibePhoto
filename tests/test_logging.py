"""Tests for logging configuration."""

from __future__ import annotations

import json
import logging

from vibephoto.core.config import LoggingSettings
from vibephoto.core.logging import (
    ROOT_LOGGER_NAME,
    JsonFormatter,
    configure_logging,
    get_logger,
)
from vibephoto.core.paths import AppPaths


def test_configure_creates_log_file(app_paths: AppPaths) -> None:
    log_file = configure_logging(LoggingSettings(), app_paths)
    assert log_file.exists()
    logging.getLogger(ROOT_LOGGER_NAME).info("hello")
    for h in logging.getLogger(ROOT_LOGGER_NAME).handlers:
        h.flush()
    assert "hello" in log_file.read_text(encoding="utf-8")


def test_configure_is_idempotent(app_paths: AppPaths) -> None:
    configure_logging(LoggingSettings(), app_paths)
    configure_logging(LoggingSettings(), app_paths)
    handlers = logging.getLogger(ROOT_LOGGER_NAME).handlers
    # Exactly one console + one file handler, not stacked duplicates.
    assert len(handlers) == 2


def test_get_logger_namespaces_under_root() -> None:
    assert get_logger("catalog.indexer").name == f"{ROOT_LOGGER_NAME}.catalog.indexer"
    assert get_logger("__main__").name == f"{ROOT_LOGGER_NAME}.__main__"
    # Already-namespaced names are left alone.
    assert get_logger(f"{ROOT_LOGGER_NAME}.x").name == f"{ROOT_LOGGER_NAME}.x"


def test_json_formatter_emits_valid_json() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="vibephoto.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="merge %s",
        args=("done",),
        exc_info=None,
    )
    record.photo_id = 99  # structured extra
    payload = json.loads(formatter.format(record))
    assert payload["message"] == "merge done"
    assert payload["level"] == "INFO"
    assert payload["photo_id"] == 99


def test_file_level_can_differ_from_console(app_paths: AppPaths) -> None:
    settings = LoggingSettings(console_level="ERROR", file_level="DEBUG")
    log_file = configure_logging(settings, app_paths)
    logging.getLogger(ROOT_LOGGER_NAME).debug("debug-line")
    for h in logging.getLogger(ROOT_LOGGER_NAME).handlers:
        h.flush()
    # DEBUG reaches the file even though console is ERROR-only.
    assert "debug-line" in log_file.read_text(encoding="utf-8")
