"""Request checks for POST /v1/records."""

import json
import re
from datetime import datetime

from recordstore.errors import AppError

BODY_MAX_BYTES = 64 * 1024
PAYLOAD_MAX_BYTES = 16 * 1024

KIND_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
CREATED_AT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$"
)

REGISTERED_KINDS = (
    {"kind": "note", "payload": "optional"},
    {"kind": "idea", "payload": "optional"},
    {"kind": "news", "payload": "optional"},
    {"kind": "trade", "payload": "optional"},
)
REGISTERED_KIND_NAMES = {item["kind"] for item in REGISTERED_KINDS}


def dump_payload(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def validate_new_record(obj: dict) -> dict:
    source = _required_text(obj, "source")
    kind = _required_text(obj, "kind")
    if KIND_RE.fullmatch(kind) is None:
        raise AppError(400, "validation_error", "kind is invalid")

    if "body" not in obj or not isinstance(obj["body"], str):
        raise AppError(400, "validation_error", "body is required")
    body = obj["body"].strip()
    if body == "":
        raise AppError(400, "validation_error", "body is required")
    if len(body.encode("utf-8")) > BODY_MAX_BYTES:
        raise AppError(413, "payload_too_large", "body exceeds 64 KiB")

    payload_text = _payload_text(kind, obj)
    created_at = _created_at(obj.get("created_at")) if "created_at" in obj else None
    client_key = _client_key(obj)

    return {
        "source": source,
        "kind": kind,
        "body": body,
        "payload_text": payload_text,
        "created_at": created_at,
        "client_key": client_key,
    }


def _required_text(obj: dict, name: str) -> str:
    value = obj.get(name)
    if not isinstance(value, str):
        raise AppError(400, "validation_error", f"{name} is required")
    text = value.strip()
    if text == "":
        raise AppError(400, "validation_error", f"{name} is required")
    return text


def _client_key(obj: dict):
    if "client_key" not in obj or obj["client_key"] is None:
        return None
    value = obj["client_key"]
    if not isinstance(value, str) or value.strip() == "":
        raise AppError(400, "validation_error", "client_key must be a non-empty string")
    return value


def _created_at(value):
    if value is None:
        return None
    if not isinstance(value, str) or CREATED_AT_RE.fullmatch(value) is None:
        raise AppError(400, "validation_error", "created_at must be ISO 8601 UTC")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(text)
    except ValueError:
        raise AppError(400, "validation_error", "created_at must be ISO 8601 UTC") from None
    return value


def _payload_text(kind: str, obj: dict):
    if "payload" not in obj or obj["payload"] is None:
        _check_kind_payload(kind, None)
        return None

    raw = obj["payload"]
    try:
        text = dump_payload(raw)
    except (TypeError, ValueError):
        raise AppError(400, "validation_error", "payload must be a JSON object") from None
    if len(text.encode("utf-8")) > PAYLOAD_MAX_BYTES:
        raise AppError(413, "payload_too_large", "payload exceeds 16 KiB")
    if not isinstance(raw, dict):
        raise AppError(400, "validation_error", "payload must be a JSON object")
    _check_kind_payload(kind, raw)
    return text


def _check_kind_payload(kind: str, payload):
    if kind == "news" and payload is not None:
        _check_news(payload)


def _check_news(payload: dict):
    title = payload.get("title")
    if not isinstance(title, str) or title.strip() == "":
        raise AppError(400, "validation_error", "news payload requires title")
