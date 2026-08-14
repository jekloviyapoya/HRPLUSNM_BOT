"""Xodimlar moduli: davomat, ballar, ish haqi, jadval.

Bito talab qilmaydi — mijoz Bito ulanmasdan ham darrov foyda ko'radi.

Vaqt bo'yicha eslatma: hamma sana va vaqt **mahalliy** (tenant TZ) bo'yicha.
UTC ishlatilsa, kechqurun 23:00 da kelgan xodim ertangi kunga yozilib qoladi.
"""

import datetime as dt
import logging
import math

from . import base, registry
from .. import ctx, db, sessions, tenant, ui, users
from ..errors import BotError

log = logging.getLogger(__name__)

WEEKDAYS = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba",
            "Juma", "Shanba", "Yakshanba"]

# Kechikish shu daqiqadan oshsa — 'kechikdi'
LATE_TOLERANCE = 5

# Ish joyidan shu masofagacha (metr) kelish qabul qilinadi
DEFAULT_RADIUS_M = 200


# --------------------------------------------------------------- yordamchilar


def _tz_offset():
    """Tenant vaqt mintaqasi (soatlarda). Standart: Toshkent."""
    raw = tenant.get("tz_offset")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 5


def now_local():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=_tz_offset())))


def today_local():
    return now_local().date()


def _hhmm(value):
    """'9:5' , '09:05', '9.05' -> '09:05' yoki None."""
    text = str(value or "").strip().replace(".", ":").replace("-", ":")
    if ":" not in text:
        if text.isdigit() and len(text) in (3, 4):
            text = text[:-2] + ":" + text[-2:]
        else:
            return None
    head, _, tail = text.partition(":")
    if not (head.isdigit() and tail.isdigit()):
        return None
    hour, minute = int(head), int(tail)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f"{hour:02d}:{minute:02d}"


def _minutes(hhmm):
    hour, minute = hhmm.split(":")
    return int(hour) * 60 + int(minute)


def distance_m(lat1, lon1, lat2, lon2):
    """Ikki nuqta orasidagi masofa, metr (haversine)."""
    radius = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ------------------------------------------------------------------- jadval


def set_shift(tg_id, weekday, starts_at, ends_at):
    start, end = _hhmm(starts_at), _hhmm(ends_at)
    if not start or not end:
        raise BotError("Vaqt formati: 09:00")
    if _minutes(end) <= _minutes(start):
        raise BotError("Tugash vaqti boshlanishdan keyin bo'lishi kerak.")
    db.run(
        "UPDATE shift SET active = 0 "
        "WHERE tenant_id = ? AND tg_id = ? AND weekday = ?",
        (ctx.require(), tg_id, weekday),
    )
    db.run(
        "INSERT INTO shift (tenant_id, tg_id, weekday, starts_at, ends_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (ctx.require(), tg_id, weekday, start, end),
    )
    return start, end


def shift_for(tg_id, weekday):
    return db.row(
        "SELECT * FROM shift WHERE tenant_id = ? AND tg_id = ? "
        "AND weekday = ? AND active = 1",
        (ctx.require(), tg_id, weekday),
    )


def shifts_of(tg_id):
    return db.rows(
        "SELECT * FROM shift WHERE tenant_id = ? AND tg_id = ? AND active = 1 "
        "ORDER BY weekday",
        (ctx.require(), tg_id),
    )


def set_week(tg_id, starts_at, ends_at, days=range(6)):
    """Bir xil vaqtni bir necha kunga qo'yadi (standart: dush–shanba)."""
    out = []
    for weekday in days:
        out.append((weekday,) + set_shift(tg_id, weekday, starts_at, ends_at))
    return out


# ------------------------------------------------------------------ davomat


def record_of(tg_id, work_date=None):
    return db.row(
        "SELECT * FROM attendance WHERE tenant_id = ? AND tg_id = ? "
        "AND work_date = ?",
        (ctx.require(), tg_id, str(work_date or today_local())),
    )


