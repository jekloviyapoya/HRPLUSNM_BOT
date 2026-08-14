"""Marketing moduli: aksiya posti, AI matn, AI poster, kanalga yuborish.

Oqim: mahsulot tanlash → narxlar → AI matn yozadi → rasm (ixtiyoriy) →
kanalga yuborish.

Ikkita saboq market-bot'dan:

- **Bito'da fayl yuklab olish endpointi yo'q.** Mahsulot kartochkasidagi
  rasmni tashqaridan olib bo'lmaydi. Shuning uchun rasm foydalanuvchidan
  so'raladi, avval behuda qidirilmaydi.
- **Holat qo'shib yoziladi, to'liq almashtirilmaydi.** Aks holda oldin
  kiritilgan narxlar yo'qoladi va matn eski `{NARX}` yo'liga tushib
  qoladi (2026-08-08 xatosi).
"""

import logging

from . import base, registry
from .. import ai, catalog, ctx, db, imagen, sessions, tenant, ui, users
from ..errors import BotError

log = logging.getLogger(__name__)

MAX_SEARCH = 8

# Chegirma bo'lmasa post «aksiya» emas — oddiy e'lon. Aks holda mijoz
# chegirma kutadi va narxni ko'rib xafa bo'ladi.
TEXT_PROMPT = """Do'kon uchun Telegram kanaliga {kind} yoz.

Mahsulot: {name}
{price_line}
Do'kon: {shop}

Qoidalar:
- O'zbek tilida, lotin alifbosida
- 3–5 qator, qisqa va jonli
- Boshida diqqatni tortadigan bir qator
- Narx aytilgan bo'lsa uni aniq ko'rsat
- {tone}
- Oxirida qisqa chaqiriq
- Emoji ishlat, lekin 4 tadan ko'p emas
- Markdown yoki ** ishlatma, oddiy matn
- Faqat post matnini qaytar, boshqa hech narsa yozma"""


# ------------------------------------------------------------------ yozuvlar


def create(tg_id):
    cur = db.run("INSERT INTO promo (tenant_id, tg_id) VALUES (?, ?)",
                 (ctx.require(), tg_id))
    return cur.lastrowid


def get(promo_id):
    return db.row("SELECT * FROM promo WHERE tenant_id = ? AND id = ?",
                  (ctx.require(), promo_id))


def update(promo_id, **fields):
    """Faqat berilgan maydonlar yangilanadi.

    To'liq qayta yozish narxlarni o'chirib yuborardi — shuning uchun
    har doim qisman.
    """
    if not fields:
        return get(promo_id)
    sets = ", ".join(f"{key} = ?" for key in fields)
    db.run(f"UPDATE promo SET {sets} WHERE tenant_id = ? AND id = ?",
           (*fields.values(), ctx.require(), promo_id))
    return get(promo_id)


def last_draft(tg_id):
    return db.row(
        "SELECT * FROM promo WHERE tenant_id = ? AND tg_id = ? "
        "AND status IN ('tuzilmoqda', 'tayyor') ORDER BY created_at DESC "
        "LIMIT 1",
        (ctx.require(), tg_id),
    )


def sent_count():
    return db.value(
        "SELECT COUNT(*) FROM promo WHERE tenant_id = ? AND status = 'yuborildi'",
        (ctx.require(),), default=0)


# --------------------------------------------------------------------- matn


def price_line(old, new):
    if old and new:
        return f"Eski narx: {old:,.0f}, yangi narx: {new:,.0f}".replace(",", " ")
    if new:
        return f"Narx: {new:,.0f}".replace(",", " ")
    return "Narx aytilmagan"


def compose(name, old=None, new=None, session=None):
    """AI post matnini yozadi. Xato bo'lsa oddiy zaxira matn."""
    sale = bool(old and new and new < old)
    prompt = TEXT_PROMPT.format(
        name=name, shop=tenant.shop_name(), price_line=price_line(old, new),
        kind="aksiya posti" if sale else "oddiy mahsulot posti",
        tone=("Chegirmani ta'kidla" if sale else
              "Chegirma YO'Q — «aksiya», «chegirma», «arzon» kabi so'zlarni "
              "ISHLATMA, shunchaki mahsulot va narxini e'lon qil"))
    try:
        text, _ = ai.ask([{"type": "text", "text": prompt}], max_tokens=600,
                         session=session)
        cleaned = (text or "").strip().strip("`")
        if len(cleaned) > 10:
            return cleaned
    except BotError:
        log.warning("Post matni yozilmadi", exc_info=True)
    return fallback_text(name, old, new)


