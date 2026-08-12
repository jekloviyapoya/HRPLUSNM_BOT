"""SQLite: thread-safe wrapper va migratsiyalar.

Botda threadlar ko'p (polling, Flask, rejalashtirilgan ishlar). SQLite bitta
ulanish bilan ishlaydi, shuning uchun har amal RLock ichida.
"""

import logging
import pathlib
import sqlite3
import threading

from . import config

log = logging.getLogger(__name__)

_lock = threading.RLock()
_conn = None

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent.parent / "migrations"


def conn():
    global _conn
    with _lock:
        if _conn is None:
            path = pathlib.Path(config.DB_PATH)
            path.parent.mkdir(parents=True, exist_ok=True)
            _conn = sqlite3.connect(str(path), check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.execute("PRAGMA busy_timeout=5000")
            _conn.execute("PRAGMA foreign_keys=ON")
            log.info("Baza ochildi: %s", path)
        return _conn


def rows(sql, params=()):
    with _lock:
        return conn().execute(sql, params).fetchall()


def row(sql, params=()):
    got = rows(sql, params)
    return got[0] if got else None


def value(sql, params=(), default=None):
    got = row(sql, params)
    return got[0] if got is not None else default


def run(sql, params=()):
    with _lock:
        c = conn()
        cur = c.execute(sql, params)
        c.commit()
        return cur


def migrate():
    """migrations/*.sql fayllarini raqam tartibida bir marta qo'llaydi."""
    applied = []
    with _lock:
        c = conn()
        c.execute(
            "CREATE TABLE IF NOT EXISTS _migrations ("
            "  name TEXT PRIMARY KEY,"
            "  applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        c.commit()
        done = {r[0] for r in c.execute("SELECT name FROM _migrations")}

        for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if f.name in done:
                continue
            log.info("Migratsiya qo'llanmoqda: %s", f.name)
            c.executescript(f.read_text(encoding="utf-8"))
            c.execute("INSERT INTO _migrations (name) VALUES (?)", (f.name,))
            c.commit()
            applied.append(f.name)
    return applied


def seen_update(key):
    """True qaytarsa — bu update allaqachon ishlangan, qayta bajarilmasin."""
    with _lock:
        try:
            run("INSERT INTO idempotency (key) VALUES (?)", (str(key),))
            return False
        except sqlite3.IntegrityError:
            return True


def prune():
    """Eskirgan qatorlarni tozalash. Kuniga bir marta chaqiriladi."""
    run("DELETE FROM idempotency WHERE created_at < datetime('now', '-2 days')")
    run(
        "DELETE FROM webapp_tokens WHERE token NOT IN ("
        "  SELECT token FROM ("
        "    SELECT token, ROW_NUMBER() OVER "
        "      (PARTITION BY tg_id ORDER BY created_at DESC) AS rn"
        "    FROM webapp_tokens) WHERE rn <= 8)"
    )
