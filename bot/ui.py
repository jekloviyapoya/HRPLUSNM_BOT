"""Klaviaturalar, menyu va formatlash."""

import logging

from telebot import types

log = logging.getLogger(__name__)

BASE_ITEMS = [
    ("⚙️ Sozlamalar", "menu:sozlamalar"),
    ("💳 Obuna", "menu:obuna"),
]

LOCKED_ITEMS = [
    ("💳 Obuna", "menu:obuna"),
    ("❓ Yordam", "menu:yordam"),
]


def main_menu(tg_id):
    """Menyu modul reyestridan quriladi.

    Yoqilmagan modul tugmasi umuman ko'rinmaydi — mijoz sotib olmagan
    narsani ko'rib turishi kerak emas.
    """
    from . import license, modules, users

    kb = types.InlineKeyboardMarkup(row_width=2)
    if license.is_locked():
        items = LOCKED_ITEMS
    else:
        role = "owner" if users.is_seller(tg_id) else (users.role_of(tg_id) or "staff")
        items = modules.menu_items(role)
        if role in ("owner", "manager"):
            items = items + BASE_ITEMS
        else:
            items = items + [("❓ Yordam", "menu:yordam")]

    for i in range(0, len(items), 2):
        kb.row(*[
            types.InlineKeyboardButton(text, callback_data=data)
            for text, data in items[i:i + 2]
        ])
    return kb


def buttons(items, row_width=2, back=None):
    """items: [(matn, callback_data), ...]"""
    kb = types.InlineKeyboardMarkup(row_width=row_width)
    for i in range(0, len(items), row_width):
        kb.row(
            *[
                types.InlineKeyboardButton(text, callback_data=data)
                for text, data in items[i:i + row_width]
            ]
        )
    if back:
        kb.row(types.InlineKeyboardButton("⬅️ Orqaga", callback_data=back))
    return kb


def ack(bot, call, text=None):
    """answer_callback_query hech qachon handlerni yiqitmasin."""
    try:
        bot.answer_callback_query(call.id, text=text)
    except Exception:  # noqa: BLE001 — atayin: bu chaqiruv hech nimani buzmasin
        log.debug("answer_callback_query o'tmadi", exc_info=True)


def escape(text):
    """HTML parse_mode uchun. Foydalanuvchi kiritgan matn har doim shu orqali."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def money(amount, currency=""):
    try:
        n = float(amount)
    except (TypeError, ValueError):
        return "—"
    body = f"{n:,.0f}".replace(",", " ")
    return f"{body} {currency}".strip()


def caption(text, limit=1024):
    """Telegram 1024 belgidan uzun izohni jimgina rad etadi."""
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def chunks(text, limit=4000):
    """Uzun xabarni bo'laklarga bo'ladi (Telegram chegarasi 4096)."""
    out = []
    while text:
        if len(text) <= limit:
            out.append(text)
            break
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        out.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return out
