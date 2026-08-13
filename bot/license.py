"""Obuna: sinov → faol → grace → qulflangan.

Ma'lumot hech qachon o'chirilmaydi. Qulflanganda faqat kirish cheklanadi.
"""

import datetime as dt
import json as _json
import logging

from . import config, ctx, db
from .errors import LicenseError

log = logging.getLogger(__name__)

# Qulflanganda ham ochiq qoladigan bo'limlar
ALWAYS_OPEN = {"obuna", "yordam", "start"}


def _today():
    return dt.date.today()


def _parse(value):
    return dt.date.fromisoformat(str(value)[:10])


def ensure():
    """Birinchi ishga tushirishda sinov muddatini ochadi."""
    if db.row("SELECT tenant_id FROM license WHERE tenant_id = ?", (ctx.require(),)):
        return
    from . import modules as _modules  # aylanma importdan qochish

    expires = _today() + dt.timedelta(days=config.TRIAL_DAYS)
    db.run(
        "INSERT INTO license (tenant_id, state, expires_at, modules) "
        "VALUES (?, 'trial', ?, ?)",
        (
            ctx.require(),
            expires.isoformat(),
            _json.dumps(list(_modules.TRIAL_MODULES)),
        ),
    )


def record():
    ensure()
    return db.row("SELECT * FROM license WHERE tenant_id = ?", (ctx.require(),))


def days_left():
    return (_parse(record()["expires_at"]) - _today()).days


def state():
    """Holatni qaytaradi.

    Markaziy kalit bo'lsa — oxirgi ma'lum javob (aloqa yo'qligida ham
    mijoz ishlaydi). Aks holda sana bo'yicha mahalliy hisob.
    """
    rec = record()
    if rec["license_key"] and rec["source"] == "bmp":
        return rec["state"]
    left = (_parse(rec["expires_at"]) - _today()).days
    was = rec["state"]

    if left >= 0:
        now = "trial" if was == "trial" else "active"
    elif left >= -config.GRACE_DAYS:
        now = "grace"
    else:
        now = "locked"

    if now != was:
        db.run("UPDATE license SET state = ? WHERE tenant_id = ?", (now, ctx.require()))
    return now


def is_locked():
    return state() == "locked"


def require_active(section=None):
    if section in ALWAYS_OPEN:
        return
    if is_locked():
        raise LicenseError()


def extend(date_iso):
    """Sotuvchi qo'lda uzaytiradi: /set_license <biznes_id> YYYY-MM-DD"""
    date = _parse(date_iso)
    db.run(
        "UPDATE license SET expires_at = ?, state = 'active', "
        "  notified = NULL WHERE tenant_id = ?",
        (date.isoformat(), ctx.require()),
    )
    return date


def summary():
    rec = record()
    left = days_left()
    st = state()
    labels = {
        "trial": "Sinov muddati",
        "active": "Faol",
        "grace": "Muddat tugadi (imtiyozli kunlar)",
        "locked": "Qulflangan",
    }
    if left >= 0:
        tail = f"{left} kun qoldi"
    else:
        tail = f"{abs(left)} kun oldin tugagan"
    from . import modules  # aylanma importdan qochish

    count = len(modules.list_enabled())
    return (
        f"Holat: {labels[st]}\n"
        f"Modullar: {count} ta yoqilgan\n"
        f"Muddat: {rec['expires_at']} ({tail})"
    )


def due_reminder():
    """Egasiga eslatma yuborish kerakmi? Qaytadi: matn yoki None."""
    rec = record()
    left = days_left()
    marker = None
    if left in (7, 3, 1):
        marker = f"left{left}"
    elif left == 0:
        marker = "expired"
    elif left < 0 and state() == "grace":
        marker = f"grace{abs(left)}"
    if not marker or rec["notified"] == marker:
        return None
    db.run("UPDATE license SET notified = ? WHERE tenant_id = ?", (marker, ctx.require()))

    if left > 0:
        return f"⏳ Obuna muddati {left} kundan keyin tugaydi."
    if left == 0:
        return "⏳ Obuna muddati bugun tugadi. Imtiyozli kunlar boshlandi."
    return (
        f"⚠️ Obuna muddati {abs(left)} kun oldin tugagan. "
        f"{config.GRACE_DAYS - abs(left)} kundan keyin bot qulflanadi."
    )


