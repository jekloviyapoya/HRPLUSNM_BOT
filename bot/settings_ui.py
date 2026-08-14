"""Sozlamalar bo'limi.

Modul emas — har doim ochiq. Mijoz hamma qiymatni shu yerdan qo'yadi:
Bito ulanishi, do'kon ma'lumotlari, xodimlar jadvali va stavkasi.

Busiz mijoz mustaqil ishlay olmaydi: jadval qo'yilmasa kechikish
hisoblanmaydi, ish joyi belgilanmasa davomat tekshirilmaydi.
"""

import logging

from telebot import types

from . import auth, bito, catalog, ctx, db, sessions, tenant, ui, users
from .errors import BotError
from .modules import xodimlar

log = logging.getLogger(__name__)

SECTIONS = [
    ("dokon", "🏪 Do'kon", "Nom, ish joyi, valyuta, vaqt mintaqasi"),
    ("bito", "🔗 Bito ulanishi", "Kalit, tashkilot, ombor, narx-ro'yxati"),
    ("xodimlar", "👥 Xodimlar", "Rol, ish jadvali, stavka"),
    ("ombor", "📦 Ombor", "Kam qolgan chegarasi"),
    ("hisob", "🔑 Hisob", "Parolni o'zgartirish"),
]


def _label(value, empty="qo'yilmagan"):
    return ui.escape(str(value)) if value else f"<i>{empty}</i>"


# ----------------------------------------------------------------- ro'yxat


def panel(bot, chat_id, tg_id):
    users.require_role(tg_id, "manager")
    lines = ["<b>Sozlamalar</b>", ""]
    for key, title, hint in SECTIONS:
        lines.append(f"{title} — {ui.escape(hint)}")
    bot.send_message(
        chat_id, "\n".join(lines), parse_mode="HTML",
        reply_markup=ui.buttons(
            [(title, f"set:{key}") for key, title, _ in SECTIONS],
            row_width=1, back="menu:root"),
    )


# ------------------------------------------------------------------ do'kon


DOKON_FIELDS = [
    ("shop_name", "Do'kon nomi", "matn"),
    ("currency_name", "Valyuta nomi", "matn"),
    ("tz_offset", "Vaqt mintaqasi (UTC+)", "son"),
    ("work_radius_m", "Ish joyi radiusi (metr)", "son"),
]


def dokon(bot, chat_id, tg_id):
    place = tenant.get_json("work_place")
    lines = ["<b>Do'kon</b>", ""]
    lines.append(f"Nomi: {_label(tenant.get('shop_name'))}")
    lines.append(f"Valyuta: {_label(tenant.get('currency_name'), 'so‘m')}")
    lines.append(f"Vaqt mintaqasi: UTC+{tenant.get('tz_offset') or 5}")
    if place:
        lines.append(f"Ish joyi: {place['lat']:.5f}, {place['lon']:.5f}")
        lines.append(f"Radius: {tenant.get('work_radius_m') or 200} m")
    else:
        lines.append("Ish joyi: <i>belgilanmagan</i> — davomatda joylashuv "
                     "so'ralmaydi")

    buttons = [(f"✏️ {title}", f"set:dokon:{key}")
               for key, title, _ in DOKON_FIELDS]
    buttons.append(("📍 Ish joyini belgilash", "set:dokon:joy"))
    if place:
        buttons.append(("🗑 Ish joyini o'chirish", "set:dokon:joy_ochir"))
    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML",
                     reply_markup=ui.buttons(buttons, row_width=1,
                                             back="menu:sozlamalar"))


# -------------------------------------------------------------------- bito


def bito_panel(bot, chat_id, tg_id):
    users.require_role(tg_id, "owner")
    lines = ["<b>Bito ulanishi</b>", ""]
    key = tenant.get("bito_api_key")
    lines.append(f"Kalit: {'✅ kiritilgan' if key else '❌ yo‘q'}")
    lines.append(f"Tashkilot: {_label(tenant.get('bito_org_name'))}")
    lines.append(f"Ombor: {_label(tenant.get('warehouse_name'))}")
    lines.append(f"Narx-ro'yxati: {_label(tenant.get('price_name'))}")

    size = catalog.size()
    if size:
        lines += ["", f"Katalogda: {size} ta mahsulot"]

    buttons = [("🔑 Kalitni almashtirish", "set:bito:kalit")]
    if key:
        buttons += [("🏢 Tashkilot", "set:bito:org"),
                    ("🏬 Ombor", "set:bito:ombor"),
                    ("💵 Narx-ro'yxati", "set:bito:narx"),
                    ("🔄 Aloqani tekshirish", "set:bito:test")]
    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML",
                     reply_markup=ui.buttons(buttons, row_width=1,
                                             back="menu:sozlamalar"))


