"""M1 checks from doc/PDR-记录库.md section 12."""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from io import StringIO

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from recordstore.backup import backup_database
from recordstore.db import Database
from recordstore.server import RecordHTTPServer
from recordstore.validate import BODY_MAX_BYTES, PAYLOAD_MAX_BYTES, dump_payload


def trade_payload(**overrides):
    payload = {
        "symbol": "600519",
        "side": "buy",
        "qty": 100,
        "price": 1680,
        "currency": "CNY",
    }
    payload.update(overrides)
    return payload


def payload_of_size(num_bytes: int) -> dict:
    overhead = len(dump_payload({"n": ""}).encode("utf-8"))
    payload = {"n": "a" * (num_bytes - overhead)}
    actual = len(dump_payload(payload).encode("utf-8"))
    if actual != num_bytes:
        raise AssertionError(f"payload size {actual} != {num_bytes}")
    return payload


class Response:
    def __init__(self, status, headers, body: bytes):
        self.status = status
        self.headers = headers
        self.body = body
        self.json = json.loads(body.decode("utf-8")) if body else None


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "records.db")
        self.httpd = None
        self.thread = None
        self.db = None
        self.start()

    def tearDown(self):
        self.stop()

    def start(self):
        self.db = Database(self.db_path)
        self.httpd = RecordHTTPServer(("127.0.0.1", 0), self.db)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.httpd.server_address
        self.base = f"http://{host}:{port}"

    def stop(self):
        httpd = self.httpd
        if httpd is None:
            return
        self.httpd = None
        httpd.shutdown()
        self.thread.join(timeout=5)
        httpd.server_close()
        self.db.close()
        self.db = None

    def request(self, method, path, payload=None, *, raw=None, content_type="application/json"):
        headers = {}
        data = raw
        if data is None and payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if data is not None:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return Response(resp.status, resp.headers, resp.read())
        except urllib.error.HTTPError as exc:
            try:
                return Response(exc.code, exc.headers, exc.read())
            finally:
                exc.close()

    def post(self, payload, **kwargs):
        return self.request("POST", "/v1/records", payload, **kwargs)

    def test_post_note_and_trade_round_trip(self):
        note = self.post(
            {
                "source": " manual ",
                "kind": "note",
                "body": " 今天把超时从 3 秒改成 8 秒 ",
                "created_at": "2026-10-12T08:00:00Z",
                "client_key": "work:2026-10-12T08:00:00Z:1",
            }
        )
        self.assertEqual(note.status, 201)
        self.assertEqual(note.headers["Location"], f"/v1/records/{note.json['id']}")
        self.assertEqual(note.json["source"], "manual")
        self.assertEqual(note.json["kind"], "note")
        self.assertEqual(note.json["body"], "今天把超时从 3 秒改成 8 秒")
        self.assertIsNone(note.json["payload"])
        self.assertEqual(note.json["created_at"], "2026-10-12T08:00:00Z")
        self.assertNotIn("client_key", note.json)
        self.assertRegex(note.json["ingested_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

        idea = self.post({"source": "manual", "kind": "idea", "body": "一个想法"})
        self.assertEqual(idea.status, 201)
        self.assertEqual(idea.json["created_at"], idea.json["ingested_at"])
        self.assertIsNone(idea.json["payload"])

        trade_body = {
            "source": "manual",
            "kind": "trade",
            "body": "买入 100 股 600519，价格 1680 CNY",
            "created_at": "2026-10-12T01:30:00Z",
            "client_key": "trade:2026-10-12:600519:1",
            "payload": trade_payload(fee=1, account="cash"),
        }
        trade = self.post(trade_body)
        self.assertEqual(trade.status, 201)
        self.assertEqual(trade.headers["Location"], f"/v1/records/{trade.json['id']}")
        self.assertEqual(trade.json["payload"], trade_body["payload"])

        got = self.request("GET", f"/v1/records/{trade.json['id']}")
        self.assertEqual(got.status, 200)
        self.assertEqual(got.json, trade.json)

        listed = self.request("GET", "/v1/records")
        self.assertEqual(
            [row["id"] for row in listed.json["records"]],
            [note.json["id"], idea.json["id"], trade.json["id"]],
        )
        trades = self.request("GET", "/v1/records?kind=trade")
        self.assertEqual([row["id"] for row in trades.json["records"]], [trade.json["id"]])

        offset = self.post(
            {
                "source": "manual",
                "kind": "note",
                "body": "utc offset zero",
                "created_at": "2026-10-12T01:30:00+00:00",
            }
        )
        self.assertEqual(offset.status, 201)
        self.assertEqual(offset.json["created_at"], "2026-10-12T01:30:00+00:00")

    def test_missing_fields_blank_body_and_bad_created_at(self):
        cases = [
            ({}, "source"),
            ({"source": "manual"}, "kind"),
            ({"source": "manual", "kind": "note"}, "body"),
            ({"source": "  ", "kind": "note", "body": "x"}, "source"),
            ({"source": "manual", "kind": " ", "body": "x"}, "kind"),
            ({"source": "manual", "kind": "note", "body": "   "}, "body"),
            ({"source": "manual", "kind": "note", "body": 1}, "body"),
            ({"source": "manual", "kind": "note", "body": "x", "created_at": "2026-10-12T01:30:00"}, "created_at"),
            ({"source": "manual", "kind": "note", "body": "x", "created_at": "2026-10-12T01:30:00+08:00"}, "created_at"),
            ({"source": "manual", "kind": "note", "body": "x", "created_at": "not-a-date"}, "created_at"),
        ]
        for payload, needle in cases:
            with self.subTest(payload=payload):
                resp = self.post(payload)
                self.assertEqual(resp.status, 400)
                self.assertEqual(resp.json["error"], "validation_error")
                self.assertIn(needle, resp.json["message"])

    def test_body_and_payload_size_limits(self):
        exact = self.post({"source": "manual", "kind": "note", "body": "a" * BODY_MAX_BYTES})
        self.assertEqual(exact.status, 201)
        self.assertEqual(len(exact.json["body"].encode("utf-8")), BODY_MAX_BYTES)

        too_big = self.post({"source": "manual", "kind": "note", "body": "a" * (BODY_MAX_BYTES + 1)})
        self.assertEqual(too_big.status, 413)
        self.assertEqual(too_big.json["error"], "payload_too_large")

        cjk_ok = self.post({"source": "manual", "kind": "note", "body": "中" * 21845})
        self.assertEqual(cjk_ok.status, 201)
        cjk_big = self.post({"source": "manual", "kind": "note", "body": "中" * 21846})
        self.assertEqual(cjk_big.status, 413)
        self.assertEqual(cjk_big.json["error"], "payload_too_large")

        exact_payload = self.post(
            {"source": "manual", "kind": "note", "body": "sized", "payload": payload_of_size(PAYLOAD_MAX_BYTES)}
        )
        self.assertEqual(exact_payload.status, 201)
        over_payload = self.post(
            {
                "source": "manual",
                "kind": "note",
                "body": "sized",
                "payload": payload_of_size(PAYLOAD_MAX_BYTES + 1),
            }
        )
        self.assertEqual(over_payload.status, 413)
        self.assertEqual(over_payload.json["error"], "payload_too_large")

        listed = self.request("GET", "/v1/records")
        bodies = [row["body"] for row in listed.json["records"]]
        self.assertIn("a" * BODY_MAX_BYTES, bodies)
        self.assertNotIn("a" * (BODY_MAX_BYTES + 1), bodies)

    def test_trade_is_a_label(self):
        text_only = self.post({"source": "manual", "kind": "trade", "body": "买入，没写价格"})
        self.assertEqual(text_only.status, 201)
        self.assertEqual(text_only.json["kind"], "trade")
        self.assertEqual(text_only.json["body"], "买入，没写价格")
        self.assertIsNone(text_only.json["payload"])

        partial = self.post(
            {
                "source": "manual",
                "kind": "trade",
                "body": "只有代码",
                "payload": {"symbol": "600519"},
            }
        )
        self.assertEqual(partial.status, 201)
        self.assertEqual(partial.json["payload"], {"symbol": "600519"})

        null_payload = self.post(
            {"source": "manual", "kind": "trade", "body": "only text", "payload": None}
        )
        self.assertEqual(null_payload.status, 201)
        self.assertIsNone(null_payload.json["payload"])

        array_payload = self.post(
            {"source": "manual", "kind": "trade", "body": "only text", "payload": [1, 2]}
        )
        self.assertEqual(array_payload.status, 400)
        self.assertEqual(array_payload.json["error"], "validation_error")

    def test_news_payload_title(self):
        missing = self.post(
            {"source": "manual", "kind": "news", "body": "一条新闻", "payload": {"url": "https://example.com"}}
        )
        self.assertEqual(missing.status, 400)
        self.assertEqual(missing.json["error"], "validation_error")
        self.assertIn("title", missing.json["message"])

        blank = self.post(
            {"source": "manual", "kind": "news", "body": "一条新闻", "payload": {"title": "  "}}
        )
        self.assertEqual(blank.status, 400)
        self.assertEqual(blank.json["error"], "validation_error")

        plain = self.post({"source": "manual", "kind": "news", "body": "没有结构字段"})
        self.assertEqual(plain.status, 201)
        self.assertIsNone(plain.json["payload"])

        titled = self.post(
            {
                "source": "manual",
                "kind": "news",
                "body": "标题在 payload 里",
                "payload": {"title": "头条", "url": "https://example.com"},
            }
        )
        self.assertEqual(titled.status, 201)
        self.assertEqual(titled.json["payload"]["title"], "头条")

    def test_unregistered_and_invalid_kind(self):
        ok = self.post(
            {
                "source": "manual",
                "kind": "dividend",
                "body": "分红 10 CNY",
                "payload": {"symbol": "600519", "amount": 10},
            }
        )
        self.assertEqual(ok.status, 201)
        self.assertEqual(ok.json["kind"], "dividend")
        self.assertEqual(ok.json["payload"]["amount"], 10)

        bare = self.post({"source": "manual", "kind": "a" * 32, "body": "最长合法类型名"})
        self.assertEqual(bare.status, 201)

        for kind in ("Trade", "1abc", "a" * 33, "has space", "_note", "Note"):
            with self.subTest(kind=kind):
                resp = self.post({"source": "manual", "kind": kind, "body": "nope"})
                self.assertEqual(resp.status, 400)
                self.assertEqual(resp.json["error"], "validation_error")

        string_payload = self.post(
            {"source": "manual", "kind": "dividend", "body": "bad", "payload": "text"}
        )
        self.assertEqual(string_payload.status, 400)
        self.assertEqual(string_payload.json["error"], "validation_error")

        kinds = self.request("GET", "/v1/kinds")
        self.assertEqual(kinds.status, 200)
        self.assertEqual(
            kinds.json,
            {
                "kinds": [
                    {"kind": "note", "payload": "optional"},
                    {"kind": "idea", "payload": "optional"},
                    {"kind": "news", "payload": "optional"},
                    {"kind": "trade", "payload": "optional"},
                ]
            },
        )
        names = [item["kind"] for item in kinds.json["kinds"]]
        self.assertNotIn("dividend", names)

    def test_open_access_and_health(self):
        health = self.request("GET", "/health")
        self.assertEqual(health.status, 200)
        self.assertEqual(health.json, {"ok": True})

        listed = self.request("GET", "/v1/records")
        self.assertEqual(listed.status, 200)
        self.assertEqual(listed.json["records"], [])

        created = self.post({"source": "manual", "kind": "note", "body": "no token"})
        self.assertEqual(created.status, 201)
        kinds = self.request("GET", "/v1/kinds")
        self.assertEqual(kinds.status, 200)

    def test_client_key_dedup_across_kinds(self):
        first = self.post(
            {
                "source": "manual",
                "kind": "note",
                "body": "original",
                "client_key": "same-key",
            }
        )
        self.assertEqual(first.status, 201)
        second = self.post(
            {
                "source": "manual",
                "kind": "trade",
                "body": "买入 1 股 600519，价格 1 CNY",
                "client_key": "same-key",
                "payload": trade_payload(qty=1, price=1),
            }
        )
        self.assertEqual(second.status, 200)
        self.assertIsNone(second.headers.get("Location"))
        self.assertEqual(second.json, first.json)
        self.assertEqual(second.json["kind"], "note")

        other = self.post(
            {"source": "manual", "kind": "note", "body": "another", "client_key": "other-key"}
        )
        self.assertEqual(other.status, 201)
        self.assertNotEqual(other.json["id"], first.json["id"])

        no_key_a = self.post({"source": "manual", "kind": "note", "body": "one"})
        no_key_b = self.post({"source": "manual", "kind": "note", "body": "two"})
        self.assertNotEqual(no_key_a.json["id"], no_key_b.json["id"])

        conn = sqlite3.connect(self.db_path)
        try:
            count = conn.execute("SELECT count(*) FROM records").fetchone()[0]
            keyed = conn.execute(
                "SELECT count(*) FROM records WHERE client_key = ?",
                ("same-key",),
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(keyed, 1)
        self.assertEqual(count, 4)

    def test_pagination_order_and_next_after_id(self):
        ids = []
        for kind, body in (("note", "a"), ("idea", "b"), ("news", "c"), ("note", "d")):
            resp = self.post({"source": "manual", "kind": kind, "body": body})
            self.assertEqual(resp.status, 201)
            ids.append(resp.json["id"])

        page = self.request("GET", "/v1/records?limit=2")
        self.assertEqual(page.status, 200)
        self.assertEqual([row["id"] for row in page.json["records"]], ids[:2])
        self.assertEqual(page.json["next_after_id"], ids[1])

        page = self.request("GET", f"/v1/records?after_id={ids[1]}&limit=2")
        self.assertEqual([row["id"] for row in page.json["records"]], ids[2:])
        self.assertEqual(page.json["next_after_id"], ids[3])

        page = self.request("GET", "/v1/records")
        self.assertEqual([row["id"] for row in page.json["records"]], ids)
        self.assertEqual(page.json["next_after_id"], ids[-1])

        for i in range(101):
            saved, created = self.db.insert(
                source="manual",
                kind="note",
                body=f"bulk-{i}",
                payload_text=None,
                created_at="2026-10-12T00:00:00Z",
                ingested_at="2026-10-12T00:00:00Z",
                client_key=None,
            )
            self.assertTrue(created)
        # 4 earlier rows plus 101 bulk rows. Default page is 50 of the whole table.
        first = self.request("GET", "/v1/records")
        self.assertEqual(len(first.json["records"]), 50)
        self.assertEqual(first.json["next_after_id"], first.json["records"][-1]["id"])
        hundred = self.request("GET", "/v1/records?limit=100")
        self.assertEqual(len(hundred.json["records"]), 100)
        too_many = self.request("GET", "/v1/records?limit=101")
        self.assertEqual(too_many.status, 400)
        self.assertEqual(too_many.json["error"], "validation_error")
        bad_cursor = self.request("GET", "/v1/records?after_id=-1")
        self.assertEqual(bad_cursor.status, 400)
        self.assertEqual(bad_cursor.json["error"], "validation_error")

    def test_kind_filter_does_not_skip_trades(self):
        def note(text):
            resp = self.post({"source": "manual", "kind": "note", "body": text})
            self.assertEqual(resp.status, 201)
            return resp.json["id"]

        def trade(text, symbol):
            resp = self.post(
                {
                    "source": "manual",
                    "kind": "trade",
                    "body": text,
                    "payload": {"symbol": symbol, "side": "buy", "qty": 1, "price": 2},
                }
            )
            self.assertEqual(resp.status, 201)
            return resp.json["id"]

        first = trade("t1", "AAA")
        note("n1")
        note("n2")
        second = trade("t2", "BBB")
        note("n3")
        third = trade("t3", "CCC")

        page = self.request("GET", "/v1/records?kind=trade&limit=1")
        self.assertEqual([row["id"] for row in page.json["records"]], [first])
        self.assertEqual(page.json["next_after_id"], first)
        self.assertTrue(all(row["kind"] == "trade" for row in page.json["records"]))

        page = self.request("GET", f"/v1/records?kind=trade&after_id={first}&limit=1")
        self.assertEqual([row["id"] for row in page.json["records"]], [second])
        self.assertEqual(page.json["next_after_id"], second)

        page = self.request("GET", "/v1/records?kind=trade&limit=2")
        self.assertEqual([row["id"] for row in page.json["records"]], [first, second])
        self.assertEqual(page.json["next_after_id"], second)

        later = note("after the trades")
        page = self.request("GET", f"/v1/records?kind=trade&after_id={third}")
        self.assertEqual(page.json["records"], [])
        self.assertEqual(page.json["next_after_id"], third)
        self.assertNotEqual(page.json["next_after_id"], later)

        rest = self.request("GET", f"/v1/records?kind=trade&after_id={second}")
        self.assertEqual([row["id"] for row in rest.json["records"]], [third])

    def test_empty_filter_keeps_after_id(self):
        self.post({"source": "manual", "kind": "note", "body": "only a note"})
        page = self.request("GET", "/v1/records?kind=trade&after_id=0")
        self.assertEqual(page.status, 200)
        self.assertEqual(page.json, {"records": [], "next_after_id": 0})
        page = self.request("GET", "/v1/records?kind=trade&after_id=5")
        self.assertEqual(page.json["records"], [])
        self.assertEqual(page.json["next_after_id"], 5)
        page = self.request("GET", "/v1/records?kind=trade")
        self.assertEqual(page.json["next_after_id"], 0)

    def test_missing_id_and_no_delete(self):
        missing = self.request("GET", "/v1/records/999999")
        self.assertEqual(missing.status, 404)
        self.assertEqual(missing.json["error"], "not_found")
        bad = self.request("GET", "/v1/records/abc")
        self.assertEqual(bad.status, 404)
        self.assertEqual(bad.json["error"], "not_found")

        created = self.post({"source": "manual", "kind": "note", "body": "keep me"})
        deleted = self.request("DELETE", f"/v1/records/{created.json['id']}")
        self.assertEqual(deleted.status, 404)
        self.assertEqual(deleted.json["error"], "not_found")
        again = self.request("GET", f"/v1/records/{created.json['id']}")
        self.assertEqual(again.status, 200)
        self.assertEqual(again.json["body"], "keep me")

    def test_restart_preserves_rows_and_payload(self):
        note = self.post({"source": "manual", "kind": "note", "body": "重启之后还在"})
        trade = self.post(
            {
                "source": "manual",
                "kind": "trade",
                "body": "买入 100 股 600519，价格 1680 CNY",
                "payload": trade_payload(),
            }
        )
        self.assertEqual(note.status, 201)
        self.assertEqual(trade.status, 201)
        saved_note = note.json
        saved_trade = trade.json
        self.stop()
        self.start()
        listed = self.request("GET", "/v1/records")
        self.assertEqual(listed.json["records"], [saved_note, saved_trade])
        got = self.request("GET", f"/v1/records/{saved_trade['id']}")
        self.assertEqual(got.status, 200)
        self.assertEqual(got.json, saved_trade)
        self.assertEqual(got.json["payload"], trade_payload())
        only_trade = self.request("GET", "/v1/records?kind=trade")
        self.assertEqual(only_trade.json["records"], [saved_trade])

    def test_backup_snapshot_matches_row_count(self):
        note = self.post({"source": "manual", "kind": "note", "body": "backup-note"})
        trade = self.post(
            {
                "source": "manual",
                "kind": "trade",
                "body": "买入 100 股 600519，价格 1680 CNY",
                "payload": trade_payload(),
            }
        )
        self.assertEqual(note.status, 201)
        self.assertEqual(trade.status, 201)
        dest = os.path.join(self.tmp.name, "snap.db")
        backup_database(self.db_path, dest)
        src = sqlite3.connect(self.db_path)
        dst = sqlite3.connect(dest)
        try:
            src_count = src.execute("SELECT count(*) FROM records").fetchone()[0]
            dst_count = dst.execute("SELECT count(*) FROM records").fetchone()[0]
            self.assertEqual(src_count, dst_count)
            self.assertEqual(dst_count, 2)
            src_payload = src.execute(
                "SELECT payload FROM records WHERE kind = 'trade'"
            ).fetchone()[0]
            dst_payload = dst.execute(
                "SELECT payload FROM records WHERE kind = 'trade'"
            ).fetchone()[0]
            self.assertEqual(src_payload, dst_payload)
            self.assertIsNotNone(
                dst.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'records'"
                ).fetchone()
            )
        finally:
            src.close()
            dst.close()

        dest2 = os.path.join(self.tmp.name, "snap-cli.db")
        proc = subprocess.run(
            [sys.executable, "-m", "recordstore.backup", self.db_path, dest2],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("backup-note", proc.stdout)
        self.assertNotIn("600519", proc.stdout)
        dst2 = sqlite3.connect(dest2)
        try:
            self.assertEqual(dst2.execute("SELECT count(*) FROM records").fetchone()[0], 2)
        finally:
            dst2.close()

        again = subprocess.run(
            [sys.executable, "-m", "recordstore.backup", self.db_path, dest2],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(again.returncode, 1)
        self.assertTrue(os.path.isfile(self.db_path))

    def test_logs_omit_token_body_and_payload(self):
        buf = StringIO()
        with redirect_stdout(buf):
            resp = self.post(
                {
                    "source": "manual",
                    "kind": "note",
                    "body": "unique-body-text-should-not-log",
                    "payload": {"secret": "unique-payload-should-not-log"},
                }
            )
        self.assertEqual(resp.status, 201)
        text = buf.getvalue()
        self.assertNotIn("unique-body-text-should-not-log", text)
        self.assertNotIn("unique-payload-should-not-log", text)
        self.assertIn("POST", text)
        self.assertIn("/v1/records", text)
        self.assertIn("201", text)
        self.assertIn(f"id={resp.json['id']}", text)


class SchemaTest(unittest.TestCase):
    def test_schema_pragmas_and_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(os.path.join(tmp, "records.db"))
            try:
                cols = [row["name"] for row in db.conn.execute("PRAGMA table_info(records)")]
                self.assertEqual(
                    cols,
                    [
                        "id",
                        "source",
                        "kind",
                        "body",
                        "payload",
                        "created_at",
                        "ingested_at",
                        "client_key",
                    ],
                )
                index = db.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'idx_records_kind_id'"
                ).fetchone()
                self.assertIsNotNone(index)
                self.assertEqual(
                    db.conn.execute("SELECT version FROM schema_version").fetchone()["version"],
                    1,
                )
                self.assertEqual(db.conn.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
                self.assertEqual(db.conn.execute("PRAGMA synchronous").fetchone()[0], 2)
                self.assertEqual(db.conn.execute("PRAGMA busy_timeout").fetchone()[0], 5000)
                self.assertEqual(db.conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            finally:
                db.close()

            reopened = Database(os.path.join(tmp, "records.db"))
            try:
                versions = reopened.conn.execute("SELECT version FROM schema_version").fetchall()
                self.assertEqual(len(versions), 1)
                self.assertEqual(versions[0]["version"], 1)
            finally:
                reopened.close()


class ProcessTest(unittest.TestCase):
    def test_main_starts_without_token(self):
        env = os.environ.copy()
        env.pop("RECORD_TOKEN", None)
        env["RECORD_HOST"] = "127.0.0.1"
        env["RECORD_PORT"] = "0"
        env["RECORD_DB"] = os.path.join(tempfile.mkdtemp(), "records.db")
        proc = subprocess.Popen(
            [sys.executable, "-m", "recordstore"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            line = proc.stdout.readline()
            self.assertIn("listening on 127.0.0.1:0", line)
            self.assertIsNone(proc.poll())
        finally:
            proc.terminate()
            proc.wait(timeout=5)
            proc.stdout.close()
            proc.stderr.close()

    def test_backup_cli_usage(self):
        proc = subprocess.run(
            [sys.executable, "-m", "recordstore.backup"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("usage:", proc.stderr)


if __name__ == "__main__":
    unittest.main()
