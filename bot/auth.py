"""Telefon + parol bilan kirish.

Parol hech qachon ochiq saqlanmaydi — faqat xesh. Sotuvchi ham, men ham
uni bazadan o'qiy olmaymiz; unutilsa yangisi beriladi.

Telegram allaqachon foydalanuvchini tanidi. Parol shaxsni emas, **qaysi
biznesga tegishli ekanini** tasdiqlaydi: sotuvchi hisob ochadi, mijoz uni
o'ziga bog'laydi.
"""

import hashlib
import hmac
import logging
import os
import re
import secrets

from . import db
from .errors import BotError

log = logging.getLogger(__name__)

ITERATIONS = 200_000
MIN_LENGTH = 6

MAX_FAILS = 5
BLOCK_MINUTES = 15

# Chalkashadigan belgilar chiqarilgan: 0/O, 1/l/I
ALPHABET = "abcdefghjkmnpqrstuvwxyzACDEFGHJKLMNPQRSTUVWXYZ23456789"


class AuthError(BotError):
    pass


def normalize_phone(raw):
    """+998 90 123 45 67 → +998901234567"""
    digits = re.sub(r"\D", "", str(raw or ""))
    if not digits:
        return None
    if digits.startswith("998") and len(digits) == 12:
        return "+" + digits
    if len(digits) == 9:
        return "+998" + digits
    if len(digits) >= 10:
        return "+" + digits
    return None


def new_password(length=8):
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def hash_password(password):
    if len(str(password or "")) < MIN_LENGTH:
        raise AuthError(f"Parol kamida {MIN_LENGTH} ta belgi bo'lishi kerak.")
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", str(password).encode(), salt,
                                 ITERATIONS)
    return f"pbkdf2${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    """Doimiy vaqtda solishtiradi."""
    if not stored or not password:
        return False
    try:
        algo, iterations, salt_hex, digest_hex = str(stored).split("$")
    except ValueError:
        return False
    if algo != "pbkdf2":
        return False
    try:
        digest = hashlib.pbkdf2_hmac("sha256", str(password).encode(),
                                     bytes.fromhex(salt_hex), int(iterations))
    except ValueError:
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


# ---------------------------------------------------------- urinishlar cheki


def _try_row(tg_id):
    return db.row("SELECT * FROM login_try WHERE tg_id = ?", (tg_id,))


def blocked_minutes(tg_id):
    """Bloklangan bo'lsa qolgan daqiqa, aks holda 0."""
    row = _try_row(tg_id)
    if not row or not row["blocked_at"]:
        return 0
    left = db.value(
        "SELECT CAST((julianday(?, ?) - julianday('now')) * 1440 AS INTEGER)",
        (row["blocked_at"], f"+{BLOCK_MINUTES} minutes"), default=0)
    return max(int(left or 0), 0)


def note_fail(tg_id):
    db.run(
        "INSERT INTO login_try (tg_id, fails, updated_at) "
        "VALUES (?, 1, datetime('now')) ON CONFLICT (tg_id) DO UPDATE SET "
        "  fails = fails + 1, updated_at = datetime('now')",
        (tg_id,),
    )
    row = _try_row(tg_id)
    if row["fails"] >= MAX_FAILS:
        db.run("UPDATE login_try SET blocked_at = datetime('now'), fails = 0 "
               "WHERE tg_id = ?", (tg_id,))
        return True
    return False


def clear_fails(tg_id):
    db.run("DELETE FROM login_try WHERE tg_id = ?", (tg_id,))


# ------------------------------------------------------------------- hisob


def create_account(phone, name=None, password=None):
    """Sotuvchi yangi mijoz hisobini ochadi. Qaytadi: (tenant_id, parol)."""
    from . import ctx, license, tenant as tenant_mod, tenants

    normalized = normalize_phone(phone)
    if not normalized:
        raise AuthError("Telefon raqami noto'g'ri. Masalan: +998901234567")
    if db.row("SELECT id FROM tenant WHERE phone = ?", (normalized,)):
        raise AuthError("Bu raqam bilan hisob allaqachon ochilgan.")

    plain = password or new_password()
    code = tenants.new_code()
    cur = db.run(
        "INSERT INTO tenant (phone, password_hash, invite_code, must_change) "
        "VALUES (?, ?, ?, 1)",
        (normalized, hash_password(plain), code),
    )
    tenant_id = cur.lastrowid
    with ctx.scope(tenant_id):
        license.ensure()
        if name:
            tenant_mod.set("shop_name", name)
    log.info("Yangi hisob ochildi: tenant=%s", tenant_id)
    return tenant_id, plain


