"""Vazifalar moduli.

Oqim: menejer vazifa beradi → xodim bajaradi va hisobot yuboradi →
menejer tasdiqlaydi yoki qaytaradi.

Ballar `xodimlar` moduliga yoziladi — u yagona manba. Tasdiqlangan vazifa
ball beradi, muddati o'tgani ayiradi. Ikkinchi hisob yuritilmaydi.
"""

import datetime as dt
import logging

from . import base, registry, xodimlar
from .. import ctx, db, sessions, ui, users
from ..errors import BotError

log = logging.getLogger(__name__)

STATUS_LABELS = {
    "yangi": "🆕 yangi",
    "bajarilmoqda": "🔄 bajarilmoqda",
    "tekshiruvda": "👀 tekshiruvda",
    "bajarildi": "✅ bajarildi",
    "qaytarildi": "↩️ qaytarildi",
    "bekor": "🚫 bekor",
}

OPEN_STATUSES = ("yangi", "bajarilmoqda", "tekshiruvda", "qaytarildi")

LATE_PENALTY = 2          # muddati o'tgani uchun ayiriladigan ball


def now():
    return xodimlar.now_local()


def _parse_due(text):
    """«bugun 18:00», «ertaga», «3 kun», «2026-08-20 15:00» — hammasi.

    None qaytsa — muddat qo'yilmagan.
    """
    raw = (text or "").strip().lower()
    if not raw or raw in ("yo'q", "yoq", "-", "muddatsiz"):
        return None

    base_day = now().date()
    time_part = None
    for piece in raw.replace(",", " ").split():
        if ":" in piece:
            time_part = xodimlar._hhmm(piece)

    if raw.startswith("bugun"):
        day = base_day
    elif raw.startswith("ertaga"):
        day = base_day + dt.timedelta(days=1)
    elif "kun" in raw:
        digits = "".join(ch for ch in raw if ch.isdigit())
        if not digits:
            raise BotError("Muddatni tushunmadim. Masalan: «ertaga 18:00»")
        day = base_day + dt.timedelta(days=int(digits))
    else:
        head = raw.split()[0]
        try:
            day = dt.date.fromisoformat(head)
        except ValueError:
            if time_part:
                day = base_day
            else:
                raise BotError(
                    "Muddatni tushunmadim. Masalan: «bugun 18:00», "
                    "«ertaga», «3 kun» yoki «2026-08-20 15:00»")

    hour, minute = (18, 0)
    if time_part:
        hour, minute = (int(x) for x in time_part.split(":"))
    return dt.datetime.combine(day, dt.time(hour, minute)).isoformat(
        timespec="minutes")


def create(title, created_by, assigned_to=None, details=None, due=None,
           points=1, photo_id=None, repeat_rule=None):
    if len(str(title).strip()) < 3:
        raise BotError("Vazifa matni juda qisqa.")
    cur = db.run(
        "INSERT INTO task (tenant_id, title, details, photo_id, assigned_to, "
        "  created_by, due_at, points, repeat_rule) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ctx.require(), str(title).strip(), details, photo_id, assigned_to,
         created_by, due, int(points), repeat_rule),
    )
    return cur.lastrowid


def get(task_id):
    return db.row("SELECT * FROM task WHERE tenant_id = ? AND id = ?",
                  (ctx.require(), task_id))


def for_user(tg_id, only_open=True):
    sql = ("SELECT * FROM task WHERE tenant_id = ? "
           "AND (assigned_to = ? OR assigned_to IS NULL)")
    params = [ctx.require(), tg_id]
    if only_open:
        marks = ",".join("?" * len(OPEN_STATUSES))
        sql += f" AND status IN ({marks})"
        params += list(OPEN_STATUSES)
    sql += " ORDER BY due_at IS NULL, due_at, created_at"
    return db.rows(sql, tuple(params))