def check_in(tg_id, lat=None, lon=None):
    """Kelishni qayd qiladi. Qaytadi: (yozuv, xabar_matni)."""
    now = now_local()
    work_date = str(now.date())
    if record_of(tg_id, work_date):
        raise BotError("Bugun allaqachon kelganingizni qayd qilgansiz.")

    distance = None
    if lat is not None and lon is not None:
        place = tenant.get_json("work_place")
        if place:
            distance = int(distance_m(lat, lon, place["lat"], place["lon"]))
            radius = int(tenant.get("work_radius_m") or DEFAULT_RADIUS_M)
            if distance > radius:
                raise BotError(
                    f"Siz ish joyidan {distance} m uzoqdasiz "
                    f"(ruxsat: {radius} m). Ish joyiga yetib kelib qayta urining."
                )

    shift = shift_for(tg_id, now.weekday())
    late = 0
    status = "keldi"
    if shift:
        late = max(0, _minutes(now.strftime("%H:%M")) - _minutes(shift["starts_at"]))
        if late > LATE_TOLERANCE:
            status = "kechikdi"
        else:
            late = 0

    db.run(
        "INSERT INTO attendance (tenant_id, tg_id, work_date, came_at, "
        "  late_minutes, status, came_lat, came_lon, distance_m) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ctx.require(), tg_id, work_date, now.isoformat(timespec="seconds"),
         late, status, lat, lon, distance),
    )

    if status == "kechikdi":
        add_points(tg_id, -1, f"{late} daqiqa kechikish", source="davomat")
        message = f"Qayd etildi: {now:%H:%M} — {late} daqiqa kechikdingiz."
    elif shift:
        add_points(tg_id, 1, "O'z vaqtida keldi", source="davomat")
        message = f"Qayd etildi: {now:%H:%M} — o'z vaqtida."
    else:
        message = f"Qayd etildi: {now:%H:%M}. (Bugunga jadval qo'yilmagan.)"

    if distance is not None:
        message += f"\nIsh joyidan {distance} m."
    return record_of(tg_id, work_date), message


def at_work(tg_id):
    """Xodim AYNI PAYTDA ishdami?

    ⚠️ «ketish qayd etilmagan» tekshiruvining o'zi YETARLI EMAS: xodim bir
    kun «Ketdim» bosishni unutgan bo'lsa, o'sha eski yozuv uni abadiy
    «ishda» ko'rsatardi. Shuning uchun FAQAT oxirgi yozuv olinadi va u
    BUGUNGI bo'lishi ham shart.
    """
    row = db.row(
        "SELECT work_date, came_at, left_at FROM attendance "
        "WHERE tenant_id = ? AND tg_id = ? ORDER BY work_date DESC LIMIT 1",
        (ctx.require(), tg_id),
    )
    if not row or not row["came_at"]:
        return False
    return not row["left_at"] and str(row["work_date"]) == str(today_local())


def close_stale(before=None):
    """Unutilgan ketishlarni yopadi: eski ochiq yozuv qolib ketmasin.

    Ish vaqti oxiri bo'yicha yopiladi, jadval yo'q bo'lsa umuman
    yopilmaydi — soxta ish soati yozilmasin.
    """
    before = str(before or today_local())
    rows = db.rows(
        "SELECT * FROM attendance WHERE tenant_id = ? AND came_at IS NOT NULL "
        "AND left_at IS NULL AND work_date < ?",
        (ctx.require(), before),
    )
    closed = []
    for row in rows:
        day = dt.date.fromisoformat(str(row["work_date"]))
        shift = shift_for(row["tg_id"], day.weekday())
        if not shift:
            continue
        db.run(
            "UPDATE attendance SET left_at = ?, note = COALESCE(note, ?) "
            "WHERE id = ?",
            (f"{row['work_date']}T{shift['ends_at']}:00",
             "Ketish qayd etilmagan — jadval bo'yicha yopildi", row["id"]),
        )
        closed.append(row["id"])
    return closed