def fallback_text(name, old=None, new=None):
    """AI ishlamasa ham post chiqsin.

    Chegirmasiz postda «aksiya» belgisi ishlatilmaydi — mijoz chegirma
    kutib qolmasin.
    """
    sale = bool(old and new and new < old)
    lines = [f"{'🔥' if sale else '🆕'} {name}"]
    if sale:
        lines.append(f"{old:,.0f} so'm o'rniga {new:,.0f} so'm"
                     .replace(",", " "))
    elif new:
        lines.append(f"Narxi: {new:,.0f} so'm".replace(",", " "))
    lines.append(f"{tenant.shop_name()} — kutamiz!")
    return "\n".join(lines)


def discount_percent(old, new):
    if not old or not new or old <= 0 or new >= old:
        return None
    return round((old - new) / old * 100)


# -------------------------------------------------------------------- modul


@registry.implement("marketing")
class Marketing(base.Module):
    def menu(self, role):
        if role == "staff":
            return []
        return [("📣 Marketing", "mod:marketing:panel")]

    def register(self, bot, guard):
        _register(bot, guard)


def _register(bot, guard):
    @bot.callback_query_handler(
        func=lambda c: (c.data or "").startswith("mod:marketing:"))
    @guard
    def _click(call):
        ui.ack(bot, call)
        action = call.data.split(":", 2)[2]
        chat_id, tg_id = call.message.chat.id, call.from_user.id
        users.require_role(tg_id, "manager")

        if action == "panel":
            _panel(bot, chat_id, tg_id)
        elif action == "yangi":
            promo_id = create(tg_id)
            sessions.set(tg_id, "promo:mahsulot", {"promo_id": promo_id})
            bot.send_message(
                chat_id,
                "Mahsulot nomini yozing.\n"
                "Katalogdan qidiraman — topilmasa nomini o'zim ishlataman.")
        elif action.startswith("tovar_"):
            _, promo_id, product_id = action.split("_", 2)
            _pick_product(bot, chat_id, tg_id, int(promo_id), product_id)
        elif action.startswith("narx_"):
            promo_id = int(action.split("_")[1])
            sessions.set(tg_id, "promo:narx", {"promo_id": promo_id})
            bot.send_message(
                chat_id,
                "Narxlarni yozing: <code>12000 9000</code> "
                "(eski va yangi).\nFaqat bitta son yozsangiz — joriy narx.\n"
                "Narxsiz post uchun «yo'q» deb yozing.",
                parse_mode="HTML")
        elif action.startswith("tahrir_"):
            promo_id = int(action.split("_")[1])
            sessions.set(tg_id, "promo:tahrir", {"promo_id": promo_id})
            bot.send_message(chat_id, "Yangi matnni yozing.")
        elif action.startswith("matn_"):
            _write_text(bot, chat_id, tg_id, int(action.split("_")[1]))
        elif action.startswith("qayta_"):
            _write_text(bot, chat_id, tg_id, int(action.split("_")[1]))
        elif action.startswith("rasm_"):
            promo_id = int(action.split("_")[1])
            sessions.set(tg_id, "promo:rasm", {"promo_id": promo_id})
            bot.send_message(chat_id, "Mahsulot rasmini yuboring.")
        elif action.startswith("poster_"):
            _make_poster(bot, chat_id, tg_id, int(action.split("_")[1]))
        elif action.startswith("korish_"):
            _preview(bot, chat_id, tg_id, int(action.split("_")[1]))
        elif action.startswith("yubor_"):
            _send(bot, chat_id, tg_id, int(action.split("_")[1]))
        elif action.startswith("bekor_"):
            update(int(action.split("_")[1]), status="bekor")
            bot.send_message(chat_id, "Post bekor qilindi.",
                             reply_markup=ui.main_menu(tg_id))
        elif action == "kanal":
            sessions.set(tg_id, "promo:kanal", {})
            bot.send_message(
                chat_id,
                "Kanal manzilini yozing: <code>@kanalim</code>\n\n"
                "Botni kanalga administrator qilib qo'shing — aks holda "
                "post yubora olmaydi.",
                parse_mode="HTML")

    @bot.message_handler(
        func=lambda m: (sessions.get_global(m.from_user.id)[0] or "")
        .startswith("promo:"),
        content_types=["text", "photo"])
    @guard
    def _input(message):
        state, data = sessions.get_global(message.from_user.id)
        sessions.clear(message.from_user.id)
        _apply(bot, message, state, data)