def pending_review():
    return db.rows(
        "SELECT * FROM task WHERE tenant_id = ? AND status = 'tekshiruvda' "
        "ORDER BY done_at",
        (ctx.require(),),
    )


def overdue():
    """Muddati o'tgan, hali yopilmagan vazifalar."""
    marks = ",".join("?" * len(OPEN_STATUSES))
    return db.rows(
        f"SELECT * FROM task WHERE tenant_id = ? AND due_at IS NOT NULL "
        f"AND due_at < ? AND late = 0 AND status IN ({marks})",
        (ctx.require(), now().isoformat(timespec="minutes"), *OPEN_STATUSES),
    )


def note(task_id, tg_id, text=None, photo_id=None, kind="izoh"):
    db.run(
        "INSERT INTO task_note (tenant_id, task_id, tg_id, kind, text, photo_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (ctx.require(), task_id, tg_id, kind, text, photo_id),
    )


def notes_of(task_id):
    return db.rows(
        "SELECT * FROM task_note WHERE tenant_id = ? AND task_id = ? "
        "ORDER BY created_at",
        (ctx.require(), task_id),
    )


def take(task_id, tg_id):
    task = get(task_id)
    if not task:
        raise BotError("Vazifa topilmadi.")
    if task["assigned_to"] is None:
        db.run("UPDATE task SET assigned_to = ?, status = 'bajarilmoqda' "
               "WHERE tenant_id = ? AND id = ?", (tg_id, ctx.require(), task_id))
    else:
        db.run("UPDATE task SET status = 'bajarilmoqda' "
               "WHERE tenant_id = ? AND id = ?", (ctx.require(), task_id))
    return get(task_id)


def report(task_id, tg_id, text=None, photo_id=None):
    """Xodim bajardim deydi — menejer tasdiqlashi kerak."""
    task = get(task_id)
    if not task:
        raise BotError("Vazifa topilmadi.")
    if task["status"] in ("bajarildi", "bekor"):
        raise BotError("Bu vazifa allaqachon yopilgan.")
    db.run(
        "UPDATE task SET status = 'tekshiruvda', done_at = ?, "
        "  assigned_to = COALESCE(assigned_to, ?) "
        "WHERE tenant_id = ? AND id = ?",
        (now().isoformat(timespec="minutes"), tg_id, ctx.require(), task_id),
    )
    note(task_id, tg_id, text=text, photo_id=photo_id, kind="hisobot")
    return get(task_id)


def approve(task_id, checked_by):
    """Menejer tasdiqlaydi — ball shu yerda beriladi."""
    task = get(task_id)
    if not task:
        raise BotError("Vazifa topilmadi.")
    if task["status"] == "bajarildi":
        raise BotError("Allaqachon tasdiqlangan.")

    db.run(
        "UPDATE task SET status = 'bajarildi', checked_by = ?, "
        "  done_at = COALESCE(done_at, ?) WHERE tenant_id = ? AND id = ?",
        (checked_by, now().isoformat(timespec="minutes"), ctx.require(),
         task_id),
    )
    worker = task["assigned_to"]
    if worker and task["points"]:
        xodimlar.add_points(worker, int(task["points"]),
                            f"Vazifa: {task['title'][:40]}",
                            source="vazifa", ref=str(task_id),
                            given_by=checked_by)
    return get(task_id)


def reject(task_id, checked_by, reason):
    task = get(task_id)
    if not task:
        raise BotError("Vazifa topilmadi.")
    db.run("UPDATE task SET status = 'qaytarildi', checked_by = ?, "
           "  done_at = NULL WHERE tenant_id = ? AND id = ?",
           (checked_by, ctx.require(), task_id))
    note(task_id, checked_by, text=reason, kind="qaytarish")
    return get(task_id)


def cancel(task_id):
    db.run("UPDATE task SET status = 'bekor' WHERE tenant_id = ? AND id = ?",
           (ctx.require(), task_id))


