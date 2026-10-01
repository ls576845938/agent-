"""Small orchestration records only. Economic authority stays in the runtime.

No initialization on construction/GET; BEGIN IMMEDIATE serializes commands.
Reservations are permanent: a new registration cannot reset an uncertain account.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3

from quant_shared.strategy_delivery.models import DeliveryError, canonical, digest


class OfflineStore:
    def __init__(self, root, owner):
        self.root = Path(root).resolve()
        self.path = self.root / "candidate-offline.sqlite"
        self.owner = owner

    def _owner(self, conn):
        if conn.execute("SELECT owner FROM metadata").fetchall() != [(self.owner,)]:
            raise DeliveryError("offline_store_owner_mismatch")

    @contextmanager
    def transaction(self):
        self.root.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=15)
        try:
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("CREATE TABLE IF NOT EXISTS metadata (owner TEXT NOT NULL)")
            if not conn.execute("SELECT owner FROM metadata").fetchall():
                conn.execute("INSERT INTO metadata VALUES (?)", (self.owner,))
            self._owner(conn)
            conn.execute("CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, payload TEXT NOT NULL, sha TEXT NOT NULL, PRIMARY KEY(kind,id))")
            conn.execute("CREATE TABLE IF NOT EXISTS reservations (resource TEXT PRIMARY KEY, job TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS requests (key TEXT PRIMARY KEY, request_sha TEXT NOT NULL, payload TEXT NOT NULL, sha TEXT NOT NULL)")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def decode(row):
        if row is None: raise DeliveryError("offline_record_not_found", 404)
        value = json.loads(row[0])
        if digest(value) != row[1]: raise DeliveryError("offline_record_integrity_invalid")
        return value

    def get(self, conn, kind, identity):
        return self.decode(conn.execute("SELECT payload,sha FROM records WHERE kind=? AND id=?", (kind, identity)).fetchone())

    def put(self, conn, kind, identity, value):
        conn.execute("INSERT INTO records VALUES (?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload,sha=excluded.sha",
                     (kind, identity, canonical(value), digest(value)))

    def read(self, kind, identity=None):
        if not self.path.is_file():
            if identity is not None: raise DeliveryError("offline_record_not_found", 404)
            return []
        conn = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=5)
        try:
            conn.execute("PRAGMA query_only=ON")
            self._owner(conn)
            if identity is not None: return self.get(conn, kind, identity)
            return [self.decode(row) for row in conn.execute("SELECT payload,sha FROM records WHERE kind=? ORDER BY id", (kind,))]
        finally:
            conn.close()

    def cached(self, conn, key, request_sha):
        row = conn.execute("SELECT request_sha,payload,sha FROM requests WHERE key=?", (key,)).fetchone()
        if row is None: return None
        if row[0] != request_sha: raise DeliveryError("idempotency_conflict")
        return self.decode(row[1:])

    def decisions(self, identity, before):
        """At most 20 immutable per-event receipts, no runtime or log reads."""
        if not self.path.is_file(): return []
        conn = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=5)
        try:
            conn.execute("PRAGMA query_only=ON"); self._owner(conn)
            return [self.decode(row) for row in conn.execute(
                "SELECT payload,sha FROM records WHERE kind='decision' AND id>=? AND id<? ORDER BY id DESC LIMIT 20",
                (identity + ":", identity + ":" + str(before).zfill(10)))]
        finally: conn.close()

    def cache(self, conn, key, request_sha, value):
        conn.execute("INSERT INTO requests VALUES (?,?,?,?)", (key, request_sha, canonical(value), digest(value)))

    def reserve(self, conn, resource, job):
        row = conn.execute("SELECT job FROM reservations WHERE resource=?", (resource,)).fetchone()
        if row is not None and row[0] != job: raise DeliveryError("offline_state_already_reserved")
        conn.execute("INSERT OR IGNORE INTO reservations VALUES (?,?)", (resource, job))
