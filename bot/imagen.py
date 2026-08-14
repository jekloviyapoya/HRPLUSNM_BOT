"""AI poster yaratish (OpenAI gpt-image-1).

Mahsulot rasmini kirish sifatida beradi va undan reklama sahnasini
so'raydi. Rasm generatsiyasi emas, tahrir: mahsulotning o'zi tanilib
tursin.

⚠️ AI rasmda uzun matnni buzadi — harflar aralashib ketadi. Shuning
uchun posterga faqat qisqa matn beriladi: sarlavha va uchta afzallik,
har biri ikki-uch so'zdan.
"""

import base64
import logging

import requests

from . import config
from .errors import BotError

log = logging.getLogger(__name__)

API_URL = "https://api.openai.com/v1/images/edits"
MODEL = "gpt-image-1"
TIMEOUT = 180

SCENE = (
    "Turn this product photo into a clean commercial poster. "
    "Keep the product itself unchanged and clearly recognizable. "
    "Add a simple studio background with soft lighting and gentle shadow. "
    "Leave empty space at the top and bottom for text. "
    "Do not add any text, letters, numbers or logos to the image."
)


class ImageError(BotError):
    def __init__(self, message=None):
        super().__init__(message or "Poster yasab bo'lmadi.")


def enabled():
    return bool(config.OPENAI_API_KEY)


def make_poster(image_bytes, mime="image/jpeg", prompt=None, session=None):
    """Mahsulot rasmidan poster. Qaytadi: bayt."""
    if not enabled():
        raise ImageError("Poster kaliti sozlanmagan. Sotuvchiga murojaat "
                         "qiling.")
    http = session or requests
    try:
        resp = http.post(
            API_URL,
            headers={"Authorization": f"Bearer {config.OPENAI_API_KEY}"},
            files={"image": ("product.jpg", image_bytes, mime)},
            data={"model": MODEL, "prompt": prompt or SCENE,
                  "size": "1024x1024", "input_fidelity": "high"},
            timeout=TIMEOUT,
        )
    except Exception as e:  # noqa: BLE001 — tarmoq
        log.warning("Poster so'rovi yiqildi: %s", e)
        raise ImageError("Poster xizmatiga ulanib bo'lmadi.")

    if resp.status_code != 200:
        detail = ""
        try:
            detail = str(resp.json().get("error", {}).get("message", ""))[:160]
        except Exception:  # noqa: BLE001
            detail = resp.text[:160]
        log.warning("Poster xatosi %s: %s", resp.status_code, detail)
        raise ImageError(f"Poster yasalmadi. {detail}".strip())

    try:
        data = (resp.json().get("data") or [{}])[0]
    except ValueError:
        raise ImageError("Poster xizmati tushunarsiz javob qaytardi.")
    if not data.get("b64_json"):
        raise ImageError("Javobda rasm yo'q.")
    return base64.b64decode(data["b64_json"])