def mark_late(task_id):
    """Muddati o'tdi — ball ayiriladi, bir marta."""
    task = get(task_id)
    if not task or task["late"]:
        return None
    db.run("UPDATE task SET late = 1 WHERE tenant_id = ? AND id = ?",
           (ctx.require(), task_id))
    if task["assigned_to"]:
        xodimlar.add_points(task["assigned_to"], -LATE_PENALTY,
                            f"Muddati o'tdi: {task['title'][:40]}",
                            source="vazifa", ref=str(task_id))
    return task


def pending_for(tg_id):
    """Xodim ishga kelganda yetkaziladigan vazifalar.

    Vazifa xodim ish vaqtidan tashqarida berilgan bo'lsa, u xabarni
    ko'rmay qolishi mumkin. Kelganda qayta eslatiladi.
    """
    return db.rows(
        "SELECT * FROM task WHERE tenant_id = ? AND status IN ('yangi', "
        "  'qaytarildi') AND (assigned_to = ? OR assigned_to IS NULL) "
        "ORDER BY due_at IS NULL, due_at LIMIT 10",
        (ctx.require(), tg_id),
    )


def stats(tg_id=None, period=None):
    period = period or f"{xodimlar.today_local():%Y-%m}"
    where = "tenant_id = ? AND created_at LIKE ?"
    params = [ctx.require(), f"{period}-%"]
    if tg_id:
        where += " AND assigned_to = ?"
        params.append(tg_id)
    rows = db.rows(f"SELECT status, late FROM task WHERE {where}",
                   tuple(params))
    out = {"jami": len(rows), "bajarildi": 0, "ochiq": 0, "kechikkan": 0}
    for row in rows:
        if row["status"] == "bajarildi":
            out["bajarildi"] += 1
        elif row["status"] in OPEN_STATUSES:
            out["ochiq"] += 1
        if row["late"]:
            out["kechikkan"] += 1
    return out


def due_text(task):
    if not task["due_at"]:
        return "muddatsiz"
    when = dt.datetime.fromisoformat(task["due_at"])
    left = (when - now().replace(tzinfo=None)).total_seconds() / 3600
    stamp = f"{when:%d.%m %H:%M}"
    if task["status"] == "bajarildi":
        return stamp
    if left < 0:
        return f"{stamp} — ⏰ muddati o'tgan"
    if left < 24:
        return f"{stamp} — {int(left)} soat qoldi"
    return stamp


# -------------------------------------------------------------------- modul


@registry.implement("vazifalar")
class Vazifalar(base.Module):
    def menu(self, role):
        if role in ("owner", "manager"):
            return [("📋 Vazifalar", "mod:vazifalar:panel")]
        return [("📋 Vazifalarim", "mod:vazifalar:menikilar")]

    def register(self, bot, guard):
        _register(bot, guard)

    def jobs(self):
        return [("vazifa_muddat", lambda: check_overdue(), 900),
                ("vazifa_takror", lambda: spawn_recurring(), 900)]



# ------------------------------------------------- takrorlanuvchi vazifalar
#
# Qoidalar:
# - «bajarildi» → keyingi nusxa darhol ochiladi
# - muddati o'tib ketsa (bajarilmagan bo'lsa ham) → fon ishi keyingisini
#   ochadi: kundalik yumush «kecha qilinmadi» deb yo'qolmaydi, eski nusxa
#   esa ochiq qoladi — menejer qarzdorlikni ko'radi
# - «bekor» zanjirni TO'XTATADI — takrorni o'chirish yo'li shu
# - har vazifadan faqat bitta davomchi (parent_id bilan tekshiriladi),
#   shuning uchun approve + fon ishi ikkalasi chaqirsa ham nusxa bitta

REPEAT_STEP = {"kunlik": dt.timedelta(days=1),
               "haftalik": dt.timedelta(days=7)}