def _choose(bot, chat_id, kind, items, title):
    if not items:
        bot.send_message(chat_id, "Bito'da variant topilmadi.")
        return
    bot.send_message(
        chat_id, title,
        reply_markup=ui.buttons(
            [(ui.escape(x.get("name") or "—"), f"set:bito:{kind}_{x['id']}")
             for x in items],
            row_width=1, back="set:bito"),
    )


# ---------------------------------------------------------------- xodimlar


ROLE_LABELS = {"owner": "egasi", "manager": "menejer", "staff": "xodim"}


def staff_panel(bot, chat_id, tg_id):
    users.require_role(tg_id, "manager")
    rows = users.listing()
    lines = [f"<b>Xodimlar</b> — {len(rows)} kishi", ""]
    for row in rows:
        salary = xodimlar.salary_of(row["tg_id"])
        shifts = xodimlar.shifts_of(row["tg_id"])
        marks = []
        if shifts:
            marks.append(f"{len(shifts)} kun jadval")
        if salary:
            marks.append("stavka bor")
        tail = f" ({', '.join(marks)})" if marks else " — sozlanmagan"
        lines.append(f"• {ui.escape(row['name'] or '—')} — "
                     f"{ROLE_LABELS.get(row['role'], row['role'])}{tail}")

    buttons = [(ui.escape(row["name"] or str(row["tg_id"])),
                f"set:xod:{row['tg_id']}") for row in rows]
    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML",
                     reply_markup=ui.buttons(buttons, row_width=1,
                                             back="menu:sozlamalar"))


def staff_card(bot, chat_id, tg_id, target):
    row = users.get(target)
    if not row:
        bot.send_message(chat_id, "Xodim topilmadi.")
        return
    salary = xodimlar.salary_of(target)
    shifts = xodimlar.shifts_of(target)

    lines = [f"<b>{ui.escape(row['name'] or '—')}</b>",
             f"Rol: {ROLE_LABELS.get(row['role'], row['role'])}", ""]
    if shifts:
        lines.append("Ish jadvali:")
        for shift in shifts:
            lines.append(f"  {xodimlar.WEEKDAYS[shift['weekday']]}: "
                         f"{shift['starts_at']}–{shift['ends_at']}")
    else:
        lines.append("Ish jadvali: <i>qo'yilmagan</i> — kechikish "
                     "hisoblanmaydi")
    if salary:
        if salary["per_day"]:
            lines.append(f"Stavka: {ui.money(salary['per_day'])} / kun")
        else:
            lines.append(f"Stavka: {ui.money(salary['base'])} / oy")
    else:
        lines.append("Stavka: <i>qo'yilmagan</i>")

    buttons = [("🕘 Jadval (haftalik)", f"set:xod:{target}:jadval"),
               ("💰 Oylik stavka", f"set:xod:{target}:oylik"),
               ("💵 Kunlik stavka", f"set:xod:{target}:kunlik"),
               ("🎖 Rolni o'zgartirish", f"set:xod:{target}:rol")]
    if row["role"] != "owner":
        buttons.append(("🚪 Ishdan bo'shatish", f"set:xod:{target}:bosh"))
    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML",
                     reply_markup=ui.buttons(buttons, row_width=1,
                                             back="set:xodimlar"))


# ------------------------------------------------------------------- ombor


def ombor_panel(bot, chat_id, tg_id):
    value = tenant.get("low_stock_default")
    lines = [
        "<b>Ombor</b>", "",
        f"Kam qolgan chegarasi: {_label(value, 'qo‘yilmagan')}",
        "",
        "Bito'da har mahsulotning qizil chizig'i bo'lsa — o'sha ishlatiladi. "
        "Bo'lmaganlar uchun shu umumiy chegara qo'llanadi.",
        "",
        "Qo'yilmasa faqat butunlay tugagan mahsulotlar ko'rsatiladi.",
    ]
    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML",
                     reply_markup=ui.buttons(
                         [("✏️ Chegarani qo'yish", "set:ombor:chegara"),
                          ("🗑 Chegarani olib tashlash", "set:ombor:ochir")],
                         row_width=1, back="menu:sozlamalar"))


