"""Management UoW, separate from every economic ledger. Reads never initialize."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from typing import Callable

from quant_shared.strategy_delivery.models import DeliveryError, canonical, digest


class DeliveryStore:
    def __init__(self, root: Path, owner: str):
        self.root = Path(root).resolve()
        self.path = self.root / "candidate-delivery.sqlite"
        self.owner = owner

    def _initialize(self, conn):
        conn.execute("CREATE TABLE IF NOT EXISTS metadata (owner TEXT NOT NULL)")
        owners = conn.execute("SELECT owner FROM metadata").fetchall()
        if not owners: conn.execute("INSERT INTO metadata VALUES (?)", (self.owner,))
        elif owners != [(self.owner,)]: raise DeliveryError("delivery_store_owner_mismatch")
        conn.execute("CREATE TABLE IF NOT EXISTS workflows (id TEXT PRIMARY KEY, payload TEXT NOT NULL, sha256 TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS events (id TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL, sha256 TEXT NOT NULL, PRIMARY KEY(id, revision))")
        conn.execute("CREATE TABLE IF NOT EXISTS requests (key TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT NOT NULL, sha256 TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS leases (environment TEXT NOT NULL, account_hash TEXT NOT NULL, workflow_id TEXT NOT NULL, PRIMARY KEY(environment, account_hash))")

    def transact(self, key: str, request_digest: str, operation: Callable) -> dict:
        self.root.mkdir(parents=True, exist_ok=True)  # explicit command only
        with closing(sqlite3.connect(self.path, timeout=15)) as conn:
            conn.execute("PRAGMA synchronous=FULL")
            try:
                conn.execute("BEGIN IMMEDIATE")
                self._initialize(conn)
                cached = conn.execute("SELECT digest,result,sha256 FROM requests WHERE key=?", (key,)).fetchone()
                if cached:
                    if cached[0] != request_digest: raise DeliveryError("idempotency_conflict")
                    result = self._decode(cached[1:])
                else:
                    result = operation(conn)
                    encoded = canonical(result)
                    conn.execute("INSERT INTO requests VALUES (?,?,?,?)", (key, request_digest, encoded, digest(result)))
                conn.commit()
                return result
            except BaseException:
                conn.rollback()
                raise

    @staticmethod
    def _decode(row):
        if row is None: raise DeliveryError("delivery_not_found", 404)
        try:
            result = json.loads(row[0])
            if digest(result) != row[1]: raise ValueError()
            return result
        except (ValueError, TypeError) as exc:
            raise DeliveryError("delivery_record_integrity_invalid") from exc

    def load(self, conn, identity):
        return self._decode(conn.execute("SELECT payload,sha256 FROM workflows WHERE id=?", (identity,)).fetchone())

    def save(self, conn, value):
        row = (value["id"], canonical(value), digest(value))
        conn.execute("INSERT INTO workflows VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,sha256=excluded.sha256", row)
        conn.execute("INSERT INTO events VALUES (?,?,?,?)", (row[0], value["revision"], row[1], row[2]))

    def reserve(self, conn, value):
        try:
            conn.execute("INSERT INTO leases VALUES (?,?,?)", (value["target"], value["binding"]["identity_hash"], value["id"]))
        except sqlite3.IntegrityError as exc:
            raise DeliveryError("account_registration_conflict") from exc

    def release(self, conn, identity):
        conn.execute("DELETE FROM leases WHERE workflow_id=?", (identity,))

    def read(self, identity=None, *, history=False):
        if not self.path.is_file():
            if identity and not history: raise DeliveryError("delivery_not_found", 404)
            return []
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=5)) as conn:
            conn.execute("PRAGMA query_only=ON")
            if conn.execute("SELECT owner FROM metadata").fetchall() != [(self.owner,)]:
                raise DeliveryError("delivery_store_owner_mismatch")
            if history:
                rows = conn.execute("SELECT payload,sha256 FROM events WHERE id=? ORDER BY revision", (identity,)).fetchall()
                return [self._decode(row) for row in rows]
            if identity: return self.load(conn, identity)
            return [self._decode(row) for row in conn.execute("SELECT payload,sha256 FROM workflows ORDER BY id")]

    def history(self, identity):
        return self.read(identity, history=True)

    def request_result(self, key, actor):
        if not self.path.is_file(): raise DeliveryError("request_not_found", 404)
        with closing(sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=5)) as conn:
            conn.execute("PRAGMA query_only=ON")
            if conn.execute("SELECT owner FROM metadata").fetchall() != [(self.owner,)]:
                raise DeliveryError("delivery_store_owner_mismatch")
            row = conn.execute("SELECT result,sha256 FROM requests WHERE key=?", (key,)).fetchone()
            if row is None: raise DeliveryError("request_not_found", 404)
            result = self._decode(row)
            if result["actor"] != actor: raise DeliveryError("request_not_found", 404)
            return result
