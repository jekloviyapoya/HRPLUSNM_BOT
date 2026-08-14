"""Ovoz → matn (Groq Whisper).

Ovozli xabar shu yerda matnga aylanadi, keyin xuddi yozilgan xabarday
odatiy oqimga qaytariladi. `GROQ_API_KEY` bo'sh bo'lsa modul o'chiq.

Til berilmaydi — Whisper o'zi aniqlaydi: mijozlar o'zbekcha ham,
ruscha ham gapiradi.
"""

import logging

import requests

from . import config
from .errors import BotError

log = logging.getLogger(__name__)

URL = "https://api.groq.com/openai/v1/audio/transcriptions"
MODEL = "whisper-large-v3"
MAX_SECONDS = 120           # do'kon topshirig'i uchun yetarli
TIMEOUT = 60


def enabled():
    return bool(config.GROQ_API_KEY)


def transcribe(content, filename="voice.ogg", session=None):
    """Audio baytlar → matn. Xatoda foydalanuvchiga tushunarli BotError."""
    if not enabled():
        raise BotError("Ovozli xabarlar hozircha sozlanmagan — matn yozing.")

    http = session or requests
    try:
        resp = http.post(
            URL,
            headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
            data={"model": MODEL, "response_format": "json"},
            files={"file": (filename, content)},
            timeout=TIMEOUT,
        )
    except Exception as e:  # noqa: BLE001 — tarmoq
        raise BotError("Ovoz xizmatiga ulanib bo'lmadi. Matn yozib "
                       "yuboring.") from e

    if resp.status_code != 200:
        # Kalit yoki kvota muammosi — logga to'liq, mijozga sodda
        log.warning("Whisper %s: %s", resp.status_code,
                    str(getattr(resp, "text", ""))[:200])
        raise BotError("Ovozni matnga aylantirib bo'lmadi. Matn yozib "
                       "yuboring.")

    try:
        text = (resp.json().get("text") or "").strip()
    except ValueError:
        text = ""
    if not text:
        raise BotError("Ovozdan matn chiqmadi — aniqroq gapirib qayta "
                       "yuboring yoki yozing.")
    return text
