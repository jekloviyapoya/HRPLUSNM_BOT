"""BMP-BOTLAR litsenziya serveri bilan aloqa.

Asosiy qoida: **server javob bermasa mijozlar ishlashda davom etadi.**
Markaziy server yagona nosozlik nuqtasiga aylanmasligi kerak — u yiqilganda
50 ta biznes birdan to'xtasa, bu server yo'qligidan ham yomon.

Shuning uchun oxirgi ma'lum javob bazada saqlanadi va aloqa uzilganda
o'sha bilan ishlanadi. Uzoq uzilishda ham avtomatik qulflash yo'q —
faqat ogohlantirish holatiga o'tadi va sotuvchiga xabar boradi.
"""

import logging
import re

import requests

from . import config

log = logging.getLogger(__name__)

TIMEOUT = 12

# Aloqa yo'qligida oxirgi holat shuncha soat amal qiladi
OFFLINE_TRUST_HOURS = 72

STATUSES = ("active", "expired", "suspended", "invalid")


class Unreachable(Exception):
    """Server javob bermadi. Bu mijozning aybi emas — qulflanmaydi."""


def scrub(text, key):
    """Kalitni matndan olib tashlaydi.

    requests xatosi to'liq URL ni o'z ichiga oladi, unda esa ?key=... bor.
    Bu matn to'g'ridan-to'g'ri logga tushsa, kalit ochiq qoladi.
    """
    text = str(text)
    if key:
        text = text.replace(str(key), "***")
    return re.sub(r"(key=)[^&\s\'\"]+", r"\1***", text)


def base_url():
    return (config.LICENSE_SERVER_URL or "").rstrip("/")


def enabled():
    return bool(base_url())


def check(license_key, bot_username=None, session=None):
    """GET /api/check. Javobni lug'at qilib qaytaradi.

    Server javob bermasa — Unreachable. Kalit noto'g'ri bo'lsa ham javob
    keladi ({"status": "invalid"}), bu Unreachable emas.
    """
    if not enabled():
        raise Unreachable("Litsenziya serveri sozlanmagan")

    params = {"key": license_key}
    if bot_username:
        params["bot"] = bot_username

    http = session or requests
    try:
        resp = http.get(
            base_url() + "/api/check", params=params, timeout=TIMEOUT
        )
    except Exception as e:  # noqa: BLE001 — tarmoq
        raise Unreachable(scrub(e, license_key)) from e

    if resp.status_code >= 500:
        # 503 = bazaga ulanmadi. Server o'zi "offline deb hisobla" deydi.
        raise Unreachable(f"server {resp.status_code}")
    if resp.status_code >= 400:
        raise Unreachable(f"so'rov rad etildi ({resp.status_code})")

    try:
        payload = resp.json()
    except ValueError as e:
        raise Unreachable("javob JSON emas") from e

    if not isinstance(payload, dict) or payload.get("status") not in STATUSES:
        raise Unreachable("javob tushunarsiz")
    return payload


def map_status(payload):
    """BMP javobini bot holatiga o'giradi: active | grace | locked."""
    status = payload.get("status")
    if status == "active":
        return "active"
    if status == "expired":
        try:
            left = int(payload.get("days_left") or 0)
        except (TypeError, ValueError):
            left = 0
        try:
            grace = int(payload.get("grace_days") or 0)
        except (TypeError, ValueError):
            grace = 0
        # days_left manfiy: muddat tugaganidan beri necha kun o'tgani
        return "grace" if abs(min(left, 0)) <= grace else "locked"
    # suspended — sotuvchi qo'lda to'xtatgan; invalid — kalit noto'g'ri
    return "locked"


def notice_of(payload):
    """Mijozga ko'rsatiladigan xabar yoki None."""
    notice = payload.get("notice")
    if not isinstance(notice, dict):
        return None
    text = (notice.get("text") or "").strip()
    if not text:
        return None
    return {
        "id": str(notice.get("id") or text[:40]),
        "level": notice.get("level") or "info",
        "text": text,
    }