def _apply(bot, message, state, data):
    chat_id, tg_id = message.chat.id, message.from_user.id
    text = (message.text or message.caption or "").strip()

    if state == "promo:kanal":
        handle = text if text.startswith("@") else f"@{text.lstrip('@')}"
        tenant.set("channel_id", handle)
        bot.send_message(chat_id, f"Kanal saqlandi: {ui.escape(handle)}",
                         parse_mode="HTML")
        _panel(bot, chat_id, tg_id)
        return

    promo_id = data.get("promo_id")
    if not promo_id or not get(promo_id):
        bot.send_message(chat_id, "Post topilmadi, qaytadan boshlang.")
        return

    if state == "promo:mahsulot":
        rows = db.rows(
            "SELECT product_id, name FROM catalog WHERE tenant_id = ? "
            "AND key LIKE ? LIMIT ?",
            (ctx.require(), f"%{catalog.normalize(text)}%", MAX_SEARCH))
        if not rows:
            update(promo_id, product_name=text)
            bot.send_message(chat_id, f"Katalogda topilmadi — «{ui.escape(text)}» "
                                      "nomi bilan davom etamiz.",
                             parse_mode="HTML")
            _ask_price(bot, chat_id, promo_id)
            return
        if len(rows) == 1:
            _pick_product(bot, chat_id, tg_id, promo_id, rows[0]["product_id"])
            return
        bot.send_message(
            chat_id, "Qaysi mahsulot?",
            reply_markup=ui.buttons(
                [(row["name"][:45],
                  f"mod:marketing:tovar_{promo_id}_{row['product_id']}")
                 for row in rows], row_width=1))
        return

    if state == "promo:narx":
        if text.lower() in ("yo'q", "yoq", "-"):
            _write_text(bot, chat_id, tg_id, promo_id)
            return
        numbers = []
        for piece in text.replace(",", " ").split():
            digits = "".join(ch for ch in piece if ch.isdigit())
            if digits:
                numbers.append(float(digits))
        if not numbers:
            bot.send_message(chat_id, "Narxni tushunmadim. Masalan: 12000 9000")
            return
        if len(numbers) >= 2:
            update(promo_id, old_price=max(numbers[:2]),
                   new_price=min(numbers[:2]))
        else:
            update(promo_id, new_price=numbers[0])
        _write_text(bot, chat_id, tg_id, promo_id)
        return

    if state == "promo:rasm":
        if message.content_type != "photo":
            bot.send_message(chat_id, "Rasm yuborilmadi.")
            return
        update(promo_id, photo_id=message.photo[-1].file_id)
        bot.send_message(chat_id, "Rasm saqlandi.")
        _preview(bot, chat_id, tg_id, promo_id)
        return

    if state == "promo:tahrir":
        update(promo_id, post_text=text)
        bot.send_message(chat_id, "Matn yangilandi.")
        _preview(bot, chat_id, tg_id, promo_id)


def _pick_product(bot, chat_id, tg_id, promo_id, product_id):
    row = db.row("SELECT name FROM catalog WHERE tenant_id = ? "
                 "AND product_id = ?", (ctx.require(), product_id))
    update(promo_id, product_id=product_id,
           product_name=row["name"] if row else None)
    _ask_price(bot, chat_id, promo_id)


def _ask_price(bot, chat_id, promo_id):
    bot.send_message(
        chat_id,
        "Narxlarni yozing: <code>12000 9000</code> (eski va yangi).\n"
        "Faqat bitta son yozsangiz — joriy narx.\n"
        "Narxsiz post uchun «yo'q» deb yozing.",
        parse_mode="HTML")
    # Sessiya `_apply` dan chaqirilganda o'chirilgan — qayta qo'yamiz
    row = get(promo_id)
    sessions.set(row["tg_id"], "promo:narx", {"promo_id": promo_id})


def _write_text(bot, chat_id, tg_id, promo_id):
    row = get(promo_id)
    note = bot.send_message(chat_id, "Matn yozilmoqda…")
    text = compose(row["product_name"] or "Mahsulot",
                   row["old_price"], row["new_price"])
    update(promo_id, post_text=text)
    try:
        bot.delete_message(chat_id, note.message_id)
    except Exception:  # noqa: BLE001
        pass
    _preview(bot, chat_id, tg_id, promo_id)