def login(tg_id, phone, password):
    """Telefon + parol tekshiriladi va tg_id biznesga bog'lanadi."""
    left = blocked_minutes(tg_id)
    if left:
        raise AuthError(f"Juda ko'p urinish. {left} daqiqadan keyin qayta "
                        "urining.")

    normalized = normalize_phone(phone)
    row = db.row("SELECT * FROM tenant WHERE phone = ? AND active = 1",
                 (normalized,)) if normalized else None

    if not row or not verify_password(password, row["password_hash"]):
        if note_fail(tg_id):
            raise AuthError(f"Juda ko'p noto'g'ri urinish. Hisob "
                            f"{BLOCK_MINUTES} daqiqaga bloklandi.")
        raise AuthError("Telefon yoki parol noto'g'ri.")

    clear_fails(tg_id)
    return row["id"], bool(row["must_change"])


def bind_owner(tenant_id, tg_id, name=None, username=None):
    """Foydalanuvchini biznesga egasi sifatida biriktiradi."""
    from . import ctx

    existing = db.value("SELECT tenant_id FROM users WHERE tg_id = ?", (tg_id,))
    if existing and existing != tenant_id:
        raise AuthError("Siz boshqa biznesga biriktirilgansiz. Avval "
                        "sotuvchiga murojaat qiling.")
    with ctx.scope(tenant_id):
        if existing:
            db.run("UPDATE users SET role = 'owner', active = 1 "
                   "WHERE tenant_id = ? AND tg_id = ?", (tenant_id, tg_id))
        else:
            db.run(
                "INSERT INTO users (tenant_id, tg_id, name, username, role, "
                "  last_seen) VALUES (?, ?, ?, ?, 'owner', datetime('now'))",
                (tenant_id, tg_id, name, username),
            )
    db.run("UPDATE tenant SET owner_tg_id = COALESCE(owner_tg_id, ?) "
           "WHERE id = ?", (tg_id, tenant_id))
    return tenant_id


def set_password(tenant_id, password, by_owner=True):
    db.run("UPDATE tenant SET password_hash = ?, must_change = ? WHERE id = ?",
           (hash_password(password), 0 if by_owner else 1, tenant_id))


def reset_password(tenant_id):
    """Sotuvchi yangi parol beradi. Mijoz uni almashtirishi kerak bo'ladi."""
    plain = new_password()
    set_password(tenant_id, plain, by_owner=False)
    return plain


def account(tenant_id):
    return db.row("SELECT id, phone, must_change, active FROM tenant "
                  "WHERE id = ?", (tenant_id,))


def by_phone(phone):
    normalized = normalize_phone(phone)
    return db.row("SELECT * FROM tenant WHERE phone = ?",
                  (normalized,)) if normalized else None


# ------------------------------------------- BMP orqali avto ochish (§5)


def provision_from_bmp(phone, tg_id, session=None):
    """Tasdiqlangan kontakt raqami bilan BMP'dan hisob ochadi.

    Qaytadi: (tenant_id, biznes_nomi) yoki None (BMP'da topilmadi).
    Tarmoq nosozligida licsrv.Unreachable ko'tariladi — chaqiruvchi
    mijozga «keyinroq urinib ko'ring» deydi, «topilmadi» emas.

    FAQAT Telegram kontakt orqali kelgan raqam bilan chaqiriladi
    (contact.user_id == from_user.id). Yozilgan raqam bilan EMAS.
    """
    from . import config, ctx, license, licsrv

    normalized = normalize_phone(phone)
    if not normalized:
        raise AuthError("Telefon raqami noto'g'ri.")

    found = licsrv.provision(
        normalized,
        bot_username=config.LICENSE_BOT_USERNAME or None,
        session=session,
    )
    if not found:
        return None

    # Hisob paroli hech kimga ko'rsatilmaydi — mijoz hoziroq o'zinikini
    # o'rnatadi (must_change=1). create_account takrorni o'zi tekshiradi.
    tenant_id, _plain = create_account(normalized,
                                       name=found.get("business_name"))
    with ctx.scope(tenant_id):
        license.set_key(found["key"])
        try:
            license.sync(session=session)
        except licsrv.Unreachable:
            # provision o'tdi-yu check o'tmadi — kamdan-kam. Kalit turadi,
            # fon ishi 15 daqiqada sinxronlaydi.
            log.warning("Provision o'tdi, sync emas: tenant=%s", tenant_id)
    bind_owner(tenant_id, tg_id)
    log.info("BMP'dan avto ochildi: tenant=%s", tenant_id)
    return tenant_id, found.get("business_name")
