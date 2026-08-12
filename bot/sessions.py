"""Foydalanuvchi sessiyalari bazada saqlanadi.

Xotirada saqlansa, Railway deployda qayta ishga tushganda foydalanuvchining
yarim qolgan ishi yo'qoladi. Shuning uchun SQLite.
"""

import json

from . import db
from .tenant import TENANT_ID


def get(tg_id):
    r = db.row(
        "SELECT state, data FROM sessions WHERE tenant_id = ? AND tg_id = ?",
        (TENANT_ID, tg_id),
    )
    if not r:
        return None, {}
    try:
        data = json.loads(r["data"]) if r["data"] else {}
    except (ValueError, TypeError):
        data = {}
    return r["state"], data


def set(tg_id, state, data=None):  # noqa: A001
    db.run(
        "INSERT INTO sessions (tenant_id, tg_id, state, data, updated_at) "
        "VALUES (?, ?, ?, ?, datetime('now')) "
        "ON CONFLICT (tenant_id, tg_id) DO UPDATE SET "
        "  state = excluded.state, data = excluded.data, "
        "  updated_at = excluded.updated_at",
        (TENANT_ID, tg_id, state, json.dumps(data or {}, ensure_ascii=False)),
    )


def patch(tg_id, **fields):
    state, data = get(tg_id)
    data.update(fields)
    set(tg_id, state, data)
    return data


def clear(tg_id):
    db.run(
        "DELETE FROM sessions WHERE tenant_id = ? AND tg_id = ?",
        (TENANT_ID, tg_id),
    )