def check_out(tg_id):
    now = now_local()
    row = record_of(tg_id, str(now.date()))
    if not row:
        raise BotError("Avval kelganingizni qayd qiling.")
    if row["left_at"]:
        raise BotError("Bugun allaqachon ketganingizni qayd qilgansiz.")

    shift = shift_for(tg_id, now.weekday())
    early = 0
    if shift:
        early = max(0, _minutes(shift["ends_at"]) - _minutes(now.strftime("%H:%M")))

    db.run(
        "UPDATE attendance SET left_at = ?, early_minutes = ? WHERE id = ?",
        (now.isoformat(timespec="seconds"), early, row["id"]),
    )
    worked = ""
    if row["came_at"]:
        came = dt.datetime.fromisoformat(row["came_at"])
        minutes = int((now - came).total_seconds() // 60)
        worked = f"\nIshlagan vaqt: {minutes // 60} soat {minutes % 60} daqiqa."
    tail = f"\n{early} daqiqa erta ketdingiz." if early > LATE_TOLERANCE else ""
    return f"Ketish qayd etildi: {now:%H:%M}.{worked}{tail}"


def mark_absent(tg_id, work_date, reason=None):
    """Kelmagan deb belgilash (menejer)."""
    status = "sababli" if reason else "kelmadi"
    db.run(
        "INSERT INTO attendance (tenant_id, tg_id, work_date, status, note) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT (tenant_id, tg_id, work_date) DO UPDATE SET "
        "  status = excluded.status, note = excluded.note",
        (ctx.require(), tg_id, str(work_date), status, reason),
    )
    if status == "kelmadi":
        add_points(tg_id, -3, "Sababsiz kelmadi", source="davomat")


def month_summary(tg_id, period=None):
    """Oylik davomat: {keldi, kechikdi, kelmadi, sababli, kechikish_daqiqa}"""
    period = period or f"{today_local():%Y-%m}"
    rows = db.rows(
        "SELECT status, late_minutes FROM attendance "
        "WHERE tenant_id = ? AND tg_id = ? AND work_date LIKE ?",
        (ctx.require(), tg_id, f"{period}-%"),
    )
    out = {"keldi": 0, "kechikdi": 0, "kelmadi": 0, "sababli": 0,
           "kechikish_daqiqa": 0, "ishlagan_kun": 0}
    for row in rows:
        out[row["status"]] = out.get(row["status"], 0) + 1
        out["kechikish_daqiqa"] += row["late_minutes"] or 0
    out["ishlagan_kun"] = out["keldi"] + out["kechikdi"]
    return out


# -------------------------------------------------------------------- ballar


def add_points(tg_id, amount, reason, source="qolda", given_by=None, ref=None):
    db.run(
        "INSERT INTO points (tenant_id, tg_id, amount, reason, source, ref, "
        "  given_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ctx.require(), tg_id, int(amount), reason, source, ref, given_by),
    )


def points_total(tg_id, period=None):
    """Jami hech qachon ustunda saqlanmaydi — har doim yig'indi."""
    sql = "SELECT COALESCE(SUM(amount), 0) FROM points WHERE tenant_id = ? AND tg_id = ?"
    params = [ctx.require(), tg_id]
    if period:
        sql += " AND created_at LIKE ?"
        params.append(f"{period}-%")
    return db.value(sql, tuple(params), default=0)


def rating(period=None):
    """Reyting: [(tg_id, ism, ball), ...] kamayish tartibida."""
    period = period or f"{today_local():%Y-%m}"
    return db.rows(
        "SELECT u.tg_id, u.name, "
        "  COALESCE((SELECT SUM(p.amount) FROM points p "
        "    WHERE p.tenant_id = u.tenant_id AND p.tg_id = u.tg_id "
        "      AND p.created_at LIKE ?), 0) AS total "
        "FROM users u WHERE u.tenant_id = ? AND u.active = 1 "
        "ORDER BY total DESC, u.name",
        (f"{period}-%", ctx.require()),
    )


# ------------------------------------------------------------------ ish haqi


def set_salary(tg_id, base=0, per_day=None):
    db.run("UPDATE salary SET active = 0 WHERE tenant_id = ? AND tg_id = ?",
           (ctx.require(), tg_id))
    db.run(
        "INSERT INTO salary (tenant_id, tg_id, base, per_day) VALUES (?, ?, ?, ?)",
        (ctx.require(), tg_id, float(base or 0),
         float(per_day) if per_day else None),
    )


def salary_of(tg_id):
    return db.row(
        "SELECT * FROM salary WHERE tenant_id = ? AND tg_id = ? AND active = 1",
        (ctx.require(), tg_id),
    )


def add_payout(tg_id, amount, kind="tolov", period=None, note=None, by=None):
    db.run(
        "INSERT INTO payout (tenant_id, tg_id, period, amount, kind, note, "
        "  created_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ctx.require(), tg_id, period or f"{today_local():%Y-%m}",
         float(amount), kind, note, by),
    )


