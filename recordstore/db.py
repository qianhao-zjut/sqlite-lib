"""SQLite storage for append-only records."""

import json
import os
import sqlite3
import threading

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS records (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,
  kind TEXT NOT NULL,
  body TEXT NOT NULL,
  payload TEXT,
  created_at TEXT NOT NULL,
  ingested_at TEXT NOT NULL,
  client_key TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_records_kind_id ON records (kind, id);
CREATE TABLE IF NOT EXISTS schema_version (
  version INTEGER NOT NULL
);
"""

_RECORD_COLUMNS = "id, source, kind, body, payload, created_at, ingested_at"


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
    if str(mode).lower() != "wal":
        conn.close()
        raise RuntimeError("journal_mode must be WAL")
    conn.execute("PRAGMA synchronous = FULL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    synchronous = conn.execute("PRAGMA synchronous").fetchone()[0]
    busy = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    if synchronous != 2 or busy != 5000 or foreign_keys != 1:
        conn.close()
        raise RuntimeError("required SQLite pragmas were not applied")
    return conn


def to_record(row: sqlite3.Row) -> dict:
    payload = row["payload"]
    return {
        "id": row["id"],
        "source": row["source"],
        "kind": row["kind"],
        "body": row["body"],
        "payload": None if payload is None else json.loads(payload),
        "created_at": row["created_at"],
        "ingested_at": row["ingested_at"],
    }


class Database:
    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._lock = threading.Lock()
        self.conn = connect(self.path)
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def _init_schema(self) -> None:
        self.conn.executescript(SCHEMA_SQL)
        rows = self.conn.execute("SELECT version FROM schema_version").fetchall()
        if not rows:
            self.conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (SCHEMA_VERSION,),
            )
            return
        if len(rows) != 1 or rows[0]["version"] != SCHEMA_VERSION:
            raise RuntimeError("unsupported schema version")

    def insert(
        self,
        *,
        source: str,
        kind: str,
        body: str,
        payload_text: str | None,
        created_at: str,
        ingested_at: str,
        client_key: str | None,
    ) -> tuple[dict, bool]:
        with self._lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                if client_key is not None:
                    existing = self._find_client_key(client_key)
                    if existing is not None:
                        self._rollback()
                        return to_record(existing), False
                cur = self.conn.execute(
                    f"""
                    INSERT INTO records
                      (source, kind, body, payload, created_at, ingested_at, client_key)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (source, kind, body, payload_text, created_at, ingested_at, client_key),
                )
                new_id = cur.lastrowid
                self.conn.execute("COMMIT")
            except sqlite3.IntegrityError:
                self._rollback()
                if client_key is not None:
                    existing = self._find_client_key(client_key)
                    if existing is not None:
                        return to_record(existing), False
                raise
            except Exception:
                self._rollback()
                raise
            row = self.conn.execute(
                f"SELECT {_RECORD_COLUMNS} FROM records WHERE id = ?",
                (new_id,),
            ).fetchone()
            return to_record(row), True

    def get_record(self, record_id: int):
        with self._lock:
            row = self.conn.execute(
                f"SELECT {_RECORD_COLUMNS} FROM records WHERE id = ?",
                (record_id,),
            ).fetchone()
        if row is None:
            return None
        return to_record(row)

    def list_records(
        self,
        *,
        after_id: int,
        limit: int,
        kind: str | None,
        source: str | None = None,
    ) -> dict:
        clauses = ["id > ?"]
        params: list = [after_id]
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if source is not None:
            clauses.append("source = ?")
            params.append(source)
        params.append(limit)
        with self._lock:
            rows = self.conn.execute(
                f"""
                SELECT {_RECORD_COLUMNS}
                FROM records
                WHERE {" AND ".join(clauses)}
                ORDER BY id ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        # Cursor is the max id in this page. An empty page keeps the caller's
        # after_id, including when other kinds or sources have higher ids.
        if rows:
            next_after_id = rows[-1]["id"]
        else:
            next_after_id = after_id
        return {
            "records": [to_record(row) for row in rows],
            "next_after_id": next_after_id,
        }

    def distinct_kind_sources(self) -> dict[str, list[str]]:
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT kind, source
                FROM records
                GROUP BY kind, source
                """
            ).fetchall()
        grouped: dict[str, set[str]] = {}
        for row in rows:
            grouped.setdefault(row["kind"], set()).add(row["source"])
        return {kind: sorted(sources) for kind, sources in grouped.items()}

    def _find_client_key(self, client_key: str):
        return self.conn.execute(
            f"SELECT {_RECORD_COLUMNS} FROM records WHERE client_key = ?",
            (client_key,),
        ).fetchone()

    def _rollback(self) -> None:
        try:
            self.conn.execute("ROLLBACK")
        except sqlite3.OperationalError:
            pass
