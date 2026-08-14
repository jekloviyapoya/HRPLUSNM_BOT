"""Telegram handlerlari.

Har xabarda birinchi ish — foydalanuvchi qaysi biznesga tegishli ekanini
aniqlab, ctx ga qo'yish. Busiz hech bir so'rov bajarilmaydi.
"""

import functools
import logging

from . import (config, ctx, db, license, modules, onboarding, sessions,
               tenant, tenants, ui, users)
from .modules import registry
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
                "Ishlatilishi: /set_license <biznes_id> YYYY-MM-DD\n"
                "Biznes ro'yxati: /saas",
            )
            return
        try:
            tenant_id = int(parts[1])
        except ValueError:
            bot.send_message(message.chat.id, "Biznes ID raqam bo'lishi kerak.")
            return
        try:
            with ctx.scope(tenant_id):
                date = license.extend(parts[2])
                name = tenant.shop_name()
        except ValueError:
            bot.send_message(message.chat.id, "Sana formati: YYYY-MM-DD")
            return
        bot.send_message(
            message.chat.id, f"#{tenant_id} {name}: muddat {date} gacha."
        )
        for owner in tenants.owners_of(tenant_id):
            try:
                bot.send_message(owner, f"✅ Obuna {date} gacha uzaytirildi.")
            except Exception:  # noqa: BLE001
                log.warning("Egaga xabar ketmadi: %s", owner, exc_info=True)

    @bot.message_handler(commands=["set_modules"])
    @safe
    def _set_modules(message):
        if not users.is_seller(message.from_user.id):
            return
        parts = (message.text or "").split()
        if len(parts) < 2:
            bot.send_message(
                message.chat.id,
                "Ishlatilishi: /set_modules <biznes_id> kalit,kalit,...\n\n"
                "Mavjud kalitlar:\n"
                + "\n".join(f"  {s.key} — {s.title}" for s in registry.CATALOG)
                + "\n\nHammasini o'chirish: /set_modules <biznes_id> -",
            )
            return
        try:
            tenant_id = int(parts[1])
        except ValueError:
            bot.send_message(message.chat.id, "Biznes ID raqam bo'lishi kerak.")
            return

        raw = parts[2] if len(parts) > 2 else "-"
        keys = [] if raw == "-" else [
            k.strip() for k in raw.replace(" ", ",").split(",") if k.strip()
        ]
        unknown = [k for k in keys if k not in registry.BY_KEY]
        if unknown:
            bot.send_message(
                message.chat.id, f"Noma'lum kalit: {', '.join(unknown)}"
            )
            return

        with ctx.scope(tenant_id):
            resolved = modules.set_enabled(keys)
            name = tenant.shop_name()
        added = [k for k in resolved if k not in keys]
        text = f"#{tenant_id} {name}: {len(resolved)} ta modul"
        if added:
            text += f"\nBog'liqligi uchun qo'shildi: {', '.join(added)}"
        text += "\n" + (", ".join(resolved) if resolved else "(bo'sh)")
        bot.send_message(message.chat.id, text)

        for owner in tenants.owners_of(tenant_id):
            try:
                bot.send_message(owner, "🔄 Modullaringiz yangilandi. /menu")
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
            _subscription(call)
            return
        if section == "yordam":
            bot.send_message(
                call.message.chat.id,
                "Savol bo'lsa do'kon egasiga yoki sotuvchiga yozing.",
            )
            return
        if section == "sozlamalar":
            _staff_panel(call)
            return

        bot.send_message(
            call.message.chat.id,
            f"«{section}» bo'limi keyingi bosqichda ochiladi.",
            reply_markup=ui.main_menu(call.from_user.id),
        )

    # Modul handlerlari: `mod:<kalit>:...` — har biri guard orqali o'tadi
    def guard(module_key):
        """Modul handlerini o'raydi: yoqilganini tekshiradi."""

        def decorator(fn):
            @functools.wraps(fn)
            def wrapper(obj, *args, **kwargs):
                modules.require(module_key)
                return fn(obj, *args, **kwargs)

            return safe(wrapper)

        return decorator

    for _spec in registry.implemented():
        try:
            _spec.impl.register(bot, guard(_spec.key))
        except Exception:  # noqa: BLE001
            log.exception("Modul handlerlari biriktirilmadi: %s", _spec.key)

    def _subscription(call):
        rec = license.record()
        lines = [license.summary()]
        if rec["license_key"]:
            lines.append("")
            lines.append("Manba: markaziy litsenziya")
            if rec["checked_at"]:
                lines.append(f"Oxirgi tekshiruv: {rec['checked_at']} UTC")
            if rec["offline_since"]:
                lines.append("⚠️ Markaz bilan aloqa yo'q — oxirgi ma'lum "
                             "holat bo'yicha ishlayapti.")
        else:
            lines.append("")
            lines.append("Litsenziya kaliti kiritilmagan — sinov muddati.")

        lines.append("")
        lines.append("<b>Modullar</b>")
        waiting_bito = False
        for spec, on, ready, waits in modules.catalog_status():
            if waits:
                mark = "⚠️"      # to'langan, lekin Bito ulanmagan
                waiting_bito = True
            elif on and ready:
                mark = "✅"
            elif on:
                mark = "🔧"      # yoqilgan, lekin hali yozilmagan
            else:
                mark = "▫️"
            lines.append(f"{mark} {spec.title} — {ui.escape(spec.summary)}")
        if waiting_bito:
            lines.append("")
            lines.append("⚠️ — modul to'langan, lekin Bito hisobi ulanmagan. "
                         "Sozlamalardan kalitni kiriting.")
        lines.append("")
        lines.append("Qo'shimcha modul kerak bo'lsa: @ulugbekbekbergenovbmp")

        buttons = []
        if users.role_of(call.from_user.id) == "owner":
            buttons.append(
                ("🔑 Kalitni kiritish" if not rec["license_key"]
                 else "🔑 Kalitni almashtirish", "lic:key")
            )
            if rec["license_key"]:
                buttons.append(("🔄 Hozir tekshirish", "lic:sync"))
        for chunk in ui.chunks("\n".join(lines)):
            bot.send_message(
                call.message.chat.id, chunk, parse_mode="HTML",
                reply_markup=ui.buttons(buttons, row_width=1, back="menu:root")
                if buttons else None,
            )

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("lic:"))
    @safe
    def _license_click(call):
        ui.ack(bot, call)
        users.require_role(call.from_user.id, "owner")

        if call.data == "lic:key":
            sessions.set(call.from_user.id, "lic:key", {})
            bot.send_message(
                call.message.chat.id,
                "Litsenziya kalitini yuboring.\n"
                "Kalitni sotuvchi beradi — <code>GB-</code> bilan boshlanadi.",
                parse_mode="HTML",
            )
            return

        if call.data == "lic:sync":
            state, notice = license.sync()
            text = f"Tekshirildi.\n\n{license.summary()}"
            if notice:
                text += f"\n\nℹ️ {notice['text']}"
            bot.send_message(call.message.chat.id, text)

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

        if state == "lic:key":
            _save_license_key(message)
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

    def _save_license_key(message):
        users.require_role(message.from_user.id, "owner")
        key = (message.text or "").strip()
        if len(key) < 6:
            bot.send_message(message.chat.id, "Bu kalitga o'xshamaydi. Qaytadan yuboring.")
            return
        previous = license.record()["license_key"]
        license.set_key(key)
        try:
            state, notice = license.sync()
        except Exception:  # noqa: BLE001
            license.clear_key()
            if previous:
                license.set_key(previous)
            raise

        if license.record()["remote_status"] == "invalid":
            license.clear_key()
            if previous:
                license.set_key(previous)
            bot.send_message(
                message.chat.id,
                "⚠️ Bunday kalit topilmadi. Sotuvchidan qayta so'rang.",
            )
            return

        sessions.clear(message.from_user.id)
        text = f"✅ Kalit qabul qilindi.\n\n{license.summary()}"
        if notice:
            text += f"\n\nℹ️ {notice['text']}"
        bot.send_message(message.chat.id, text,
                         reply_markup=ui.main_menu(message.from_user.id))

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