# ---------------------------------------------------------------------------
# Markaziy litsenziya (BMP-BOTLAR)
#
# license_key bo'lmasa — yuqoridagi mahalliy mantiq ishlaydi.
# Kalit bo'lsa — haqiqat manbai BMP, mahalliy yozuv esa kesh.
# ---------------------------------------------------------------------------

import datetime as _dt  # noqa: E402

from . import licsrv  # noqa: E402


def key():
    return record()["license_key"]


def set_key(license_key):
    db.run(
        "UPDATE license SET license_key = ?, source = 'bmp', "
        "  checked_at = NULL, offline_since = NULL WHERE tenant_id = ?",
        ((license_key or "").strip(), ctx.require()),
    )


def clear_key():
    db.run(
        "UPDATE license SET license_key = NULL, source = 'local', "
        "  remote_status = NULL, offline_since = NULL WHERE tenant_id = ?",
        (ctx.require(),),
    )


def _hours_offline():
    since = record()["offline_since"]
    if not since:
        return 0.0
    try:
        started = _dt.datetime.fromisoformat(str(since))
    except ValueError:
        return 0.0
    return (_dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None) - started).total_seconds() / 3600.0


def sync(session=None):
    """Markazdan holatni oladi va saqlaydi.

    Qaytaradi: (holat, notice | None). Aloqa yo'q bo'lsa mavjud holat
    saqlanadi — mijoz ishlashda davom etadi.
    """
    rec = record()
    if not rec["license_key"]:
        return state(), None

    try:
        payload = licsrv.check(
            rec["license_key"],
            bot_username=config.LICENSE_BOT_USERNAME or None,
            session=session,
        )
    except licsrv.Unreachable as e:
        log.warning("Litsenziya serveri javob bermadi (tenant=%s): %s",
                    ctx.require(), e)
        if not rec["offline_since"]:
            db.run(
                "UPDATE license SET offline_since = ? WHERE tenant_id = ?",
                (_dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds"),
                 ctx.require()),
            )
        return state(), None

    mapped = licsrv.map_status(payload)
    expires = licsrv.expires_of(payload) or rec["expires_at"]

    # modules yo'q bo'lsa oxirgi ma'lum ro'yxat saqlanadi — server
    # nosozligi mijozning barcha modullarini o'chirib qo'ymasin
    incoming = licsrv.modules_of(payload)
    if incoming is not None:
        from . import modules as _modules
        _modules.set_enabled(incoming)
    db.run(
        "UPDATE license SET state = ?, remote_status = ?, expires_at = ?, "
        "  grace_days = ?, price = ?, checked_at = ?, offline_since = NULL, "
        "  source = 'bmp' WHERE tenant_id = ?",
        (
            mapped,
            payload.get("status"),
            str(expires)[:10],
            payload.get("grace_days"),
            payload.get("price"),
            _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds"),
            ctx.require(),
        ),
    )

    notice = licsrv.notice_of(payload)
    if notice and notice["id"] == rec["notice_id"]:
        notice = None          # bir xil xabar ikki marta ko'rsatilmaydi
    elif notice:
        db.run("UPDATE license SET notice_id = ? WHERE tenant_id = ?",
               (notice["id"], ctx.require()))
    return mapped, notice


def offline_warning():
    """Uzoq vaqt aloqa yo'q bo'lsa sotuvchiga aytiladigan matn yoki None."""
    hours = _hours_offline()
    if hours < licsrv.OFFLINE_TRUST_HOURS:
        return None
    return (
        f"Litsenziya serveri {int(hours)} soatdan beri javob bermayapti. "
        "Mijozlar ishlashda davom etmoqda."
    )
