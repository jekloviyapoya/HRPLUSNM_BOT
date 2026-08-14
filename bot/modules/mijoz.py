"""Mijoz baholari: QR orqali baho, takliflar va shikoyatlar.

Mijoz QR kodni skanerlaydi → botga tushadi → yulduzcha qo'yadi →
xohlasa izoh yozadi. Past baho darrov egaga boradi.

Ikkita qoida:

- **Mijoz `users` jadvaliga yozilmaydi.** U tenant foydalanuvchisi emas —
  bir marta keladi va ketadi. Yozilsa, o'sha odam boshqa do'konda ishlay
  olmasdi.
- **Baho anonim.** Ism so'ralmaydi. Mijoz javob kutayotgan bo'lsa,
  telefonini o'zi qoldiradi.
"""

import io
import logging

from . import base, registry
from .. import ctx, db, sessions, tenant, ui, users

log = logging.getLogger(__name__)

# Shu balldan past baho darhol egaga yuboriladi
ALERT_BELOW = 3

STARS = {1: "😞", 2: "🙁", 3: "😐", 4: "🙂", 5: "😍"}
KIND_LABELS = {"baho": "Baho", "taklif": "Taklif", "shikoyat": "Shikoyat"}


# ------------------------------------------------------------------ yozuvlar


def add(tg_id=None, kind="baho", stars=None, text=None, photo_id=None,
        phone=None):
    cur = db.run(
        "INSERT INTO feedback (tenant_id, tg_id, kind, stars, text, "
        "  photo_id, phone) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ctx.require(), tg_id, kind, stars, text, photo_id, phone),
    )
    return cur.lastrowid


def get(feedback_id):
    return db.row("SELECT * FROM feedback WHERE tenant_id = ? AND id = ?",
                  (ctx.require(), feedback_id))


def update(feedback_id, **fields):
    if not fields:
        return get(feedback_id)
    sets = ", ".join(f"{key} = ?" for key in fields)
    db.run(f"UPDATE feedback SET {sets} WHERE tenant_id = ? AND id = ?",
           (*fields.values(), ctx.require(), feedback_id))
    return get(feedback_id)


def listing(status=None, kind=None, limit=30):
    sql = "SELECT * FROM feedback WHERE tenant_id = ?"
    params = [ctx.require()]
    if status:
        sql += " AND status = ?"
        params.append(status)
    if kind:
        sql += " AND kind = ?"
        params.append(kind)
    # id ham qo'shiladi: bir soniyada kelgan baholar tartibi
    # aniq bo'lsin (kassada navbat bo'lsa ular to'p-to'p keladi)
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(limit)
    return db.rows(sql, tuple(params))


def new_count():
    return db.value(
        "SELECT COUNT(*) FROM feedback WHERE tenant_id = ? AND status = 'yangi'",
        (ctx.require(),), default=0)


def stats(period=None):
    """O'rtacha baho va taqsimot."""
    sql = ("SELECT stars, COUNT(*) AS n FROM feedback "
           "WHERE tenant_id = ? AND stars IS NOT NULL")
    params = [ctx.require()]
    if period:
        sql += " AND created_at LIKE ?"
        params.append(f"{period}-%")
    sql += " GROUP BY stars"
    rows = db.rows(sql, tuple(params))

    spread = {star: 0 for star in range(1, 6)}
    total, weighted = 0, 0
    for row in rows:
        star = int(row["stars"])
        spread[star] = row["n"]
        total += row["n"]
        weighted += star * row["n"]
    return {
        "total": total,
        "average": (weighted / total) if total else None,
        "spread": spread,
        "low": spread[1] + spread[2],
    }


def qr_link(bot_username):
    return f"https://t.me/{bot_username}?start=baho_{ctx.require()}"


def qr_png(link):
    """QR kodni rasm sifatida qaytaradi. Kutubxona yo'q bo'lsa None."""
    try:
        import qrcode
    except ImportError:
        log.info("qrcode kutubxonasi yo'q — havola matn bilan beriladi")
        return None
    image = qrcode.make(link)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def summary_text(row):
    """Bitta baho — bir necha qator."""
    lines = []
    if row["stars"]:
        lines.append(f"{STARS.get(int(row['stars']), '')} "
                     f"{'⭐' * int(row['stars'])}")
    lines.append(KIND_LABELS.get(row["kind"], row["kind"]))
    if row["text"]:
        lines.append(ui.escape(row["text"]))
    if row["phone"]:
        lines.append(f"📞 {ui.escape(row['phone'])}")
    return "\n".join(lines)


# -------------------------------------------------------------------- modul