def payroll(tg_id, period=None):
    """Oylik hisob. Qaytadi: lug'at, hisob-kitob ochiq ko'rinsin."""
    period = period or f"{today_local():%Y-%m}"
    salary = salary_of(tg_id)
    summary = month_summary(tg_id, period)

    if salary and salary["per_day"]:
        earned = float(salary["per_day"]) * summary["ishlagan_kun"]
        basis = f"{summary['ishlagan_kun']} kun × {ui.money(salary['per_day'])}"
    elif salary:
        earned = float(salary["base"])
        basis = "oylik stavka"
    else:
        earned, basis = 0.0, "stavka qo'yilmagan"

    rows = db.rows(
        "SELECT kind, COALESCE(SUM(amount), 0) AS total FROM payout "
        "WHERE tenant_id = ? AND tg_id = ? AND period = ? GROUP BY kind",
        (ctx.require(), tg_id, period),
    )
    by_kind = {r["kind"]: float(r["total"]) for r in rows}
    paid = by_kind.get("tolov", 0) + by_kind.get("avans", 0)
    held = by_kind.get("ushlab_qolish", 0)
    bonus = by_kind.get("mukofot", 0)

    return {
        "period": period,
        "basis": basis,
        "earned": earned,
        "bonus": bonus,
        "held": held,
        "paid": paid,
        "balance": earned + bonus - held - paid,
        "attendance": summary,
    }


# -------------------------------------------------------------------- modul


@registry.implement("xodimlar")
class Xodimlar(base.Module):
    def menu(self, role):
        if role in ("owner", "manager"):
            return [
                ("👥 Xodimlar", "mod:xodimlar:panel"),
                ("✅ Davomat", "mod:xodimlar:davomat"),
            ]
        return [("✅ Keldim / Ketdim", "mod:xodimlar:davomat")]

    def register(self, bot, guard):
        _register(bot, guard)


