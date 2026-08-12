"""Obuna: sinov → faol → grace → qulflangan.

Ma'lumot hech qachon o'chirilmaydi. Qulflanganda faqat kirish cheklanadi.
"""

import datetime as dt

from . import config, db
from .errors import LicenseError, PlanError
from .tenant import TENANT_ID

PLANS = ("boshlangich", "standart", "toliq")
_PLAN_RANK = {p: i for i, p in enumerate(PLANS)}

PLAN_LABELS = {
    "boshlangich": "Boshlang'ich",
    "standart": "Standart",
    "toliq": "To'liq",
}

# Qulflanganda ham ochiq qoladigan bo'limlar
ALWAYS_OPEN = {"obuna", "yordam", "start"}


def _today():
    return dt.date.today()


def _parse(value):
    return dt.date.fromisoformat(str(value)[:10])


def ensure():
    """Birinchi ishga tushirishda sinov muddatini ochadi."""
    if db.row("SELECT tenant_id FROM license WHERE tenant_id = ?", (TENANT_ID,)):
        return
    expires = _today() + dt.timedelta(days=config.TRIAL_DAYS)
    db.run(
        "INSERT INTO license (tenant_id, state, expires_at) VALUES (?, 'trial', ?)",
        (TENANT_ID, expires.isoformat()),
    )


def record():
    ensure()
    return db.row("SELECT * FROM license WHERE tenant_id = ?", (TENANT_ID,))


def days_left():
    return (_parse(record()["expires_at"]) - _today()).days


def state():
    """Bazadagi holatni sanaga qarab qayta hisoblaydi va saqlaydi."""
    rec = record()
    left = (_parse(rec["expires_at"]) - _today()).days
    was = rec["state"]

    if left >= 0:
        now = "trial" if was == "trial" else "active"
    elif left >= -config.GRACE_DAYS:
        now = "grace"
    else:
        now = "locked"

    if now != was:
        db.run("UPDATE license SET state = ? WHERE tenant_id = ?", (now, TENANT_ID))
    return now


def plan():
    return record()["plan"]


def is_locked():
    return state() == "locked"


def require_active(section=None):
    if section in ALWAYS_OPEN:
        return
    if is_locked():
        raise LicenseError()


def require_plan(needed):
    if _PLAN_RANK.get(plan(), 0) < _PLAN_RANK[needed]:
        raise PlanError(PLAN_LABELS[needed])


def extend(date_iso, new_plan=None):
    """Sotuvchi qo'lda uzaytiradi: /set_license YYYY-MM-DD"""
    date = _parse(date_iso)
    db.run(
        "UPDATE license SET expires_at = ?, state = 'active', "
        "  plan = COALESCE(?, plan), notified = NULL WHERE tenant_id = ?",
        (date.isoformat(), new_plan, TENANT_ID),
    )
    return date


def set_plan(new_plan):
    if new_plan not in PLANS:
        raise ValueError(new_plan)
    db.run("UPDATE license SET plan = ? WHERE tenant_id = ?", (new_plan, TENANT_ID))


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
    return (
        f"Holat: {labels[st]}\n"
        f"Tarif: {PLAN_LABELS[rec['plan']]}\n"
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
    db.run("UPDATE license SET notified = ? WHERE tenant_id = ?", (marker, TENANT_ID))

    if left > 0:
        return f"⏳ Obuna muddati {left} kundan keyin tugaydi."
    if left == 0:
        return "⏳ Obuna muddati bugun tugadi. Imtiyozli kunlar boshlandi."
    return (
        f"⚠️ Obuna muddati {abs(left)} kun oldin tugagan. "
        f"{config.GRACE_DAYS - abs(left)} kundan keyin bot qulflanadi."
    )
