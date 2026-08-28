"""Structured JSON logging with secret and taint redaction.

Two non-obvious requirements drive this module.

1. ARCHITECTURE §14: credentials are "never logged". A ``SecretStr`` renders as
   ``**********`` under ``str()``, but the moment someone logs a dict built
   from ``model_dump()`` the real value can escape. So redaction happens in the
   formatter, on the way out, by key name — the last point where we still
   control the bytes.

2. CONSTITUTION P6: retrieved content is hostile. Hostile content in a log line
   is a log-injection vector (forged records via embedded newlines) and, worse,
   a path into a model context if logs are ever summarised. Control characters
   and newlines in string values are escaped here rather than trusted.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any, Final

# Key names whose values must never appear in a log record. Matched
# case-insensitively as substrings, so SESSION_SECRET, s3_secret_key,
# google_oauth_client_secret and refresh_token are all covered by design.
_REDACT_KEY_PATTERNS = (
    "secret",
    "password",
    "passwd",
    "token",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
    "kek",
    "authorization",
    "cookie",
    "session",
    "credential",
)

_REDACTED = "[REDACTED]"

# Recursion and size caps. Logging must never itself become the outage, so a
# hostile or cyclic structure is truncated rather than followed.
_MAX_SCRUB_DEPTH: Final = 6
_MAX_STRING_CHARS: Final = 4096
_MAX_SEQUENCE_ITEMS: Final = 100

# Control characters other than tab. Newlines included deliberately: a newline
# inside a logged field is how a hostile page forges a second log record.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

_RESERVED = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)


def _should_redact(key: str) -> bool:
    lowered = key.lower()
    return any(p in lowered for p in _REDACT_KEY_PATTERNS)


def _scrub(value: Any, key: str = "", depth: int = 0) -> Any:  # noqa: PLR0911
    """Recursively redact secret-shaped keys and neutralise control chars.

    PLR0911 (many returns) is accepted: this is a type dispatch, and each
    branch returns a differently-shaped result. Collapsing it into one exit
    would need an accumulator variable and would be harder to audit — and this
    function is a security control, so auditability wins.

    ``depth`` is capped because a hostile or buggy structure could otherwise
    make logging itself the outage.
    """
    if depth > _MAX_SCRUB_DEPTH:
        return "[TRUNCATED:depth]"
    if key and _should_redact(key):
        return _REDACTED
    if isinstance(value, str):
        cleaned = _CONTROL_CHARS.sub("\ufffd", value).replace("\n", "\\n").replace("\r", "\\r")
        if len(cleaned) <= _MAX_STRING_CHARS:
            return cleaned
        return cleaned[:_MAX_STRING_CHARS] + "…[TRUNCATED]"
    if isinstance(value, dict):
        return {k: _scrub(v, str(k), depth + 1) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_scrub(v, key, depth + 1) for v in value[:_MAX_SEQUENCE_ITEMS]]
    if isinstance(value, int | float | bool) or value is None:
        return value
    # Unknown object: stringify, then scrub as a string. Notably this catches
    # SecretStr, whose __str__ is already masked.
    return _scrub(repr(value), key, depth + 1)


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per line, vendor-neutral (ARCHITECTURE §4)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": _scrub(record.getMessage()),
        }

        # OpenTelemetry correlation, when a span is active. Imported lazily so
        # that neptiq_core carries no hard OTEL dependency — P10 again.
        #
        # Failure here is suppressed on purpose. This block only *enriches* a
        # record with trace ids. If OpenTelemetry is absent, being torn down, or
        # throwing, the right outcome is a log line without correlation ids —
        # not a lost log line, and never an exception raised from inside a
        # logging handler, which would mask the error being reported.
        with contextlib.suppress(Exception):  # pragma: no cover - optional dep
            from opentelemetry import trace

            span = trace.get_current_span()
            ctx = span.get_span_context()
            if ctx.is_valid:
                payload["trace_id"] = format(ctx.trace_id, "032x")
                payload["span_id"] = format(ctx.span_id, "016x")

        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = _scrub(value, key)

        if record.exc_info:
            payload["exc"] = _scrub(self.formatException(record.exc_info))

        return json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))


def configure_logging(level: str = "INFO", *, stream: Any = None) -> None:
    """Install the JSON formatter as the sole root handler.

    Replaces existing handlers rather than adding to them: duplicated handlers
    are the usual cause of a "redacted" line also appearing unredacted from a
    library-installed handler.
    """
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
