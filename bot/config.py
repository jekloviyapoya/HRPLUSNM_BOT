"""Env o'zgaruvchilar va konstantalar.

Qoida: bu yerda FAQAT muhitga bog'liq qiymatlar bo'ladi.
Do'konga xos qiymat (tashkilot ID, ombor, narx-ro'yxati, do'kon nomi...)
bu yerda YO'Q — u bazadan, tenant.get() orqali olinadi.
"""

import os

def _int(name, default=0):
    raw = (os.getenv(name) or "").strip()
    try:
        return int(raw)
    except ValueError:
        return default


# --- Majburiy ---
TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
SAAS_OWNER_ID = _int("SAAS_OWNER_ID")        # sotuvchi — siz
SUPER_ADMIN_ID = _int("SUPER_ADMIN_ID") or SAAS_OWNER_ID

# --- Baza ---
# Railway'da doimiy disk /data ga ulanadi. Aks holda deployda hammasi yo'qoladi.
DB_PATH = os.getenv("DB_PATH") or "/data/bot.db"

# --- Webapp ---
PORT = _int("PORT", 8080)
PUBLIC_URL = (os.getenv("PUBLIC_URL") or "").rstrip("/")
WEBAPP_SECRET = os.getenv("WEBAPP_SECRET") or "almashtiring-bu-vaqtinchalik"

# --- Tashqi xizmatlar (ixtiyoriy: yo'q bo'lsa tegishli funksiya o'chadi) ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY") or ""
GROQ_API_KEY = os.getenv("GROQ_API_KEY") or ""
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or ""
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or ""

# --- Litsenziya serveri (BMP-BOTLAR) ---
# Bo'sh bo'lsa: mahalliy sinov muddati ishlaydi, markaz so'ralmaydi.
LICENSE_SERVER_URL = (os.getenv("LICENSE_SERVER_URL") or "").strip()
LICENSE_BOT_USERNAME = (os.getenv("LICENSE_BOT_USERNAME") or "").strip()
LICENSE_CHECK_MINUTES = _int("LICENSE_CHECK_MINUTES", 15)

# --- Bito ---
BITO_BASE_URL = (
    os.getenv("BITO_BASE_URL")
    or "https://api.bito.uz/integration-api/integration/api/v2/"
)

# --- Umumiy ---
TZ = os.getenv("TZ") or "Asia/Tashkent"
LOG_LEVEL = (os.getenv("LOG_LEVEL") or "INFO").upper()
TRIAL_DAYS = _int("TRIAL_DAYS", 14)
GRACE_DAYS = _int("GRACE_DAYS", 3)

BUILD_SHA = (
    os.getenv("RAILWAY_GIT_COMMIT_SHA")
    or os.getenv("BUILD_SHA")
    or "local"
)[:7]


def missing_required():
    """Ishga tushirishni to'xtatadigan yetishmovchiliklar ro'yxati."""
    bad = []
    if not TELEGRAM_BOT_TOKEN:
        bad.append("TELEGRAM_BOT_TOKEN")
    if not SAAS_OWNER_ID:
        bad.append("SAAS_OWNER_ID")
    return bad
