"""AI chaqiruvlari.

Faqat matn va rasm tahlili. Har chaqiruv qaytadan urinishga chidamli:
tarmoq xatosi yoki server nosozligi mijozning ishini yo'qotmasin.
"""

import base64
import json
import logging
import re
import time

import requests

from . import config
from .errors import BotError

log = logging.getLogger(__name__)

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-6"
VERSION = "2023-06-01"

TIMEOUT = 180
RETRIES = 2

# 8192 — har doim ishlaydigan xavfsiz chegara.
# Undan yuqorisi uchun beta-header kerak.
SAFE_TOKENS = 8192
BIG_TOKENS = 16000
BIG_HEADER = "output-128k-2025-02-19"

IMAGE_TYPES = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "png": "image/png", "webp": "image/webp", "gif": "image/gif",
}


class AIError(BotError):
    def __init__(self, message=None):
        super().__init__(message or "AI xizmati javob bermadi. Qayta urining.")


def enabled():
    return bool(config.ANTHROPIC_API_KEY)


def image_block(data, filename="rasm.jpg"):
    ext = filename.rsplit(".", 1)[-1].lower()
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": IMAGE_TYPES.get(ext, "image/jpeg"),
            "data": base64.b64encode(data).decode(),
        },
    }


def pdf_block(data):
    return {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": base64.b64encode(data).decode(),
        },
    }


def ask(content, max_tokens=SAFE_TOKENS, big=False, session=None):
    """Bitta chaqiruv. Matn qaytaradi."""
    if not enabled():
        raise AIError("AI kaliti sozlanmagan. Sotuvchiga murojaat qiling.")

    headers = {
        "x-api-key": config.ANTHROPIC_API_KEY,
        "anthropic-version": VERSION,
        "content-type": "application/json",
    }
    if big:
        headers["anthropic-beta"] = BIG_HEADER

    body = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": content}],
    }

    http = session or requests
    last = None
    for attempt in range(RETRIES + 1):
        try:
            resp = http.post(API_URL, headers=headers, json=body, timeout=TIMEOUT)
        except Exception as e:  # noqa: BLE001 — tarmoq
            last = str(e)
            log.warning("AI so'rov xatosi (%s): %s", attempt + 1, e)
            time.sleep(2 * (attempt + 1))
            continue

        if resp.status_code == 200:
            try:
                payload = resp.json()
            except ValueError:
                raise AIError("AI tushunarsiz javob qaytardi.")
            parts = [
                block.get("text", "")
                for block in payload.get("content", [])
                if block.get("type") == "text"
            ]
            return "\n".join(parts), payload.get("stop_reason")

        # Aniq xato matnini API javobidan olamiz — status kodning o'zi
        # sababni aytmaydi
        detail = ""
        try:
            detail = str(resp.json().get("error", {}).get("message", ""))[:200]
        except Exception:  # noqa: BLE001
            detail = resp.text[:200]
        last = f"{resp.status_code}: {detail}"
        log.warning("AI xatosi: %s", last)

        if resp.status_code in (429, 500, 502, 503, 529):
            time.sleep(3 * (attempt + 1))
            continue
        break

    raise AIError(f"AI xizmati xatosi. {last or ''}".strip())


def ask_json(content, max_tokens=SAFE_TOKENS, session=None):
    """JSON kutiladigan chaqiruv.

    Javob kesilgan bo'lsa — YUQORIGA qarab qayta urinamiz. Kichikroq limit
    bilan qayta urinish faqat battar kesadi, hech narsani tuzatmaydi.
    """
    text, stop = ask(content, max_tokens=max_tokens, session=session)
    if stop == "max_tokens":
        log.info("AI javobi kesildi, kattaroq limit bilan qayta urinilmoqda")
        text, stop = ask(content, max_tokens=BIG_TOKENS, big=True,
                         session=session)
    return parse_json(text), stop


def parse_json(text):
    """Matndan JSON ajratadi. Markdown ramkasi bo'lsa ham ishlaydi."""
    if not text:
        raise AIError("AI bo'sh javob qaytardi.")
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(),
                     flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except ValueError:
        pass
    # Birinchi { dan oxirgi } gacha
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(cleaned[start:end + 1])
        except ValueError:
            pass
    raise AIError(
        "AI javobini o'qib bo'lmadi — hujjat juda katta yoki sifati past "
        "bo'lishi mumkin. Aniqroq rasm bilan qayta urining."
    )