def _make_poster(bot, chat_id, tg_id, promo_id):
    row = get(promo_id)
    if not row["photo_id"]:
        bot.send_message(chat_id, "Avval mahsulot rasmini yuboring.")
        return
    note = bot.send_message(chat_id, "Poster yasalmoqda… 30–60 soniya.")
    try:
        info = bot.get_file(row["photo_id"])
        data = bot.download_file(info.file_path)
        poster = imagen.make_poster(data)
        sent = bot.send_photo(chat_id, poster, caption="Poster tayyor.")
        file_id = sent.photo[-1].file_id
        update(promo_id, poster_id=file_id)
    finally:
        try:
            bot.delete_message(chat_id, note.message_id)
        except Exception:  # noqa: BLE001
            pass
    _preview(bot, chat_id, tg_id, promo_id)


def _preview(bot, chat_id, tg_id, promo_id):
    row = get(promo_id)
    text = row["post_text"] or "(matn yo'q)"
    percent = discount_percent(row["old_price"], row["new_price"])

    head = []
    if row["product_name"]:
        head.append(f"Mahsulot: {ui.escape(row['product_name'])}")
    if percent:
        head.append(f"Chegirma: {percent}%")
    if head:
        bot.send_message(chat_id, "\n".join(head), parse_mode="HTML")

    image = row["poster_id"] or row["photo_id"]
    if image:
        bot.send_photo(chat_id, image, caption=ui.caption(text))
    else:
        bot.send_message(chat_id, text)

    buttons = [("✏️ Matnni tahrirlash", f"mod:marketing:tahrir_{promo_id}"),
               ("🔄 Matnni qayta yozdirish", f"mod:marketing:qayta_{promo_id}")]
    if not row["photo_id"]:
        buttons.append(("🖼 Rasm qo'shish", f"mod:marketing:rasm_{promo_id}"))
    elif imagen.enabled() and not row["poster_id"]:
        buttons.append(("✨ AI poster yasash", f"mod:marketing:poster_{promo_id}"))
    if tenant.get("channel_id"):
        buttons.append(("📤 Kanalga yuborish", f"mod:marketing:yubor_{promo_id}"))
    else:
        buttons.append(("📡 Kanalni ulash", "mod:marketing:kanal"))
    buttons.append(("🗑 Bekor qilish", f"mod:marketing:bekor_{promo_id}"))

    bot.send_message(chat_id, "Post tayyormi?",
                     reply_markup=ui.buttons(buttons, row_width=1,
                                             back="mod:marketing:panel"))


def _send(bot, chat_id, tg_id, promo_id):
    row = get(promo_id)
    channel = tenant.get("channel_id")
    if not channel:
        bot.send_message(chat_id, "Kanal ulanmagan.")
        return

    image = row["poster_id"] or row["photo_id"]
    try:
        if image:
            sent = bot.send_photo(channel, image,
                                  caption=ui.caption(row["post_text"] or ""))
        else:
            sent = bot.send_message(channel, row["post_text"] or "")
    except Exception as e:  # noqa: BLE001
        log.warning("Kanalga yuborilmadi: %s", e)
        bot.send_message(
            chat_id,
            "⚠️ Kanalga yuborib bo'lmadi. Bot kanalga administrator qilib "
            "qo'shilganini tekshiring.")
        return

    update(promo_id, status="yuborildi", channel_id=str(channel),
           message_id=getattr(sent, "message_id", None),
           sent_at=_now())
    bot.send_message(chat_id, f"✅ Kanalga yuborildi: {ui.escape(channel)}",
                     parse_mode="HTML", reply_markup=ui.main_menu(tg_id))


def _now():
    import datetime as dt
    return dt.datetime.now().isoformat(timespec="seconds")


def _panel(bot, chat_id, tg_id):
    channel = tenant.get("channel_id")
    draft = last_draft(tg_id)
    lines = ["<b>Marketing</b>", ""]
    lines.append(f"Kanal: {ui.escape(channel) if channel else '<i>ulanmagan</i>'}")
    lines.append(f"Yuborilgan postlar: {sent_count()} ta")
    if not ai.enabled():
        lines.append("\n⚠️ AI kaliti yo'q — matn qo'lda yoziladi.")
    if not imagen.enabled():
        lines.append("ℹ️ Poster kaliti yo'q — o'z rasmingizni ishlatasiz.")

    buttons = [("➕ Yangi post", "mod:marketing:yangi")]
    if draft:
        buttons.insert(0, ("📝 Tugallanmagan post",
                           f"mod:marketing:korish_{draft['id']}"))
    buttons.append(("📡 Kanalni o'zgartirish", "mod:marketing:kanal"))
    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML",
                     reply_markup=ui.buttons(buttons, row_width=1,
                                             back="menu:root"))
