"""
SQLite layer. One table, `listings`, keyed by eBay item_id. Tracks
whether we've already alerted on something so reruns don't spam, and
carries enough parsed spec data for the web UI to sort/filter without
re-parsing anything.

Uses a simple additive migration (ALTER TABLE ADD COLUMN) so existing
databases from earlier versions of this tool don't need to be dropped.
"""

import sqlite3
import time
from contextlib import contextmanager

from src import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    item_id      TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    price        REAL NOT NULL,
    url          TEXT NOT NULL,
    ram_gb       INTEGER,
    gpu          TEXT,
    gpu_tier     TEXT,
    cpu          TEXT,
    brand        TEXT,
    storage_gb   INTEGER,
    dual_storage INTEGER NOT NULL DEFAULT 0,
    score        INTEGER NOT NULL,
    condition    TEXT,
    query        TEXT,
    first_seen   REAL NOT NULL,
    last_seen    REAL NOT NULL,
    alerted      INTEGER NOT NULL DEFAULT 0,
    enriched     INTEGER NOT NULL DEFAULT 0,
    active       INTEGER NOT NULL DEFAULT 1
);
"""

# columns added after the original v1 schema — migrated in automatically
_MIGRATION_COLUMNS = {
    "gpu_tier": "TEXT",
    "cpu": "TEXT",
    "brand": "TEXT",
    "storage_gb": "INTEGER",
    "dual_storage": "INTEGER NOT NULL DEFAULT 0",
    "enriched": "INTEGER NOT NULL DEFAULT 0",
    "active": "INTEGER NOT NULL DEFAULT 1",
}


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(listings)")}
    for col, coltype in _MIGRATION_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE listings ADD COLUMN {col} {coltype}")


@contextmanager
def get_conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(SCHEMA)
        _migrate(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_listing(item: dict) -> tuple[bool, bool]:
    """Insert or update a listing. Returns (is_new, already_enriched):
    - is_new: True if this item_id wasn't in the DB before this call
    - already_enriched: True if the (pre-existing) row already had its
      full item detail fetched — callers use this to avoid re-fetching
      item details for something already enriched on a previous run."""
    now = time.time()
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT item_id, enriched FROM listings WHERE item_id = ?",
            (item["item_id"],),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE listings SET price=?, score=?, last_seen=?,
                   ram_gb=?, gpu=?, gpu_tier=?, cpu=?, brand=?,
                   storage_gb=?, dual_storage=?, active=1
                   WHERE item_id=?""",
                (
                    item["price"], item["score"], now,
                    item.get("ram_gb"), item.get("gpu"), item.get("gpu_tier"),
                    item.get("cpu"), item.get("brand"), item.get("storage_gb"),
                    int(item.get("dual_storage", False)), item["item_id"],
                ),
            )
            return False, bool(existing["enriched"])
        conn.execute(
            """INSERT INTO listings
               (item_id, title, price, url, ram_gb, gpu, gpu_tier, cpu,
                brand, storage_gb, dual_storage, score, condition,
                query, first_seen, last_seen, alerted, enriched)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0)""",
            (
                item["item_id"], item["title"], item["price"], item["url"],
                item.get("ram_gb"), item.get("gpu"), item.get("gpu_tier"),
                item.get("cpu"), item.get("brand"), item.get("storage_gb"),
                int(item.get("dual_storage", False)), item["score"],
                item.get("condition"), item.get("query"), now, now,
            ),
        )
        return True, False


def mark_enriched(item_ids: list[str]) -> None:
    if not item_ids:
        return
    with get_conn() as conn:
        conn.executemany(
            "UPDATE listings SET enriched=1 WHERE item_id=?",
            [(i,) for i in item_ids],
        )


def mark_inactive(item_ids: list[str]) -> None:
    if not item_ids:
        return
    with get_conn() as conn:
        conn.executemany(
            "UPDATE listings SET active=0 WHERE item_id=?",
            [(i,) for i in item_ids],
        )


def stale_active_listings(older_than_hours: float, limit: int = 30) -> list[sqlite3.Row]:
    """Active listings not re-confirmed by search in a while — candidates
    for a direct sold/ended check via ebay_client.is_item_active()."""
    cutoff = time.time() - older_than_hours * 3600
    with get_conn() as conn:
        return conn.execute(
            """SELECT * FROM listings
               WHERE active = 1 AND last_seen < ?
               ORDER BY last_seen ASC
               LIMIT ?""",
            (cutoff, limit),
        ).fetchall()


def mark_alerted(item_ids: list[str]) -> None:
    if not item_ids:
        return
    with get_conn() as conn:
        conn.executemany(
            "UPDATE listings SET alerted=1 WHERE item_id=?",
            [(i,) for i in item_ids],
        )


def top_listings(limit: int = 100) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            """SELECT * FROM listings
               WHERE score >= ?
               ORDER BY score DESC, last_seen DESC
               LIMIT ?""",
            (config.SPEC_TARGETS["min_score_to_alert"], limit),
        ).fetchall()


def unalerted_deals() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            """SELECT * FROM listings
               WHERE score >= ? AND alerted = 0
               ORDER BY score DESC""",
            (config.SPEC_TARGETS["min_score_to_alert"],),
        ).fetchall()


def all_listings(limit: int = 1000) -> list[sqlite3.Row]:
    """Everything, regardless of score/active status — the web UI does its
    own sort/filter (including a "hide sold" toggle) client-side, so it
    needs the full picture."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM listings ORDER BY last_seen DESC LIMIT ?",
            (limit,),
        ).fetchall()


def get_listing(item_id: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM listings WHERE item_id = ?", (item_id,)
        ).fetchone()


def distinct_values(column: str) -> list[str]:
    """Used to populate filter dropdowns (brands, gpu tiers seen so far)."""
    assert column in {"brand", "gpu_tier", "query"}  # guard against injection
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT DISTINCT {column} FROM listings WHERE {column} IS NOT NULL ORDER BY {column}"
        ).fetchall()
        return [r[0] for r in rows]