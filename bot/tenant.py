"""Ijarachi sozlamalari.

Eng muhim qoida: get() STANDART QIYMAT BERMAYDI. Sozlanmagan bo'lsa None
qaytadi, require() esa foydalanuvchiga tushunarli xato beradi. Kodda birorta
do'konga xos qiymat qotirilmaydi.
"""

import json
import threading

from . import db
from .errors import SetupError

TENANT_ID = 1

_cache = {}
_cache_lock = threading.RLock()

# Sozlama kaliti -> qaysi bo'limda to'ldiriladi (xato matnida ko'rsatiladi)
SECTIONS = {
    "shop_name": "Sozlamalar → Do'kon",
    "bito_api_key": "Sozlamalar → Bito ulanishi",
    "bito_org_id": "Sozlamalar → Bito ulanishi",
    "warehouse_id": "Sozlamalar → Ombor",
    "price_id": "Sozlamalar → Ombor",
    "currency_id": "Sozlamalar → Bito ulanishi",
    "uom_piece_id": "Sozlamalar → Ombor",
    "uom_kg_id": "Sozlamalar → Ombor",
    "plu_field_id": "Sozlamalar → Ombor",
    "channel_id": "Sozlamalar → Marketing",
    "work_hours": "Sozlamalar → Do'kon",
    "morning_time": "Sozlamalar → AI va eslatmalar",
}


def ensure_row():
    if not db.row("SELECT id FROM tenant WHERE id = ?", (TENANT_ID,)):
        db.run("INSERT INTO tenant (id) VALUES (?)", (TENANT_ID,))


def get(key, default=None):
    """Sozlamani qaytaradi. Yo'q bo'lsa default (odatda None)."""
    with _cache_lock:
        if key in _cache:
            return _cache[key]
    val = db.value(
        "SELECT value FROM settings WHERE tenant_id = ? AND key = ?",
        (TENANT_ID, key),
    )
    with _cache_lock:
        _cache[key] = val
    return default if val is None else val


def require(key):
    """Sozlangan bo'lishi shart. Aks holda SetupError."""
    val = get(key)
    if val in (None, ""):
        raise SetupError.for_key(key, SECTIONS.get(key, "Sozlamalar"))
    return val


def set(key, value):  # noqa: A001 — atayin qisqa nom
    val = None if value is None else str(value)
    db.run(
        "INSERT INTO settings (tenant_id, key, value, updated_at) "
        "VALUES (?, ?, ?, datetime('now')) "
        "ON CONFLICT (tenant_id, key) DO UPDATE SET "
        "  value = excluded.value, updated_at = excluded.updated_at",
        (TENANT_ID, key, val),
    )
    with _cache_lock:
        _cache[key] = val
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
    return {
        r["key"]: r["value"]
        for r in db.rows(
            "SELECT key, value FROM settings WHERE tenant_id = ?", (TENANT_ID,)
        )
    }


def missing(keys):
    """Berilgan kalitlardan sozlanmaganlarini qaytaradi."""
    return [k for k in keys if get(k) in (None, "")]


def clear_cache():
    with _cache_lock:
        _cache.clear()


def shop_name():
    """AI so'rovlari va postlarda ishlatiladi. Sehrgarda albatta so'raladi."""
    return get("shop_name") or "Do'kon"


def setup_done():
    ensure_row()
    return bool(
        db.value("SELECT setup_done FROM tenant WHERE id = ?", (TENANT_ID,))
    )


def mark_setup_done():
    db.run("UPDATE tenant SET setup_done = 1, setup_step = NULL WHERE id = ?",
           (TENANT_ID,))
