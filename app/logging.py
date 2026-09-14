import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
        }

        standard_attrs = {
            "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
            "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
            "created", "msecs", "relativeCreated", "thread", "threadName",
            "processName", "process", "message", "asctime",
        }
        extras = {
            k: v for k, v in record.__dict__.items()
            if k not in standard_attrs and not k.startswith("_")
        }
        if extras:
            log_payload["data"] = extras

        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_payload, default=str, ensure_ascii=False)

class ColoredConsoleFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[41m",  # Red background
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        level_badge = f"{color}{record.levelname:<7}{self.RESET}"
        msg = record.getMessage()

        standard_attrs = {
            "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
            "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
            "created", "msecs", "relativeCreated", "thread", "threadName",
            "processName", "process", "message", "asctime",
        }
        extras = {
            k: v for k, v in record.__dict__.items()
            if k not in standard_attrs and not k.startswith("_")
        }
        extra_str = f" | {extras}" if extras else ""

        formatted = f"{timestamp} [{level_badge}] [{record.name}] {msg}{extra_str}"
        if record.exc_info:
            formatted += f"\n{self.formatException(record.exc_info)}"
        return formatted

def setup_logging(log_level: str | None = None, log_format: str | None = None) -> None:
    from app.config import get_settings
    settings = get_settings()

    level_name = (log_level or getattr(settings, "log_level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)

    fmt_mode = (log_format or getattr(settings, "log_format", "text" if settings.dev_mode else "json")).lower()

    handler = logging.StreamHandler(sys.stdout)
    if fmt_mode == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(ColoredConsoleFormatter())

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    while root_logger.handlers:
        root_logger.handlers.pop()

    root_logger.addHandler(handler)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi", "app"):
        l = logging.getLogger(logger_name)
        l.handlers = []
        l.propagate = True

    logging.getLogger("motor").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.INFO)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
