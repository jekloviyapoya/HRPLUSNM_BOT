"""Telegram handlerlari.

Har xabarda birinchi ish — foydalanuvchi qaysi biznesga tegishli ekanini
aniqlab, ctx ga qo'yish. Busiz hech bir so'rov bajarilmaydi.
"""

import functools
import logging

from . import (config, ctx, db, license, onboarding, sessions, tenant,
               tenants, ui, users)
from .errors import BotError

log = logging.getLogger(__name__)

JOIN_PROMPT = (
    "Taklif kodini yuboring (6 ta belgi).\n"
    "Kodni do'kon egasi <b>Xodimlar</b> bo'limidan oladi."
)


def _chat_id(obj):
    msg = getattr(obj, "message", None) or obj
    return msg.chat.id


def _payload(message):
    """/start ABC123 dagi kodni ajratadi."""
    parts = (message.text or "").split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else None


def register(bot):
    def _tell(obj, text):
        try:
            bot.send_message(_chat_id(obj), text)
        except Exception:  # noqa: BLE001
            log.error("Xato xabarini yuborib bo'lmadi", exc_info=True)

    def safe(fn):
        @functools.wraps(fn)
        def wrapper(obj, *args, **kwargs):
            tg_id = obj.from_user.id
            ctx.set(tenants.find_by_user(tg_id))
            try:
                return fn(obj, *args, **kwargs)
            except BotError as e:
                log.warning("%s: %s", fn.__name__, e, exc_info=True)
                _tell(obj, f"⚠️ {e.user_message}")
            except Exception:  # noqa: BLE001 — hech nima jim yiqilmasin
                log.exception("%s da kutilmagan xato (tenant=%s)",
                              fn.__name__, ctx.current())
                _tell(obj, "⚠️ Kutilmagan xato. Log yozildi.\n"
                           f"BUILD sha={config.BUILD_SHA}")
            finally:
                ctx.clear()

        return wrapper

    def _seen(message):
        return db.seen_update(f"msg:{message.chat.id}:{message.message_id}")

    def _greet(message):
        """Biznesi bor foydalanuvchiga menyu."""
        users.touch(message.from_user.id)
        note = ""
        if users.role_of(message.from_user.id) == "owner":
            pending = onboarding.pending_summary()
            if pending:
                note = "\n\n⚙️ Sozlanmagan: " + ", ".join(pending)
        bot.send_message(
            message.chat.id,
            f"<b>{ui.escape(tenant.shop_name())}</b>\n"
            f"{ui.escape(license.summary())}{ui.escape(note)}",
            parse_mode="HTML",
            reply_markup=ui.main_menu(message.from_user.id),
        )

    # ------------------------------------------------------------------ start

    @bot.message_handler(commands=["start"])
    @safe
    def _start(message):
        if _seen(message):
            return
        tg_id = message.from_user.id

        # Yangi odam
        if ctx.current() is None:
            code = _payload(message)
            if code:
                _do_join(message, code)
                return
            bot.send_message(
                message.chat.id,
                "Salom! Bu — do'kon boshqaruv boti.\n\n"
                "Nima qilamiz?",
                reply_markup=ui.buttons(
                    [
                        ("🏪 Yangi biznes ochish", "join:new"),
                        ("👥 Jamoaga qo'shilish", "join:code"),
                    ],
                    row_width=1,
                ),
            )
            return

        # Sehrgar o'rtasida
        step = onboarding.current_step(tg_id)
        if step:
            onboarding.resume(bot, message, step)
            return

        _greet(message)

    def _do_join(message, code):
        tg_id = message.from_user.id
        tenant_id = tenants.join(
            tg_id,
            code,
            name=(message.from_user.first_name or "").strip() or None,
            username=message.from_user.username,
        )
        ctx.set(tenant_id)
        sessions.clear(tg_id)
        bot.send_message(
            message.chat.id,
            f"✅ Qo'shildingiz: <b>{ui.escape(tenant.shop_name())}</b>\n"
            "Rolingiz — xodim. Egasi kerak bo'lsa rolingizni ko'taradi.",
            parse_mode="HTML",
            reply_markup=ui.main_menu(tg_id),
        )

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("join:"))
    @safe
    def _join_click(call):
        ui.ack(bot, call)
        tg_id = call.from_user.id
        if ctx.current() is not None:
            bot.send_message(call.message.chat.id,
                             "Siz allaqachon bir biznesdasiz.")
            return

        if call.data == "join:new":
            tenant_id = tenants.create(
                tg_id,
                name=(call.from_user.first_name or "").strip() or None,
                username=call.from_user.username,
            )
            ctx.set(tenant_id)
            onboarding.start(bot, call.message, tg_id)
            return

        if call.data == "join:code":
            sessions.set(tg_id, "join:code", {})
            bot.send_message(call.message.chat.id, JOIN_PROMPT, parse_mode="HTML")

    @bot.message_handler(commands=["menu"])
    @safe
    def _menu(message):
        ctx.require()
        bot.send_message(
            message.chat.id,
            f"<b>{ui.escape(tenant.shop_name())}</b>",
            parse_mode="HTML",
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
        rows = tenants.listing()
        if not rows:
            bot.send_message(message.chat.id, "Hali biznes yo'q.")
            return
        lines = [f"Jami biznes: {len(rows)}", ""]
        for r in rows[:30]:
            lines.append(
                f"#{r['id']} {r['shop_name'] or '(nomsiz)'} — "
                f"{r['state'] or '—'}/{r['plan'] or '—'} "
                f"gacha {r['expires_at'] or '—'}, {r['staff_count']} xodim"
            )
        lines.append("")
        lines.append(f"BUILD sha={config.BUILD_SHA}")
        for chunk in ui.chunks("\n".join(lines)):
            bot.send_message(message.chat.id, chunk)

    @bot.message_handler(commands=["set_license"])
    @safe
    def _set_license(message):
        if not users.is_seller(message.from_user.id):
            return
        parts = (message.text or "").split()
        if len(parts) < 3:
            bot.send_message(
                message.chat.id,
                "Ishlatilishi: /set_license <biznes_id> YYYY-MM-DD [tarif]\n"
                "Biznes ro'yxati: /saas",
            )
            return
        try:
            tenant_id = int(parts[1])
        except ValueError:
            bot.send_message(message.chat.id, "Biznes ID raqam bo'lishi kerak.")
            return
        plan = parts[3] if len(parts) > 3 else None
        try:
            with ctx.scope(tenant_id):
                date = license.extend(parts[2], plan)
                name = tenant.shop_name()
        except ValueError:
            bot.send_message(
                message.chat.id,
                "Sana formati: YYYY-MM-DD. Tarif: boshlangich | standart | toliq",
            )
            return
        bot.send_message(
            message.chat.id, f"#{tenant_id} {name}: muddat {date} gacha."
        )
        for owner in tenants.owners_of(tenant_id):
            try:
                bot.send_message(owner, f"✅ Obuna {date} gacha uzaytirildi.")
            except Exception:  # noqa: BLE001
                log.warning("Egaga xabar ketmadi: %s", owner, exc_info=True)

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
        for tenant_id in tenants.all_ids():
            for owner in tenants.owners_of(tenant_id):
                try:
                    bot.send_message(owner, f"📢 {parts[1]}")
                    sent += 1
                except Exception:  # noqa: BLE001
                    log.warning("E'lon yuborilmadi: %s", owner, exc_info=True)
        bot.send_message(message.chat.id, f"Yuborildi: {sent} ta egaga")

    # -------------------------------------------------------- sehrgar tugmasi

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("setup:"))
    @safe
    def _setup_click(call):
        ui.ack(bot, call)
        ctx.require()
        onboarding.handle_callback(bot, call)

    # ---------------------------------------------------------- menyu tugmasi

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("menu:"))
    @safe
    def _menu_click(call):
        ui.ack(bot, call)
        ctx.require()
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
        if section == "xodimlar":
            _staff_panel(call)
            return

        bot.send_message(
            call.message.chat.id,
            f"«{section}» bo'limi keyingi bosqichda ochiladi.",
            reply_markup=ui.main_menu(call.from_user.id),
        )

    def _staff_panel(call):
        users.require_role(call.from_user.id, "manager")
        rows = users.listing()
        me = bot.get_me()
        code = tenants.invite_code()
        link = f"https://t.me/{me.username}?start={code}"
        lines = [f"<b>Jamoa</b> — {len(rows)} kishi", ""]
        role_names = {"owner": "egasi", "manager": "menejer", "staff": "xodim"}
        for u in rows:
            lines.append(
                f"• {ui.escape(u['name'] or '—')} — {role_names.get(u['role'], u['role'])}"
            )
        lines += [
            "",
            f"Taklif kodi: <code>{code}</code>",
            f"Havola: {link}",
            "",
            "Kod tarqab ketsa yangilang — eskisi ishlamay qoladi.",
        ]
        bot.send_message(
            call.message.chat.id,
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=ui.buttons(
                [("🔄 Kodni yangilash", "staff:rotate")], back="menu:root"
            ),
        )

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "staff:rotate")
    @safe
    def _rotate(call):
        ui.ack(bot, call)
        users.require_role(call.from_user.id, "owner")
        code = tenants.rotate_code()
        bot.send_message(
            call.message.chat.id,
            f"Yangi taklif kodi: <code>{code}</code>\nEski kod bekor qilindi.",
            parse_mode="HTML",
        )

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "menu:root")
    @safe
    def _root(call):
        ui.ack(bot, call)
        bot.send_message(
            call.message.chat.id,
            f"<b>{ui.escape(tenant.shop_name())}</b>",
            parse_mode="HTML",
            reply_markup=ui.main_menu(call.from_user.id),
        )

    # ------------------------------------------------------------- erkin matn

    @bot.message_handler(content_types=["text"])
    @safe
    def _text(message):
        if _seen(message):
            return
        tg_id = message.from_user.id
        state, _ = sessions.get_global(tg_id)

        if state == "join:code":
            _do_join(message, message.text or "")
            return

        if ctx.current() is None:
            bot.send_message(message.chat.id, "Boshlash uchun /start bosing.")
            return

        if onboarding.handle_text(bot, message):
            return
        if state:
            return
        bot.send_message(
            message.chat.id,
            "Menyudan tanlang:",
            reply_markup=ui.main_menu(tg_id),
        )

    @bot.message_handler(content_types=["photo", "document", "sticker"])
    @safe
    def _media(message):
        if _seen(message):
            return
        ctx.require()
        bot.send_message(
            message.chat.id,
            "Rasm va hujjat qabul qilish nakladnoy bosqichida ishga tushadi.",
        )
