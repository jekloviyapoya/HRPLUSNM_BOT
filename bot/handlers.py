"""Telegram handlerlari.

Qoida: har handler try/except ichida. Xato ham logga, ham foydalanuvchiga
chiqadi — jim yiqilish taqiqlanadi.
"""

import functools
import logging

from . import config, db, license, onboarding, sessions, tenant, ui, users
from .errors import BotError

log = logging.getLogger(__name__)


def _chat_id(obj):
    """Message va CallbackQuery ikkalasidan chat id ni oladi."""
    msg = getattr(obj, "message", None) or obj
    return msg.chat.id


def register(bot):
    def _tell(obj, text):
        try:
            bot.send_message(_chat_id(obj), text)
        except Exception:  # noqa: BLE001
            log.error("Xato xabarini yuborib bo'lmadi", exc_info=True)

    def safe(fn):
        @functools.wraps(fn)
        def wrapper(obj, *args, **kwargs):
            try:
                return fn(obj, *args, **kwargs)
            except BotError as e:
                log.warning("%s: %s", fn.__name__, e, exc_info=True)
                _tell(obj, f"⚠️ {e.user_message}")
            except Exception:  # noqa: BLE001 — atayin: hech nima jim yiqilmasin
                log.exception("%s da kutilmagan xato", fn.__name__)
                _tell(
                    obj,
                    "⚠️ Kutilmagan xato. Log yozildi.\n"
                    f"BUILD sha={config.BUILD_SHA}",
                )

        return wrapper

    def _seen(message):
        return db.seen_update(f"msg:{message.chat.id}:{message.message_id}")

    # ------------------------------------------------------------------ start

    @bot.message_handler(commands=["start"])
    @safe
    def _start(message):
        if _seen(message):
            return
        license.ensure()
        tenant.ensure_row()

        became_owner = onboarding.claim_owner(message)
        users.upsert(
            message.from_user.id,
            name=(message.from_user.first_name or "").strip() or None,
            username=message.from_user.username,
        )

        if became_owner:
            onboarding.start(bot, message)
            return

        if users.role_of(message.from_user.id) is None:
            bot.send_message(
                message.chat.id,
                "Salom! Sizni hali do'kon egasi qo'shmagan. "
                "Egasidan sizni xodim sifatida qo'shishini so'rang.",
            )
            return

        note = ""
        if users.role_of(message.from_user.id) == "owner":
            pending = onboarding.pending_summary()
            if pending:
                note = "\n\n⚙️ Sozlanmagan: " + ", ".join(pending)

        bot.send_message(
            message.chat.id,
            f"{tenant.shop_name()}\n{license.summary()}{note}",
            reply_markup=ui.main_menu(message.from_user.id),
        )

    @bot.message_handler(commands=["menu"])
    @safe
    def _menu(message):
        bot.send_message(
            message.chat.id,
            tenant.shop_name(),
            reply_markup=ui.main_menu(message.from_user.id),
        )

    @bot.message_handler(commands=["build"])
    @safe
    def _build(message):
        bot.send_message(message.chat.id, f"BUILD sha={config.BUILD_SHA}")

    # -------------------------------------------------------- sotuvchi paneli

    @bot.message_handler(commands=["saas"])
    @safe
    def _saas(message):
        if not users.is_seller(message.from_user.id):
            return
        owner = db.row(
            "SELECT name, username, last_seen FROM users "
            "WHERE tenant_id = 1 AND role = 'owner' LIMIT 1"
        )
        who = "—"
        if owner:
            who = owner["name"] or "—"
            if owner["username"]:
                who += f" (@{owner['username']})"
        bot.send_message(
            message.chat.id,
            "\n".join(
                [
                    f"Do'kon: {tenant.shop_name()}",
                    license.summary(),
                    f"Egasi: {who}",
                    f"Oxirgi faollik: {owner['last_seen'] if owner else '—'}",
                    f"Sozlash tugagan: {'ha' if tenant.setup_done() else 'yoq'}",
                    f"BUILD sha={config.BUILD_SHA}",
                ]
            ),
        )

    @bot.message_handler(commands=["set_license"])
    @safe
    def _set_license(message):
        if not users.is_seller(message.from_user.id):
            return
        parts = (message.text or "").split()
        if len(parts) < 2:
            bot.send_message(
                message.chat.id, "Ishlatilishi: /set_license YYYY-MM-DD [tarif]"
            )
            return
        plan = parts[2] if len(parts) > 2 else None
        try:
            date = license.extend(parts[1], plan)
        except ValueError:
            bot.send_message(
                message.chat.id,
                "Sana formati: YYYY-MM-DD. Tarif: boshlangich | standart | toliq",
            )
            return
        bot.send_message(message.chat.id, f"Muddat {date} gacha uzaytirildi.")

    @bot.message_handler(commands=["saas_msg"])
    @safe
    def _saas_msg(message):
        if not users.is_seller(message.from_user.id):
            return
        parts = (message.text or "").split(" ", 1)
        if len(parts) < 2:
            bot.send_message(message.chat.id, "Ishlatilishi: /saas_msg <matn>")
            return
        sent = 0
        for u in users.listing():
            if u["role"] != "owner":
                continue
            try:
                bot.send_message(u["tg_id"], f"📢 {parts[1]}")
                sent += 1
            except Exception:  # noqa: BLE001
                log.warning("E'lon yuborilmadi: %s", u["tg_id"], exc_info=True)
        bot.send_message(message.chat.id, f"Yuborildi: {sent} ta")

    # ---------------------------------------------------------- menyu tugmasi

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("menu:"))
    @safe
    def _menu_click(call):
        ui.ack(bot, call)
        section = call.data.split(":", 1)[1]
        license.require_active(section)

        if section == "obuna":
            bot.send_message(call.message.chat.id, license.summary())
            return
        if section == "yordam":
            bot.send_message(
                call.message.chat.id,
                "Savol bo'lsa do'kon egasiga yoki sotuvchiga yozing.",
            )
            return

        bot.send_message(
            call.message.chat.id,
            f"«{section}» bo'limi keyingi bosqichda ochiladi.",
            reply_markup=ui.main_menu(call.from_user.id),
        )

    # ------------------------------------------------------------- erkin matn

    @bot.message_handler(content_types=["text"])
    @safe
    def _text(message):
        if _seen(message):
            return
        if onboarding.handle_text(bot, message):
            return
        state, _ = sessions.get(message.from_user.id)
        if state:
            return
        bot.send_message(
            message.chat.id,
            "Menyudan tanlang:",
            reply_markup=ui.main_menu(message.from_user.id),
        )

    # WEBP rasm content_type='sticker' bo'lib keladi — uchalasi ham ushlanadi
    @bot.message_handler(content_types=["photo", "document", "sticker"])
    @safe
    def _media(message):
        if _seen(message):
            return
        bot.send_message(
            message.chat.id,
            "Rasm va hujjat qabul qilish nakladnoy bosqichida ishga tushadi.",
        )
