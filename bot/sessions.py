"""Foydalanuvchi sessiyalari bazada saqlanadi.

Xotirada saqlansa, Railway deployda qayta ishga tushganda foydalanuvchining
yarim qolgan ishi yo'qoladi.

Biznesga hali biriktirilmagan odam ham sessiyaga ega bo'ladi (taklif kodini
kutish holati) — ular uchun tenant_id = 0.
"""

import json

from . import ctx, db

NO_TENANT = 0


def _tid(tenant_id=None):
    if tenant_id is not None:
        return tenant_id
    current = ctx.current()
    return NO_TENANT if current is None else current


def get(tg_id, tenant_id=None):
    r = db.row(
        "SELECT state, data FROM sessions WHERE tenant_id = ? AND tg_id = ?",
        (_tid(tenant_id), tg_id),
    )
    if not r:
        return None, {}
    try:
        data = json.loads(r["data"]) if r["data"] else {}
    except (ValueError, TypeError):
        data = {}
    return r["state"], data


def get_global(tg_id):
    """Tenant'dan qat'i nazar — /start oqimida kim qayerdaligi noma'lum."""
    r = db.row(
        "SELECT state, data FROM sessions WHERE tg_id = ? "
        "ORDER BY updated_at DESC LIMIT 1",
        (tg_id,),
    )
    if not r:
        return None, {}
    try:
        data = json.loads(r["data"]) if r["data"] else {}
    except (ValueError, TypeError):
        data = {}
    return r["state"], data


def set(tg_id, state, data=None, tenant_id=None):  # noqa: A001
    db.run(
        "INSERT INTO sessions (tenant_id, tg_id, state, data, updated_at) "
        "VALUES (?, ?, ?, ?, datetime('now')) "
        "ON CONFLICT (tenant_id, tg_id) DO UPDATE SET "
        "  state = excluded.state, data = excluded.data, "
        "  updated_at = excluded.updated_at",
        (_tid(tenant_id), tg_id, state, json.dumps(data or {}, ensure_ascii=False)),
    )


def patch(tg_id, **fields):
    state, data = get(tg_id)
    data.update(fields)
    set(tg_id, state, data)
    return data


def clear(tg_id, tenant_id=None):
    """Barcha kontekstlardagi sessiyani tozalaydi."""
    db.run("DELETE FROM sessions WHERE tg_id = ?", (tg_id,))