@registry.implement("mijoz")
class Mijoz(base.Module):
    def menu(self, role):
        if role == "staff":
            return []
        return [("⭐ Mijoz baholari", "mod:mijoz:panel")]

    def register(self, bot, guard):
        _register(bot, guard)


def _register(bot, guard):
    @bot.callback_query_handler(
        func=lambda c: (c.data or "").startswith("mod:mijoz:"))
    @guard
    def _click(call):
        ui.ack(bot, call)
        action = call.data.split(":", 2)[2]
        chat_id, tg_id = call.message.chat.id, call.from_user.id
        users.require_role(tg_id, "manager")

        if action == "panel":
            _panel(bot, chat_id, tg_id)
        elif action == "qr":
            _qr(bot, chat_id, tg_id)
        elif action == "yangi":
            _list(bot, chat_id, tg_id, status="yangi")
        elif action == "past":
            _list(bot, chat_id, tg_id, low_only=True)
        elif action == "hammasi":
            _list(bot, chat_id, tg_id)
        elif action.startswith("hal_"):
            update(int(action.split("_")[1]), status="hal_qilindi",
                   answered_by=tg_id)
            bot.send_message(chat_id, "Hal qilindi deb belgilandi.")
            _list(bot, chat_id, tg_id, status="yangi")


def _panel(bot, chat_id, tg_id):
    numbers = stats()
    lines = ["<b>Mijoz baholari</b>", ""]
    if numbers["total"]:
        lines.append(f"O'rtacha: <b>{numbers['average']:.1f}</b> / 5 "
                     f"({numbers['total']} ta baho)")
        for star in range(5, 0, -1):
            count = numbers["spread"][star]
            if count:
                bar = "█" * min(20, round(count / numbers["total"] * 20))
                lines.append(f"{star}⭐ {bar} {count}")
    else:
        lines.append("Hali baho yo'q. QR kodni kassaga qo'ying.")

    pending = new_count()
    if pending:
        lines += ["", f"🔔 Ko'rilmagan: {pending} ta"]

    buttons = [("🔳 QR kod", "mod:mijoz:qr")]
    if pending:
        buttons.append((f"🔔 Yangilar ({pending})", "mod:mijoz:yangi"))
    if numbers["low"]:
        buttons.append((f"😞 Past baholar ({numbers['low']})",
                        "mod:mijoz:past"))
    if numbers["total"]:
        buttons.append(("📋 Hammasi", "mod:mijoz:hammasi"))
    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML",
                     reply_markup=ui.buttons(buttons, row_width=1,
                                             back="menu:root"))


def _qr(bot, chat_id, tg_id):
    try:
        username = bot.get_me().username
    except Exception:  # noqa: BLE001
        username = "bot"
    link = qr_link(username)
    caption = (f"Mijozlar shu QR kodni skanerlab baho qoldiradi.\n\n"
               f"Kassaga, stolga yoki chekka qo'ying.\n\n{link}")
    image = qr_png(link)
    if image:
        bot.send_photo(chat_id, image, caption=ui.caption(caption))
    else:
        bot.send_message(chat_id, caption)
    bot.send_message(chat_id, "—",
                     reply_markup=ui.buttons([], back="mod:mijoz:panel"))


def _list(bot, chat_id, tg_id, status=None, low_only=False):
    rows = listing(status=status)
    if low_only:
        rows = [row for row in rows
                if row["stars"] and int(row["stars"]) < ALERT_BELOW]
    if not rows:
        bot.send_message(chat_id, "Ro'yxat bo'sh. 👍",
                         reply_markup=ui.buttons([], back="mod:mijoz:panel"))
        return

    for row in rows[:15]:
        text = summary_text(row) + f"\n<i>{row['created_at']}</i>"
        buttons = []
        if row["status"] != "hal_qilindi":
            buttons.append(("✅ Hal qilindi", f"mod:mijoz:hal_{row['id']}"))
        if row["photo_id"]:
            try:
                bot.send_photo(chat_id, row["photo_id"],
                               caption=ui.caption(text), parse_mode="HTML",
                               reply_markup=ui.buttons(buttons)
                               if buttons else None)
                continue
            except Exception:  # noqa: BLE001
                log.warning("Baho rasmi yuborilmadi", exc_info=True)
        bot.send_message(chat_id, text, parse_mode="HTML",
                         reply_markup=ui.buttons(buttons) if buttons else None)

    if status == "yangi":
        for row in rows:
            if row["status"] == "yangi":
                update(row["id"], status="korildi")
    bot.send_message(chat_id, "—",
                     reply_markup=ui.buttons([], back="mod:mijoz:panel"))