def _advance_due(due_iso, rule):
    """Keyingi muddat: davr qo'shib, kelajakka chiqquncha suriladi.

    Uch kun o'tkazib yuborilgan kunlik vazifa uchun UCHTA emas, BITTA
    nusxa ochiladi — muddati bugungi.
    """
    step = REPEAT_STEP[rule]
    try:
        due = dt.datetime.fromisoformat(due_iso)
    except (TypeError, ValueError):
        due = now().replace(hour=18, minute=0)
    due += step
    while due <= now():
        due += step
    return due.isoformat(timespec="minutes")


def spawn_next(task_id):
    """Takrorlanuvchi vazifaning keyingi nusxasini ochadi.

    Qaytadi: yangi id yoki None (takror emas / bekor / davomchi bor).
    """
    task = get(task_id)
    if not task or task["repeat_rule"] not in REPEAT_STEP:
        return None
    if task["status"] == "bekor":
        return None
    if db.value("SELECT id FROM task WHERE tenant_id = ? AND parent_id = ?",
                (ctx.require(), task_id)):
        return None

    due = _advance_due(task["due_at"], task["repeat_rule"])
    cur = db.run(
        "INSERT INTO task (tenant_id, title, details, photo_id, assigned_to, "
        "  created_by, due_at, points, repeat_rule, parent_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ctx.require(), task["title"], task["details"], task["photo_id"],
         task["assigned_to"], task["created_by"], due, task["points"],
         task["repeat_rule"], task_id),
    )
    return cur.lastrowid


def spawn_recurring():
    """Fon ishi: yopilgan yoki muddati o'tgan takrorlarga davomchi ochadi."""
    rows = db.rows(
        "SELECT id FROM task WHERE tenant_id = ? "
        "AND repeat_rule IS NOT NULL AND status != 'bekor' "
        "AND id NOT IN (SELECT parent_id FROM task WHERE tenant_id = ? "
        "               AND parent_id IS NOT NULL) "
        "AND (status = 'bajarildi' "
        "     OR (due_at IS NOT NULL AND due_at < ?))",
        (ctx.require(), ctx.require(),
         now().isoformat(timespec="minutes")),
    )
    return [sid for row in rows if (sid := spawn_next(row["id"]))]


def check_overdue(notify=None):
    """Muddati o'tganlarni belgilaydi. Fon ishi chaqiradi."""
    marked = []
    for task in overdue():
        row = mark_late(task["id"])
        if row:
            marked.append(row)
            if notify:
                try:
                    notify(row)
                except Exception:  # noqa: BLE001
                    log.warning("Muddat xabari ketmadi", exc_info=True)
    return marked