def _register(bot, guard):
    """Handlerlar. guard modul yoqilganini tekshiradi."""

    @bot.callback_query_handler(
        func=lambda c: (c.data or "").startswith("mod:xodimlar:"))
    @guard
    def _click(call):
        ui.ack(bot, call)
        action = call.data.split(":", 2)[2]
        chat_id, tg_id = call.message.chat.id, call.from_user.id

        if action == "davomat":
            _attendance_screen(bot, chat_id, tg_id)
        elif action == "keldim":
            _ask_location(bot, chat_id, tg_id)
        elif action == "ketdim":
            bot.send_message(chat_id, check_out(tg_id),
                             reply_markup=ui.main_menu(tg_id))
        elif action == "ball":
            _points_screen(bot, chat_id, tg_id)
        elif action == "reyting":
            _rating_screen(bot, chat_id, tg_id)
        elif action == "hisob":
            _payroll_screen(bot, chat_id, tg_id)
        elif action == "panel":
            _panel(bot, chat_id, tg_id)
        else:
            bot.send_message(chat_id, "Bu amal hali tayyor emas.")

    @bot.message_handler(content_types=["location"])
    @guard
    def _location(message):
        state, _ = sessions.get(message.from_user.id)
        if state != "xodimlar:keldim":
            return
        sessions.clear(message.from_user.id)
        _, text = check_in(
            message.from_user.id,
            lat=message.location.latitude,
            lon=message.location.longitude,
        )
        bot.send_message(message.chat.id, text,
                         reply_markup=ui.main_menu(message.from_user.id))
        deliver_tasks(bot, message.chat.id, message.from_user.id)


def _attendance_screen(bot, chat_id, tg_id):
    today = record_of(tg_id)
    lines = [f"<b>Davomat</b> — {today_local():%d.%m.%Y}"]
    buttons = []
    if not today:
        lines.append("Bugun hali qayd qilinmagan.")
        buttons.append(("✅ Keldim", "mod:xodimlar:keldim"))
    elif not today["left_at"]:
        came = dt.datetime.fromisoformat(today["came_at"])
        lines.append(f"Keldingiz: {came:%H:%M}")
        if today["late_minutes"]:
            lines.append(f"Kechikish: {today['late_minutes']} daqiqa")
        buttons.append(("🚪 Ketdim", "mod:xodimlar:ketdim"))
    else:
        came = dt.datetime.fromisoformat(today["came_at"])
        left = dt.datetime.fromisoformat(today["left_at"])
        lines.append(f"Keldingiz: {came:%H:%M}, ketdingiz: {left:%H:%M}")
        lines.append("Bugun uchun hammasi qayd etilgan.")

    summary = month_summary(tg_id)
    lines += [
        "",
        f"Shu oy: {summary['ishlagan_kun']} kun ishlangan, "
        f"{summary['kechikdi']} marta kechikish",
        f"Ballaringiz: {points_total(tg_id, f'{today_local():%Y-%m}')}",
    ]
    buttons += [("⭐ Ballarim", "mod:xodimlar:ball"),
                ("💰 Hisobim", "mod:xodimlar:hisob")]
    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML",
                     reply_markup=ui.buttons(buttons, back="menu:root"))


def deliver_tasks(bot, chat_id, tg_id):
    """Ishga kelgan xodimga kutayotgan vazifalarni eslatadi.

    Vazifa ish vaqtidan tashqarida berilgan bo'lsa xodim xabarni ko'rmay
    qolishi mumkin — kelganda qayta ko'rsatiladi.
    """
    from . import vazifalar

    try:
        from .. import modules as _modules

        if not _modules.enabled("vazifalar"):
            return
        rows = vazifalar.pending_for(tg_id)
    except Exception:  # noqa: BLE001 — vazifalar moduli davomatni yiqitmasin
        log.warning("Vazifalar olinmadi", exc_info=True)
        return
    if not rows:
        return
    lines = [f"📋 Sizda {len(rows)} ta ochiq vazifa bor:", ""]
    for task in rows:
        lines.append(f"• {ui.escape(task['title'])} — "
                     f"{vazifalar.due_text(task)}")
    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML",
                     reply_markup=ui.buttons(
                         [("📋 Vazifalarim", "mod:vazifalar:menikilar")]))


def _ask_location(bot, chat_id, tg_id):
    place = tenant.get_json("work_place")
    if not place:
        _, text = check_in(tg_id)
        bot.send_message(chat_id, text, reply_markup=ui.main_menu(tg_id))
        deliver_tasks(bot, chat_id, tg_id)
        return
    sessions.set(tg_id, "xodimlar:keldim", {})
    from telebot import types

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add(types.KeyboardButton("📍 Joylashuvni yuborish", request_location=True))
    bot.send_message(
        chat_id,
        "Kelganingizni tasdiqlash uchun joylashuvni yuboring.",
        reply_markup=kb,
    )


