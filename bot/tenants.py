"""Ijarachilar: yaratish, taklif kodi orqali qo'shilish, sotuvchi ro'yxati.

Bir odam bitta biznesda bo'ladi (users.tg_id unikal). Shu sabab kimning
nomidan yozayotgani har safar so'ralmaydi.
"""

import logging
import secrets

from . import ctx, db, license
from .errors import BotError

log = logging.getLogger(__name__)

# O'xshash belgilar chiqarib tashlangan: 0/O, 1/I/L
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LEN = 6


class JoinError(BotError):
    pass


def new_code():
    for _ in range(20):
        code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))
        if not db.row("SELECT id FROM tenant WHERE invite_code = ?", (code,)):
            return code
    raise BotError("Taklif kodi yaratilmadi. Qayta urinib ko'ring.")


def create(owner_tg_id, name=None, username=None):
    """Yangi biznes ochadi va egasini qayd qiladi. tenant_id qaytadi."""
    if find_by_user(owner_tg_id):
        raise BotError("Siz allaqachon bir biznesga biriktirilgansiz.")

    code = new_code()
    cur = db.run(
        "INSERT INTO tenant (owner_tg_id, invite_code) VALUES (?, ?)",
        (owner_tg_id, code),
    )
    tenant_id = cur.lastrowid
    db.run(
        "INSERT INTO users (tenant_id, tg_id, name, username, role, last_seen) "
        "VALUES (?, ?, ?, ?, 'owner', datetime('now'))",
        (tenant_id, owner_tg_id, name, username),
    )
    with ctx.scope(tenant_id):
        license.ensure()
    log.info("Yangi biznes: tenant=%s egasi=%s", tenant_id, owner_tg_id)
    return tenant_id


def find_by_user(tg_id):
    """Foydalanuvchi qaysi biznesda? None — hech qayerda."""
    return db.value("SELECT tenant_id FROM users WHERE tg_id = ?", (tg_id,))


def by_code(code):
    return db.row(
        "SELECT * FROM tenant WHERE invite_code = ? AND active = 1",
        ((code or "").strip().upper(),),
    )


def join(tg_id, code, name=None, username=None, role="staff"):
    """Taklif kodi bilan jamoaga qo'shilish."""
    if find_by_user(tg_id):
        raise JoinError("Siz allaqachon bir biznesga biriktirilgansiz.")
    row = by_code(code)
    if not row:
        raise JoinError("Bunday taklif kodi topilmadi. Kodni tekshiring.")
    db.run(
        "INSERT INTO users (tenant_id, tg_id, name, username, role, last_seen) "
        "VALUES (?, ?, ?, ?, ?, datetime('now'))",
        (row["id"], tg_id, name, username, role),
    )
    log.info("Jamoaga qo'shildi: tenant=%s user=%s", row["id"], tg_id)
    return row["id"]


def invite_code(tenant_id=None):
    tid = tenant_id or ctx.require()
    code = db.value("SELECT invite_code FROM tenant WHERE id = ?", (tid,))
    if not code:
        code = new_code()
        db.run("UPDATE tenant SET invite_code = ? WHERE id = ?", (code, tid))
    return code


def rotate_code(tenant_id=None):
    """Kod tarqab ketsa almashtiriladi. Eski kod ishlamay qoladi."""
    tid = tenant_id or ctx.require()
    code = new_code()
    db.run("UPDATE tenant SET invite_code = ? WHERE id = ?", (code, tid))
    return code


def set_active(tenant_id, active):
    db.run("UPDATE tenant SET active = ? WHERE id = ?",
           (1 if active else 0, tenant_id))


def listing():
    """Sotuvchi paneli uchun — hamma biznes.

    shop_name faqat settings jadvalidan olinadi. tenant.shop_name ustuni
    ishlatilmaydi: ikki manba bo'lsa ular albatta bir-biridan uzoqlashadi.
    """
    return db.rows(
        "SELECT t.id, t.owner_tg_id, t.invite_code, t.active, t.setup_done, "
        "  t.created_at, "
        "  (SELECT value FROM settings s "
        "     WHERE s.tenant_id = t.id AND s.key = 'shop_name') AS shop_name, "
        "  (SELECT COUNT(*) FROM users u WHERE u.tenant_id = t.id) AS staff_count, "
        "  l.state, l.plan, l.expires_at "
        "FROM tenant t LEFT JOIN license l ON l.tenant_id = t.id "
        "ORDER BY t.created_at DESC"
    )


def owners_of(tenant_id):
    return [
        r["tg_id"]
        for r in db.rows(
            "SELECT tg_id FROM users WHERE tenant_id = ? AND role = 'owner' "
            "AND active = 1",
            (tenant_id,),
        )
    ]


def all_ids():
    return [r["id"] for r in db.rows("SELECT id FROM tenant WHERE active = 1")]