def _register(bot, guard):
    @bot.callback_query_handler(
        func=lambda c: (c.data or "").startswith("mod:vazifalar:"))
    @guard
    def _click(call):
        ui.ack(bot, call)
        action = call.data.split(":", 2)[2]
        chat_id, tg_id = call.message.chat.id, call.from_user.id

        if action == "panel":
            _panel(bot, chat_id, tg_id)
        elif action == "menikilar":
            _my_tasks(bot, chat_id, tg_id)
        elif action == "yangi":
            sessions.set(tg_id, "vaz:matn", {})
            bot.send_message(chat_id, "Vazifa matnini yozing.")
        elif action == "tekshiruv":
            _review_list(bot, chat_id, tg_id)
        elif action.startswith("kor_"):
            _card(bot, chat_id, tg_id, int(action.split("_")[1]))
        elif action.startswith("ol_"):
            task = take(int(action.split("_")[1]), tg_id)
            bot.send_message(chat_id, f"Qabul qildingiz: {ui.escape(task['title'])}",
                             parse_mode="HTML")
            _card(bot, chat_id, tg_id, task["id"])
        elif action.startswith("hisobot_"):
            task_id = int(action.split("_")[1])
            sessions.set(tg_id, "vaz:hisobot", {"task_id": task_id})
            bot.send_message(chat_id, "Bajarilgani haqida yozing yoki rasm "
                                      "yuboring.")
        elif action.startswith("takror_"):
            users.require_role(tg_id, "manager")
            _, task_id, rule = action.split("_", 2)
            task_id = int(task_id)
            if rule in REPEAT_STEP:
                task = get(task_id)
                if task and not task["due_at"]:
                    # Takror muddatsiz bo'lmaydi — standart: bugun 18:00
                    db.run("UPDATE task SET due_at = ? WHERE tenant_id = ? "
                           "AND id = ?",
                           (now().replace(hour=18, minute=0)
                            .isoformat(timespec="minutes"),
                            ctx.require(), task_id))
                db.run("UPDATE task SET repeat_rule = ? WHERE tenant_id = ? "
                       "AND id = ?", (rule, ctx.require(), task_id))
                bot.send_message(chat_id,
                                 "🔁 Har " + ("kuni" if rule == "kunlik"
                                              else "hafta")
                                 + " takrorlanadi. To'xtatish: vazifani "
                                   "bekor qilish.")
            _ask_assignee(bot, chat_id, task_id)
        elif action.startswith("tasdiq_"):
            task = approve(int(action.split("_")[1]), tg_id)
            bot.send_message(chat_id, f"✅ Tasdiqlandi. "
                                      f"{task['points']} ball berildi.")
            next_id = spawn_next(task["id"])
            if next_id:
                fresh = get(next_id)
                bot.send_message(chat_id,
                                 f"🔁 Keyingisi ochildi — muddat: "
                                 f"{due_text(fresh)}")
            if task["assigned_to"]:
                _tell(bot, task["assigned_to"],
                      f"✅ «{task['title']}» tasdiqlandi. "
                      f"+{task['points']} ball.")
            _review_list(bot, chat_id, tg_id)
        elif action.startswith("qaytar_"):
            task_id = int(action.split("_")[1])
            sessions.set(tg_id, "vaz:qaytar", {"task_id": task_id})
            bot.send_message(chat_id, "Nima uchun qaytarilyapti? Sababini "
                                      "yozing.")
        elif action.startswith("bekor_"):
            cancel(int(action.split("_")[1]))
            bot.send_message(chat_id, "Vazifa bekor qilindi.")
            _panel(bot, chat_id, tg_id)
        elif action.startswith("kim_"):
            _, task_id, target = action.split("_")
            db.run("UPDATE task SET assigned_to = ? WHERE tenant_id = ? "
                   "AND id = ?",
                   (None if target == "hamma" else int(target),
                    ctx.require(), int(task_id)))
            _finish_create(bot, chat_id, tg_id, int(task_id))

    @bot.message_handler(
        func=lambda m: (sessions.get_global(m.from_user.id)[0] or "")
        .startswith("vaz:"),
        content_types=["text", "photo"])
    @guard
    def _input(message):
        state, data = sessions.get_global(message.from_user.id)
        sessions.clear(message.from_user.id)
        _apply(bot, message, state, data)


def _tell(bot, tg_id, text):
    try:
        bot.send_message(tg_id, text)
    except Exception:  # noqa: BLE001
        log.warning("Xabar yetkazilmadi: %s", tg_id, exc_info=True)


