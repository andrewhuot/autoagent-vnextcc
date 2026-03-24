"""Structured JSON logging configuration with rotating file handlers."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path


class JsonFormatter(logging.Formatter):
    """Render log records as one JSON document per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for extra_key in (
            "event",
            "cycle",
            "run_id",
            "status",
            "provider",
            "model",
            "memory_mb",
            "cpu_percent",
        ):
            if hasattr(record, extra_key):
                payload[extra_key] = getattr(record, extra_key)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload)


def configure_structured_logging(
    *,
    log_path: str,
    logger_name: str = "autoagent",
    level: int = logging.INFO,
    max_bytes: int = 5_000_000,
    backup_count: int = 5,
) -> logging.Logger:
    """Configure and return a rotating structured logger."""
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    logger.propagate = False

    if not any(isinstance(handler, RotatingFileHandler) and handler.baseFilename == str(path) for handler in logger.handlers):
        handler = RotatingFileHandler(
            filename=str(path),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)

    return logger