# -------------------------------------------------------------------- hisob


def hisob(bot, chat_id, tg_id):
    users.require_role(tg_id, "owner")
    row = auth.account(ctx.require())
    lines = ["<b>Hisob</b>", ""]
    lines.append(f"Telefon (login): {_label(row['phone'] if row else None)}")
    lines.append("Parol: ●●●●●●●●")
    lines += ["", "Parolni unutsangiz sotuvchiga murojaat qiling — u yangi "
                  "parol beradi."]
    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML",
                     reply_markup=ui.buttons(
                         [("🔑 Parolni o'zgartirish", "set:hisob:parol")],
                         row_width=1, back="menu:sozlamalar"))


# ---------------------------------------------------------------- handlerlar


def register(bot, safe):
    """`safe` — handlers.py dagi xato ushlovchi dekorator."""

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("set:"))
    @safe
    def _click(call):
        ui.ack(bot, call)
        chat_id, tg_id = call.message.chat.id, call.from_user.id
        parts = call.data.split(":")
        section = parts[1] if len(parts) > 1 else ""

        if section == "dokon":
            _dokon_click(bot, chat_id, tg_id, parts)
        elif section == "bito":
            _bito_click(bot, chat_id, tg_id, parts)
        elif section == "xodimlar":
            staff_panel(bot, chat_id, tg_id)
        elif section == "xod":
            _staff_click(bot, chat_id, tg_id, parts)
        elif section == "ombor":
            _ombor_click(bot, chat_id, tg_id, parts)
        elif section == "hisob":
            if len(parts) == 2:
                hisob(bot, chat_id, tg_id)
            elif parts[2] == "parol":
                users.require_role(tg_id, "owner")
                sessions.set(tg_id, "set:hisob:parol", {})
                bot.send_message(
                    chat_id,
                    f"Yangi parolni yozing (kamida {auth.MIN_LENGTH} ta "
                    "belgi).\n\n⚠️ Yuborgach xabarni o'chirib tashlang.")

    @bot.message_handler(
        func=lambda m: (sessions.get_global(m.from_user.id)[0] or "")
        .startswith("set:"),
        content_types=["text", "location"])
    @safe
    def _input(message):
        state, data = sessions.get_global(message.from_user.id)
        sessions.clear(message.from_user.id)
        _apply(bot, message, state, data)


def _dokon_click(bot, chat_id, tg_id, parts):
    users.require_role(tg_id, "manager")
    if len(parts) == 2:
        dokon(bot, chat_id, tg_id)
        return
    field = parts[2]

    if field == "joy":
        sessions.set(tg_id, "set:dokon:joy", {})
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True,
                                       one_time_keyboard=True)
        kb.add(types.KeyboardButton("📍 Shu yer", request_location=True))
        bot.send_message(
            chat_id,
            "Do'konda turib joylashuvni yuboring. Xodimlar shu nuqtadan "
            "belgilangan radius ichida bo'lsagina davomat qayd etiladi.",
            reply_markup=kb)
        return

    if field == "joy_ochir":
        tenant.set("work_place", None)
        bot.send_message(chat_id, "Ish joyi o'chirildi. Davomatda joylashuv "
                                  "endi so'ralmaydi.")
        dokon(bot, chat_id, tg_id)
        return

    titles = {key: title for key, title, _ in DOKON_FIELDS}
    if field in titles:
        sessions.set(tg_id, f"set:dokon:{field}", {})
        bot.send_message(chat_id, f"{titles[field]} — yangi qiymatni yozing.")