def _apply(bot, message, state, data):
    chat_id, tg_id = message.chat.id, message.from_user.id
    text = (message.text or message.caption or "").strip()
    photo = message.photo[-1].file_id if message.content_type == "photo" else None

    if state == "vaz:matn":
        users.require_role(tg_id, "manager")
        task_id = create(text or "(matnsiz)", created_by=tg_id, photo_id=photo)
        sessions.set(tg_id, "vaz:muddat", {"task_id": task_id})
        bot.send_message(
            chat_id,
            "Muddat qachon? Masalan: <code>bugun 18:00</code>, "
            "<code>ertaga</code>, <code>3 kun</code>.\n"
            "Muddatsiz bo'lsa «yo'q» deb yozing.",
            parse_mode="HTML")
        return

    if state == "vaz:muddat":
        task_id = data["task_id"]
        due = _parse_due(text)
        db.run("UPDATE task SET due_at = ? WHERE tenant_id = ? AND id = ?",
               (due, ctx.require(), task_id))
        sessions.clear(tg_id)
        bot.send_message(
            chat_id, "Takrorlansinmi?",
            reply_markup=ui.buttons(
                [("Yo'q — bir martalik", f"mod:vazifalar:takror_{task_id}_yoq"),
                 ("🔁 Har kuni", f"mod:vazifalar:takror_{task_id}_kunlik"),
                 ("🔁 Har hafta", f"mod:vazifalar:takror_{task_id}_haftalik")],
                row_width=1))
        return

    if state == "vaz:hisobot":
        task = report(data["task_id"], tg_id, text=text or None, photo_id=photo)
        bot.send_message(chat_id, "Hisobot yuborildi, tasdiqlanishini kuting.")
        for manager in _managers():
            _tell(bot, manager,
                  f"👀 «{task['title']}» bajarildi deb belgilandi. "
                  f"Tekshiring: /menu → Vazifalar")
        return

    if state == "vaz:qaytar":
        users.require_role(tg_id, "manager")
        task = reject(data["task_id"], tg_id, text or "sabab ko'rsatilmagan")
        bot.send_message(chat_id, "Vazifa qaytarildi.")
        if task["assigned_to"]:
            _tell(bot, task["assigned_to"],
                  f"↩️ «{task['title']}» qaytarildi.\nSabab: {text}")


def _managers():
    return [row["tg_id"] for row in users.listing()
            if row["role"] in ("owner", "manager")]


def _finish_create(bot, chat_id, tg_id, task_id):
    task = get(task_id)
    target = "hamma"
    if task["assigned_to"]:
        row = users.get(task["assigned_to"])
        target = (row["name"] if row else str(task["assigned_to"]))
    bot.send_message(
        chat_id,
        f"✅ Vazifa berildi: <b>{ui.escape(task['title'])}</b>\n"
        f"Kimga: {ui.escape(target)}\nMuddat: {due_text(task)}",
        parse_mode="HTML", reply_markup=ui.main_menu(tg_id))

    receivers = ([task["assigned_to"]] if task["assigned_to"]
                 else [r["tg_id"] for r in users.listing()
                       if r["role"] == "staff"])
    for receiver in receivers:
        _tell(bot, receiver,
              f"📋 Yangi vazifa: {task['title']}\nMuddat: {due_text(task)}")


def _panel(bot, chat_id, tg_id):
    users.require_role(tg_id, "manager")
    review = pending_review()
    numbers = stats()
    lines = [
        "<b>Vazifalar</b>", "",
        f"Shu oy: {numbers['jami']} ta berilgan, "
        f"{numbers['bajarildi']} ta bajarilgan",
        f"Ochiq: {numbers['ochiq']} ta · Kechikkan: {numbers['kechikkan']} ta",
    ]
    if review:
        lines += ["", f"👀 Tekshirish kutilmoqda: {len(review)} ta"]

    buttons = [("➕ Yangi vazifa", "mod:vazifalar:yangi")]
    if review:
        buttons.append((f"👀 Tekshirish ({len(review)})",
                        "mod:vazifalar:tekshiruv"))
    buttons.append(("📋 Mening vazifalarim", "mod:vazifalar:menikilar"))
    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML",
                     reply_markup=ui.buttons(buttons, row_width=1,
                                             back="menu:root"))