def _points_screen(bot, chat_id, tg_id):
    period = f"{today_local():%Y-%m}"
    rows = db.rows(
        "SELECT amount, reason, created_at FROM points "
        "WHERE tenant_id = ? AND tg_id = ? AND created_at LIKE ? "
        "ORDER BY created_at DESC LIMIT 15",
        (ctx.require(), tg_id, f"{period}-%"),
    )
    lines = [f"<b>Ballar</b> — jami {points_total(tg_id, period)}", ""]
    if not rows:
        lines.append("Shu oyda hali ball yozilmagan.")
    for row in rows:
        sign = "➕" if row["amount"] > 0 else "➖"
        day = str(row["created_at"])[5:10].replace("-", ".")
        lines.append(f"{sign} {abs(row['amount'])} — {ui.escape(row['reason'])} "
                     f"({day})")
    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML",
                     reply_markup=ui.buttons(
                         [("🏆 Reyting", "mod:xodimlar:reyting")],
                         back="mod:xodimlar:davomat"))


def _rating_screen(bot, chat_id, tg_id):
    rows = rating()
    medals = ["🥇", "🥈", "🥉"]
    lines = [f"<b>Reyting</b> — {today_local():%B %Y}", ""]
    for i, row in enumerate(rows[:15]):
        mark = medals[i] if i < 3 else f"{i + 1}."
        me = " ←" if row["tg_id"] == tg_id else ""
        lines.append(f"{mark} {ui.escape(row['name'] or '—')} — "
                     f"{row['total']} ball{me}")
    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML",
                     reply_markup=ui.buttons([], back="mod:xodimlar:davomat"))


def _payroll_screen(bot, chat_id, tg_id):
    calc = payroll(tg_id)
    currency = tenant.get("currency_name") or "so'm"
    lines = [
        f"<b>Hisob</b> — {calc['period']}",
        "",
        f"Asos: {calc['basis']}",
        f"Ishlangan: {ui.money(calc['earned'], currency)}",
    ]
    if calc["bonus"]:
        lines.append(f"Mukofot: +{ui.money(calc['bonus'], currency)}")
    if calc["held"]:
        lines.append(f"Ushlab qolindi: −{ui.money(calc['held'], currency)}")
    if calc["paid"]:
        lines.append(f"To'langan: −{ui.money(calc['paid'], currency)}")
    lines += ["", f"<b>Qoldiq: {ui.money(calc['balance'], currency)}</b>"]

    summary = calc["attendance"]
    lines += [
        "",
        f"Davomat: {summary['ishlagan_kun']} kun, "
        f"{summary['kechikdi']} kechikish ({summary['kechikish_daqiqa']} daqiqa)",
    ]
    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML",
                     reply_markup=ui.buttons([], back="mod:xodimlar:davomat"))


def _panel(bot, chat_id, tg_id):
    users.require_role(tg_id, "manager")
    period = f"{today_local():%Y-%m}"
    lines = [f"<b>Jamoa</b> — {period}", ""]
    for row in rating(period):
        summary = month_summary(row["tg_id"], period)
        today = record_of(row["tg_id"])
        if today and today["came_at"]:
            mark = "🟢" if today["status"] == "keldi" else "🟡"
        elif today:
            mark = "🔴"
        else:
            mark = "⚪"
        lines.append(
            f"{mark} {ui.escape(row['name'] or '—')} — "
            f"{summary['ishlagan_kun']} kun, {row['total']} ball"
        )
    lines += ["", "🟢 keldi · 🟡 kechikdi · 🔴 kelmadi · ⚪ bugun qayd yo'q"]
    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML",
                     reply_markup=ui.buttons([], back="menu:root"))
