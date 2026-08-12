"""Ijarachi sozlamalari.

Ikki qoida:
1. get() STANDART QIYMAT BERMAYDI. Sozlanmagan bo'lsa None; require() esa
   foydalanuvchiga tushunarli xato beradi. Kodda do'konga xos qiymat yo'q.
2. Har amal joriy tenant doirasida. tenant_id ctx dan olinadi — hech qachon
   qotirilmaydi.
"""

import json
import threading

from . import ctx, db
from .errors import SetupError

_cache = {}
_cache_lock = threading.RLock()

SECTIONS = {
    "shop_name": "Sozlamalar → Do'kon",
    "bito_api_key": "Sozlamalar → Bito ulanishi",
    "bito_org_id": "Sozlamalar → Bito ulanishi",
    "warehouse_id": "Sozlamalar → Ombor",
    "price_id": "Sozlamalar → Ombor",
    "currency_id": "Sozlamalar → Bito ulanishi",
    "uom_piece_id": "Sozlamalar → Ombor",
    "uom_kg_id": "Sozlamalar → Ombor",
    "channel_id": "Sozlamalar → Marketing",
    "work_hours": "Sozlamalar → Do'kon",
    "morning_time": "Sozlamalar → AI va eslatmalar",
}


def get(key, default=None):
    tid = ctx.require()
    with _cache_lock:
        if (tid, key) in _cache:
            val = _cache[(tid, key)]
            return default if val is None else val
    val = db.value(
        "SELECT value FROM settings WHERE tenant_id = ? AND key = ?", (tid, key)
    )
    with _cache_lock:
        _cache[(tid, key)] = val
    return default if val is None else val


def require(key):
    val = get(key)
    if val in (None, ""):
        raise SetupError.for_key(key, SECTIONS.get(key, "Sozlamalar"))
    return val


def set(key, value):  # noqa: A001
    tid = ctx.require()
    val = None if value is None else str(value)
    db.run(
        "INSERT INTO settings (tenant_id, key, value, updated_at) "
        "VALUES (?, ?, ?, datetime('now')) "
        "ON CONFLICT (tenant_id, key) DO UPDATE SET "
        "  value = excluded.value, updated_at = excluded.updated_at",
        (tid, key, val),
    )
    with _cache_lock:
        _cache[(tid, key)] = val
    return val


def get_json(key, default=None):
    raw = get(key)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return default


def set_json(key, obj):
    return set(key, json.dumps(obj, ensure_ascii=False))


def all_settings():
    tid = ctx.require()
    return {
        r["key"]: r["value"]
        for r in db.rows(
            "SELECT key, value FROM settings WHERE tenant_id = ?", (tid,)
        )
    }


def missing(keys):
    return [k for k in keys if get(k) in (None, "")]


def clear_cache(tenant_id=None):
    with _cache_lock:
        if tenant_id is None:
            _cache.clear()
        else:
            for k in [k for k in _cache if k[0] == tenant_id]:
                del _cache[k]


def record():
    return db.row("SELECT * FROM tenant WHERE id = ?", (ctx.require(),))


def shop_name():
    return get("shop_name") or "Do'kon"


def setup_done():
    return bool(db.value(
        "SELECT setup_done FROM tenant WHERE id = ?", (ctx.require(),)
    ))


def mark_setup_done():
    db.run(
        "UPDATE tenant SET setup_done = 1, setup_step = NULL WHERE id = ?",
        (ctx.require(),),
    )
