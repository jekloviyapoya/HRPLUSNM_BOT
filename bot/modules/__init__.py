"""Modul litsenziyasi.

Tarif pog'onalari (boshlangich/standart/toliq) o'rniga — har modul alohida
yoqiladi. Sabab: mijozlarning ehtiyoji pog'onali emas. Biriga faqat xodimlar
kerak, boshqasiga xodimlar va ombor AI. Pog'onali tarifda o'rtadagi mijoz
keraksiz modullar uchun to'laydi.

Yoqilgan modullar ro'yxati litsenziyada (JSON massiv) saqlanadi va BMP_BOT
dan keladi.
"""

import json
import logging

from . import registry
from .. import ctx, db
from ..errors import BotError

log = logging.getLogger(__name__)

KEYS = registry.KEYS
BY_KEY = registry.BY_KEY

# Sinov davrida hammasi ochiq: mijoz nima sotib olishini ko'rib tanlasin
TRIAL_MODULES = list(KEYS)


class ModuleError(BotError):
    def __init__(self, key):
        self.key = key
        spec = BY_KEY.get(key)
        title = spec.title if spec else key
        super().__init__(
            f"«{title}» moduli yoqilmagan.\n"
            "💳 Obuna bo'limidan qo'shishni so'rashingiz mumkin."
        )


def _row():
    return db.row(
        "SELECT modules, state, license_key FROM license WHERE tenant_id = ?",
        (ctx.require(),),
    )


def list_enabled(tenant_id=None):
    """Joriy biznesda yoqilgan modullar (katalog tartibida)."""
    tid = tenant_id or ctx.require()
    raw = db.value("SELECT modules FROM license WHERE tenant_id = ?", (tid,))
    if raw is None:
        return []
    try:
        keys = json.loads(raw)
    except (ValueError, TypeError):
        log.warning("modules JSON buzuq: tenant=%s", tid)
        return []
    if not isinstance(keys, list):
        return []
    return [k for k in KEYS if k in keys]


def set_enabled(keys, tenant_id=None):
    """Ro'yxatni saqlaydi. Bog'liqliklar avtomatik qo'shiladi."""
    tid = tenant_id or ctx.require()
    resolved = registry.resolve_depends(keys)
    db.run(
        "UPDATE license SET modules = ? WHERE tenant_id = ?",
        (json.dumps(resolved), tid),
    )
    return resolved


def enabled(key, tenant_id=None):
    return key in list_enabled(tenant_id)


def require(key):
    """Yoqilmagan bo'lsa ModuleError. Obuna qulflangan bo'lsa ham xato."""
    from .. import license  # aylanma importdan qochish

    if license.is_locked():
        raise license.LicenseError()
    if not enabled(key):
        raise ModuleError(key)
    spec = BY_KEY.get(key)
    if spec:
        for dep in spec.depends:
            if not enabled(dep):
                raise ModuleError(dep)
    return True


def available(tenant_id=None):
    """Yoqilgan VA yozilgan modullar — menyu shulardan quriladi."""
    active = set(list_enabled(tenant_id))
    return [s for s in registry.CATALOG if s.key in active and s.ready]


def catalog_status(tenant_id=None):
    """Obuna ekrani uchun: [(spec, yoqilganmi, tayyormi), ...]"""
    active = set(list_enabled(tenant_id))
    return [(s, s.key in active, s.ready) for s in registry.CATALOG]


def menu_items(role, tenant_id=None):
    items = []
    for spec in available(tenant_id):
        try:
            items.extend(spec.impl.menu(role) or [])
        except Exception:  # noqa: BLE001 — bitta modul menyuni yiqitmasin
            log.exception("Modul menyusi xato berdi: %s", spec.key)
    return items


def tenants_with(key):
    """Shu modul yoqilgan biznes ID lari — fon ishlari uchun."""
    out = []
    for row in db.rows("SELECT tenant_id, modules FROM license"):
        try:
            keys = json.loads(row["modules"] or "[]")
        except (ValueError, TypeError):
            continue
        if key in keys:
            out.append(row["tenant_id"])
    return out
