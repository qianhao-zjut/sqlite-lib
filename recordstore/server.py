"""HTTP API on the stdlib threading server."""

import hmac
import json
import os
import re
import signal
import sys
import threading
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from recordstore.db import Database
from recordstore.errors import AppError
from recordstore.validate import KIND_RE, REGISTERED_KINDS, validate_new_record

# Larger than any request the field limits allow, including JSON escapes.
MAX_HTTP_BYTES = 2 * 1024 * 1024
_ID_PATH = re.compile(r"/v1/records/([1-9][0-9]*)$")
_INT_RE = re.compile(r"(?:0|[1-9][0-9]*)$")
_SQLITE_INT_MAX = 2**63 - 1


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class RecordHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, db: Database, token: str):
        super().__init__(server_address, RecordHandler)
        self.db = db
        self.token = token


class RecordHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "recordstore"
    sys_version = "1"

    def do_GET(self):
        self._dispatch()

    def do_POST(self):
        self._dispatch()

    def do_PUT(self):
        self._dispatch()

    def do_PATCH(self):
        self._dispatch()

    def do_DELETE(self):
        self._dispatch()

    def do_HEAD(self):
        self._dispatch()

    def log_message(self, fmt, *args):
        return

    def log_request(self, code="-", size="-"):
        return

    def _dispatch(self):
        path = urllib.parse.urlsplit(self.path).path
        record_id = None
        try:
            if self.command == "GET" and path == "/health":
                self._send_json(200, {"ok": True})
                return
            if not _authorized(self.headers.get("Authorization"), self.server.token):
                self._send_json(
                    401,
                    {"error": "unauthorized", "message": "unauthorized"},
                )
                return
            if self.command == "POST" and path == "/v1/records":
                self._post_record()
                return
            if self.command == "GET" and path == "/v1/records":
                self._list_records()
                return
            if self.command == "GET" and path == "/v1/kinds":
                self._send_json(200, {"kinds": list(REGISTERED_KINDS)})
                return
            match = _ID_PATH.fullmatch(path)
            if self.command == "GET" and match:
                record_id = int(match.group(1))
                if record_id > _SQLITE_INT_MAX:
                    self._send_json(404, _not_found(), record_id=record_id)
                    return
                self._get_record(record_id)
                return
            self._send_json(404, _not_found())
        except AppError as exc:
            self._send_json(
                exc.status,
                {"error": exc.error, "message": exc.message},
                record_id=record_id,
            )
        except Exception as exc:
            sys.stderr.write(f"internal error: {type(exc).__name__}\n")
            self._send_json(
                500,
                {"error": "internal_error", "message": "internal error"},
                record_id=record_id,
            )

    def _post_record(self):
        incoming = validate_new_record(self._read_json())
        ingested_at = utc_now()
        created_at = incoming["created_at"] or ingested_at
        record, created = self.server.db.insert(
            source=incoming["source"],
            kind=incoming["kind"],
            body=incoming["body"],
            payload_text=incoming["payload_text"],
            created_at=created_at,
            ingested_at=ingested_at,
            client_key=incoming["client_key"],
        )
        headers = {"Location": f"/v1/records/{record['id']}"} if created else None
        self._send_json(201 if created else 200, record, headers, record_id=record["id"])

    def _list_records(self):
        after_id = _query_int(self.path, "after_id", default=0, minimum=0, maximum=None)
        limit = _query_int(self.path, "limit", default=50, minimum=1, maximum=100)
        kind = _query_kind(self.path)
        page = self.server.db.list_records(after_id=after_id, limit=limit, kind=kind)
        self._send_json(200, page)

    def _get_record(self, record_id: int):
        record = self.server.db.get_record(record_id)
        if record is None:
            self._send_json(404, _not_found(), record_id=record_id)
            return
        self._send_json(200, record, record_id=record["id"])

    def _read_json(self) -> dict:
        raw_len = self.headers.get("Content-Length")
        if raw_len is None:
            raise AppError(400, "validation_error", "Content-Length is required")
        try:
            length = int(raw_len)
        except ValueError:
            raise AppError(400, "validation_error", "Content-Length is invalid") from None
        if length < 0:
            raise AppError(400, "validation_error", "Content-Length is invalid")
        if length == 0:
            raise AppError(400, "validation_error", "request body is required")
        if length > MAX_HTTP_BYTES:
            raise AppError(413, "payload_too_large", "request body is too large")
        data = self.rfile.read(length)
        if len(data) != length:
            raise AppError(400, "validation_error", "truncated request body")
        media = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if media != "application/json":
            raise AppError(400, "validation_error", "Content-Type must be application/json")
        try:
            obj = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise AppError(400, "validation_error", "request body must be JSON") from None
        if not isinstance(obj, dict):
            raise AppError(400, "validation_error", "request body must be a JSON object")
        return obj

    def _send_json(self, status: int, obj: dict, extra_headers=None, record_id=None):
        raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)
        self._access_log(status, record_id)

    def _access_log(self, status: int, record_id):
        path = urllib.parse.urlsplit(self.path).path
        line = f"{utc_now()} {self.command} {path} {status}"
        if record_id is not None:
            line += f" id={record_id}"
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def _not_found() -> dict:
    return {"error": "not_found", "message": "not found"}


def _authorized(header, expected: str) -> bool:
    if not header or not expected:
        return False
    parts = header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False
    given = parts[1].strip()
    if given == "":
        return False
    return hmac.compare_digest(given, expected)


def _query_values(path: str) -> dict:
    return urllib.parse.parse_qs(
        urllib.parse.urlsplit(path).query,
        keep_blank_values=True,
    )


def _query_int(path: str, name: str, *, default: int, minimum: int, maximum: int | None) -> int:
    values = _query_values(path)
    if name not in values:
        return default
    raw = values[name][0]
    if len(raw) > 19 or _INT_RE.fullmatch(raw) is None:
        raise AppError(400, "validation_error", f"{name} must be an integer")
    value = int(raw)
    if value > _SQLITE_INT_MAX or value < minimum or (maximum is not None and value > maximum):
        raise AppError(400, "validation_error", f"{name} is out of range")
    return value


def _query_kind(path: str):
    values = _query_values(path)
    if "kind" not in values:
        return None
    kind = values["kind"][0]
    if KIND_RE.fullmatch(kind) is None:
        raise AppError(400, "validation_error", "kind is invalid")
    return kind


def load_token() -> str:
    token = os.environ.get("RECORD_TOKEN", "").strip()
    if token == "":
        sys.stderr.write("RECORD_TOKEN is required\n")
        raise SystemExit(1)
    return token


def main() -> None:
    token = load_token()
    db_path = os.environ.get("RECORD_DB", os.path.join("data", "records.db"))
    host = os.environ.get("RECORD_HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("RECORD_PORT", "8787"))
    except ValueError:
        sys.stderr.write("RECORD_PORT must be an integer\n")
        raise SystemExit(1) from None
    db = Database(db_path)
    httpd = RecordHTTPServer((host, port), db, token)

    def stop(_signum, _frame):
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    sys.stdout.write(f"listening on {host}:{port}\n")
    sys.stdout.flush()
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
        db.close()