def _bito_click(bot, chat_id, tg_id, parts):
    users.require_role(tg_id, "owner")
    if len(parts) == 2:
        bito_panel(bot, chat_id, tg_id)
        return
    action = parts[2]

    if action == "kalit":
        sessions.set(tg_id, "set:bito:kalit", {})
        bot.send_message(
            chat_id,
            "Yangi Bito API kalitini yuboring.\n"
            "Yuborgach xabaringizni o'chirib tashlang — kalit hisobingizga "
            "to'liq kirish beradi.")
        return

    if action == "test":
        client = bito.client()
        profile, _ = client.verify()
        name = profile.get("company_name") or profile.get("full_name") or "—"
        bot.send_message(chat_id, f"✅ Aloqa bor: {ui.escape(str(name))}",
                         parse_mode="HTML")
        return

    if action == "org":
        _choose(bot, chat_id, "org", bito.client().organizations(),
                "Tashkilotni tanlang:")
        return
    if action == "ombor":
        _choose(bot, chat_id, "ombor",
                bito.client().warehouses(
                    organization_id=tenant.get("bito_org_id")),
                "Omborni tanlang:")
        return
    if action == "narx":
        _choose(bot, chat_id, "narx", bito.client().prices(),
                "Narx-ro'yxatini tanlang:")
        return

    # Tanlov: set:bito:org_<id>
    if "_" in action:
        kind, value = action.split("_", 1)
        client = bito.client()
        if kind == "org":
            match = [x for x in client.organizations() if str(x["id"]) == value]
            if match:
                tenant.set("bito_org_id", match[0]["id"])
                tenant.set("bito_org_name", match[0].get("name"))
        elif kind == "ombor":
            match = [x for x in client.warehouses(
                organization_id=tenant.get("bito_org_id"))
                if str(x["id"]) == value]
            if match:
                tenant.set("warehouse_id", match[0]["id"])
                tenant.set("warehouse_name", match[0].get("name"))
        elif kind == "narx":
            match = [x for x in client.prices() if str(x["id"]) == value]
            if match:
                tenant.set("price_id", match[0]["id"])
                tenant.set("price_name", match[0].get("name"))
                if match[0].get("currency_id"):
                    tenant.set("currency_id", match[0]["currency_id"])
        bot.send_message(chat_id, "Saqlandi.")
        bito_panel(bot, chat_id, tg_id)


def _staff_click(bot, chat_id, tg_id, parts):
    users.require_role(tg_id, "manager")
    target = int(parts[2])
    action = parts[3] if len(parts) > 3 else None

    if action is None:
        staff_card(bot, chat_id, tg_id, target)
        return

    if action == "jadval":
        sessions.set(tg_id, f"set:xod:{target}:jadval", {})
        bot.send_message(
            chat_id,
            "Ish vaqtini yozing: <code>09:00 18:00</code>\n\n"
            "Dushanbadan shanbagacha shu vaqt qo'yiladi. Yakshanba dam olish.\n"
            "Boshqacha kerak bo'lsa keyin har kunni alohida o'zgartirasiz.",
            parse_mode="HTML")
    elif action in ("oylik", "kunlik"):
        sessions.set(tg_id, f"set:xod:{target}:{action}", {})
        unit = "oylik" if action == "oylik" else "bir kunlik"
        bot.send_message(chat_id, f"Xodimning {unit} stavkasini yozing "
                                  f"(faqat raqam).")
    elif action == "rol":
        bot.send_message(
            chat_id, "Yangi rolni tanlang:",
            reply_markup=ui.buttons(
                [("Xodim", f"set:xod:{target}:rol_staff"),
                 ("Menejer", f"set:xod:{target}:rol_manager")],
                row_width=1, back=f"set:xod:{target}"))
    elif action.startswith("rol_"):
        users.require_role(tg_id, "owner")
        role = action.split("_", 1)[1]
        users.upsert(target, role=role)
        bot.send_message(chat_id, f"Rol o'zgartirildi: {ROLE_LABELS[role]}")
        staff_card(bot, chat_id, tg_id, target)
    elif action == "bosh":
        users.require_role(tg_id, "owner")
        bot.send_message(
            chat_id,
            "Ishdan bo'shatilsa xodim botga kira olmaydi, lekin davomat va "
            "ish haqi tarixi saqlanadi.\n\nTasdiqlaysizmi?",
            reply_markup=ui.buttons(
                [("Ha, bo'shatilsin", f"set:xod:{target}:bosh_ha")],
                back=f"set:xod:{target}"))
    elif action == "bosh_ha":
        users.require_role(tg_id, "owner")
        db.run("UPDATE users SET active = 0 WHERE tenant_id = ? AND tg_id = ?",
               (ctx.require(), target))
        bot.send_message(chat_id, "Xodim ishdan bo'shatildi. Tarix saqlandi.")
        staff_panel(bot, chat_id, tg_id)