def _my_tasks(bot, chat_id, tg_id):
    rows = for_user(tg_id)
    if not rows:
        bot.send_message(chat_id, "Ochiq vazifangiz yo'q. 👍",
                         reply_markup=ui.buttons([], back="menu:root"))
        return
    lines = [f"<b>Vazifalarim</b> — {len(rows)} ta", ""]
    buttons = []
    for task in rows:
        lines.append(f"{STATUS_LABELS[task['status']]} "
                     f"<b>{ui.escape(task['title'])}</b>\n"
                     f"    {due_text(task)}")
        buttons.append((task["title"][:40], f"mod:vazifalar:kor_{task['id']}"))
    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML",
                     reply_markup=ui.buttons(buttons, row_width=1,
                                             back="menu:root"))


def _ask_assignee(bot, chat_id, task_id):
    rows = users.listing()
    bot.send_message(
        chat_id, "Kimga beriladi?",
        reply_markup=ui.buttons(
            [("👥 Hammaga", f"mod:vazifalar:kim_{task_id}_hamma")]
            + [(ui.escape(r["name"] or "—"),
                f"mod:vazifalar:kim_{task_id}_{r['tg_id']}")
               for r in rows if r["role"] != "owner"],
            row_width=1))


def _card(bot, chat_id, tg_id, task_id):
    task = get(task_id)
    if not task:
        bot.send_message(chat_id, "Vazifa topilmadi.")
        return
    lines = [f"<b>{ui.escape(task['title'])}</b>"
             + (" 🔁" if task["repeat_rule"] else ""),
             f"Holat: {STATUS_LABELS[task['status']]}",
             f"Muddat: {due_text(task)}",
             f"Ball: {task['points']}"]
    if task["details"]:
        lines += ["", ui.escape(task["details"])]

    for entry in notes_of(task_id):
        who = users.get(entry["tg_id"])
        name = (who["name"] if who else "—")
        mark = {"hisobot": "📝", "qaytarish": "↩️"}.get(entry["kind"], "💬")
        lines.append(f"\n{mark} {ui.escape(name)}: "
                     f"{ui.escape(entry['text'] or '(rasm)')}")

    buttons = []
    is_manager = users.role_of(tg_id) in ("owner", "manager")
    if task["status"] in ("yangi", "qaytarildi"):
        buttons.append(("✋ Qabul qilaman", f"mod:vazifalar:ol_{task_id}"))
    if task["status"] in ("yangi", "bajarilmoqda", "qaytarildi"):
        buttons.append(("📝 Bajardim", f"mod:vazifalar:hisobot_{task_id}"))
    if is_manager and task["status"] == "tekshiruvda":
        buttons += [("✅ Tasdiqlash", f"mod:vazifalar:tasdiq_{task_id}"),
                    ("↩️ Qaytarish", f"mod:vazifalar:qaytar_{task_id}")]
    if is_manager and task["status"] not in ("bajarildi", "bekor"):
        buttons.append(("🚫 Bekor qilish", f"mod:vazifalar:bekor_{task_id}"))

    if task["photo_id"]:
        try:
            bot.send_photo(chat_id, task["photo_id"],
                           caption=ui.caption("\n".join(lines)),
                           parse_mode="HTML",
                           reply_markup=ui.buttons(buttons, row_width=1,
                                                   back="menu:root"))
            return
        except Exception:  # noqa: BLE001
            log.warning("Rasm yuborilmadi", exc_info=True)
    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML",
                     reply_markup=ui.buttons(buttons, row_width=1,
                                             back="menu:root"))


def _review_list(bot, chat_id, tg_id):
    users.require_role(tg_id, "manager")
    rows = pending_review()
    if not rows:
        bot.send_message(chat_id, "Tekshirish kutayotgan vazifa yo'q. 👍",
                         reply_markup=ui.buttons([], back="mod:vazifalar:panel"))
        return
    bot.send_message(
        chat_id, f"Tekshirish kutilmoqda — {len(rows)} ta:",
        reply_markup=ui.buttons(
            [(task["title"][:40], f"mod:vazifalar:kor_{task['id']}")
             for task in rows],
            row_width=1, back="mod:vazifalar:panel"))