def _ombor_click(bot, chat_id, tg_id, parts):
    users.require_role(tg_id, "manager")
    if len(parts) == 2:
        ombor_panel(bot, chat_id, tg_id)
        return
    if parts[2] == "chegara":
        sessions.set(tg_id, "set:ombor:chegara", {})
        bot.send_message(chat_id, "Chegarani yozing (masalan 10). Qoldiq shu "
                                  "sondan kam bo'lsa ogohlantiriladi.")
    elif parts[2] == "ochir":
        tenant.set("low_stock_default", None)
        bot.send_message(chat_id, "Chegara olib tashlandi.")
        ombor_panel(bot, chat_id, tg_id)


# --------------------------------------------------------------- kiritishlar


def _number(text, name):
    try:
        return float(str(text).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        raise BotError(f"{name} — faqat raqam yozing.")


def _apply(bot, message, state, data):
    chat_id, tg_id = message.chat.id, message.from_user.id
    parts = state.split(":")
    section = parts[1]
    text = (message.text or "").strip()

    if section == "dokon":
        field = parts[2]
        if field == "joy":
            if not message.location:
                bot.send_message(chat_id, "Joylashuv yuborilmadi.")
                return
            tenant.set_json("work_place", {"lat": message.location.latitude,
                                           "lon": message.location.longitude})
            if not tenant.get("work_radius_m"):
                tenant.set("work_radius_m", 200)
            bot.send_message(chat_id, "Ish joyi belgilandi.",
                             reply_markup=types.ReplyKeyboardRemove())
            dokon(bot, chat_id, tg_id)
            return
        if field in ("tz_offset", "work_radius_m"):
            value = _number(text, "Bu maydon")
            tenant.set(field, int(value))
        else:
            if len(text) < 2:
                bot.send_message(chat_id, "Juda qisqa. Qaytadan yozing.")
                return
            tenant.set(field, text)
        bot.send_message(chat_id, "Saqlandi.")
        dokon(bot, chat_id, tg_id)
        return

    if section == "bito" and parts[2] == "kalit":
        probe = bito.Bito(api_key=text)
        profile, scheme = probe.verify()
        tenant.set("bito_api_key", text)
        tenant.set("bito_auth_scheme", scheme)
        name = profile.get("company_name") or profile.get("full_name") or ""
        bot.send_message(chat_id, f"✅ Ulandi: {ui.escape(str(name))}",
                         parse_mode="HTML")
        bito_panel(bot, chat_id, tg_id)
        return

    if section == "xod":
        target, action = int(parts[2]), parts[3]
        if action == "jadval":
            pieces = text.replace("-", " ").replace("—", " ").split()
            if len(pieces) != 2 or not all(
                    xodimlar._hhmm(piece) for piece in pieces):
                bot.send_message(
                    chat_id,
                    "Format: <code>09:00 18:00</code>\n"
                    "Ikkita vaqt, orasida bo'shliq.",
                    parse_mode="HTML")
                return
            xodimlar.set_week(target, pieces[0], pieces[1])
            bot.send_message(chat_id, "Ish jadvali qo'yildi "
                                      "(dushanba–shanba).")
        elif action == "oylik":
            xodimlar.set_salary(target, base=_number(text, "Stavka"))
            bot.send_message(chat_id, "Oylik stavka saqlandi.")
        elif action == "kunlik":
            xodimlar.set_salary(target, per_day=_number(text, "Stavka"))
            bot.send_message(chat_id, "Kunlik stavka saqlandi.")
        staff_card(bot, chat_id, tg_id, target)
        return

    if section == "hisob" and parts[2] == "parol":
        users.require_role(tg_id, "owner")
        auth.set_password(ctx.require(), text)
        bot.send_message(
            chat_id,
            "✅ Parol o'zgartirildi. Eski parol endi ishlamaydi.\n"
            "Bu xabarni ham o'chirib tashlang.")
        hisob(bot, chat_id, tg_id)
        return

    if section == "ombor" and parts[2] == "chegara":
        value = _number(text, "Chegara")
        if value <= 0:
            bot.send_message(chat_id, "Chegara noldan katta bo'lishi kerak.")
            return
        tenant.set("low_stock_default", int(value))
        bot.send_message(chat_id, "Chegara saqlandi. Keyingi skanerdan "
                                  "keyin kuchga kiradi.")
        ombor_panel(bot, chat_id, tg_id)
