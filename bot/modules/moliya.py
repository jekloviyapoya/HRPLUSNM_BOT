"""Moliya moduli: kassa, qarzlar, zakaz limiti.

Uchta qoida market-bot'da amalda sinovdan o'tgan
(`LESSONS-MARKET-BOT.md` bilan birga o'qing):

1. **Kassadagi pul balans hisobotidan olinadi**, tranzaksiyalardan
   yig'ilmaydi. Tranzaksiya taxmini 10.7 mln ko'rsatgan, haqiqiysi
   31.2 mln edi.
2. **Firmalar `supplier/get-paging` dan** olinadi. Qarz hisobotidagi
   `supplier._id` mahsulot kartochkasidagi `supplier_ids` bilan mos
   kelmaydi — 114 ta bog'langan mahsulotda nol moslik chiqqan.
3. **Zakaz limiti ufq kuniga bo'linadi.** Bo'linmasa, bir kunlik zakazga
   butun haftalik byudjet ruxsat berilgan bo'lardi.
"""

import logging

from . import base, registry
from .. import bito, sessions, tenant, ui, users
from ..errors import BitoError, BotError

log = logging.getLogger(__name__)

DEFAULT_HORIZON = 7      # kun
RESERVE_DAYS = 3         # zaxira: shuncha kunlik majburiy xarajat


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _pick(payload, *keys, default=0.0):
    """Javobdagi maydonni bir necha nom bo'yicha qidiradi."""
    if not isinstance(payload, dict):
        return default
    for key in keys:
        if key in payload:
            return _num(payload[key], default)
    for value in payload.values():
        if isinstance(value, dict):
            found = _pick(value, *keys, default=None)
            if found is not None:
                return found
    return default


# --------------------------------------------------------------------- kassa


def cash_on_hand(client=None):
    """Kassalardagi jami pul. Qaytadi: (jami, [{name, amount}, ...])"""
    client = client or bito.client()
    payload = client.balance()

    boxes = []
    rows = payload if isinstance(payload, list) else None
    if rows is None and isinstance(payload, dict):
        for key in ("cashboxes", "boxes", "items", "active", "assets", "data"):
            if isinstance(payload.get(key), list):
                rows = payload[key]
                break
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        amount = _num(row.get("amount") or row.get("total")
                      or row.get("balance"))
        name = row.get("name") or row.get("title") or "—"
        if amount:
            boxes.append({"name": str(name), "amount": amount})

    total = sum(box["amount"] for box in boxes)
    if not total:
        total = _pick(payload if isinstance(payload, dict) else {},
                      "total", "cash", "balance")
    boxes.sort(key=lambda box: -box["amount"])
    return total, boxes


# -------------------------------------------------------------------- qarzlar


def debts(client=None):
    """Bizga qarzdorlar (mijozlar) va biz qarzdormiz (firmalar).

    ⚠️ Firmalar qarzi hisobot summasidan EMAS, firmalar ro'yxatidan
    yig'iladi. Sabab: qarz hisobotida Bito ro'yxatida endi mavjud
    bo'lmagan firmalar ham qolib ketadi va «fantom qarz» ko'rsatadi.
    Ro'yxatda yo'q firma to'langan hisoblanadi.

    Ro'yxat olinmasa — hisobot summasi zaxira sifatida ishlatiladi.
    """
    client = client or bito.client()
    result = {"customers": 0.0, "suppliers": 0.0, "phantom": False}
    try:
        result["customers"] = _pick(client.debt_summary(),
                                    "total", "total_debt", "amount")
    except BitoError:
        log.warning("Mijoz qarzi olinmadi", exc_info=True)

    try:
        rows = suppliers_with_balance(client)
        result["suppliers"] = sum(-row["balance"] for row in rows
                                  if row["balance"] < 0)
    except BitoError:
        log.warning("Firmalar ro'yxati olinmadi, hisobot summasi ishlatiladi",
                    exc_info=True)
        try:
            result["suppliers"] = _pick(client.credit_summary(),
                                        "total", "total_credit", "amount")
            result["phantom"] = True
        except BitoError:
            log.warning("Firma qarzi olinmadi", exc_info=True)
    return result


def suppliers_with_balance(client=None, max_pages=10):
    """Firmalar + qarz. Manba: supplier/get-paging.

    Qarz hisobotidan olinmaydi — u yerdagi id mahsulot kartochkasidagi
    supplier_ids bilan mos kelmaydi.
    """
    client = client or bito.client()
    out, page = [], 1
    while page <= max_pages:
        rows, _ = client.suppliers(page=page, limit=200)
        if not rows:
            break
        for row in rows:
            balance = _num(row.get("balance") or row.get("debt"))
            out.append({
                "id": str(row.get("_id") or row.get("id") or ""),
                "name": row.get("name") or "—",
                "balance": balance,
            })
        if len(rows) < 200:
            break
        page += 1
    out.sort(key=lambda row: row["balance"])
    return out


# -------------------------------------------------------------- zakaz limiti


def order_limit(cash, daily_income, obligations, horizon=DEFAULT_HORIZON,
                reserve=None):
    """Ertangi zakaz uchun ruxsat etilgan summa.

    UFQ DAVOMIDAGI bo'sh pul kunlik ulushga BO'LINADI. Bo'linmasa,
    bir kunlik zakazga butun haftalik byudjet ruxsat berilgan bo'lardi
    (market-bot'da «567% ko'paytiring» degan bema'ni tavsiya chiqqan edi).

    Qaytadi: lug'at — hisob-kitob ochiq ko'rinsin.
    """
    horizon = max(int(horizon or 1), 1)
    expected_in = _num(daily_income) * horizon
    if reserve is None or _num(reserve) <= 0:
        reserve = (_num(obligations) / horizon) * RESERVE_DAYS
    available = _num(cash) + expected_in - _num(obligations) - _num(reserve)
    return {
        "horizon": horizon,
        "cash": _num(cash),
        "expected_in": expected_in,
        "obligations": _num(obligations),
        "reserve": _num(reserve),
        "available": available,
        "daily_limit": available / horizon,
    }


def advice(limit, avg_daily_purchase):
    """Odatdagi sur'atga nisbatan tavsiya."""
    daily = limit["daily_limit"]
    average = _num(avg_daily_purchase)
    if daily <= 0:
        return ("🔴 Bugun yangi zakaz bermang — bo'sh pul yo'q. "
                "Avval tushumni kuting yoki qarzlarni yig'ing.")
    if average <= 0:
        return "🟢 Zakaz uchun bo'sh pul bor."
    ratio = daily / average
    if ratio < 0.7:
        return (f"🟡 Odatdagidan kam: zakazni taxminan "
                f"{int((1 - ratio) * 100)}% qisqartiring.")
    if ratio > 1.4:
        return (f"🟢 Bo'sh pul odatdagidan ko'p — zakazni "
                f"{int((ratio - 1) * 100)}% gacha oshirish mumkin.")
    return "🟢 Odatdagi sur'atda davom eting."


def daily_income(client=None, days=30):
    """Kunlik o'rtacha tushum."""
    client = client or bito.client()
    try:
        payload = client.get("income_expense")
    except BitoError:
        log.warning("Tushum statistikasi olinmadi", exc_info=True)
        return 0.0
    total = _pick(payload, "total_income", "income", "total")
    return total / max(days, 1) if total else 0.0


def avg_daily_purchase(client=None, days=30, max_pages=5):
    """Oxirgi kunlardagi o'rtacha kunlik xarid."""
    client = client or bito.client()
    total, page = 0.0, 1
    try:
        while page <= max_pages:
            rows, _ = client.purchases(page=page, limit=200)
            if not rows:
                break
            for row in rows:
                total += _num(row.get("total") or row.get("amount"))
            if len(rows) < 200:
                break
            page += 1
    except BitoError:
        log.warning("Xaridlar olinmadi", exc_info=True)
        return 0.0
    return total / max(days, 1)


# -------------------------------------------------------------------- modul


# --------------------------------------------------------------- savdo
# market-bot tengligi (PARITY.md 1-band). Ma'lumot Bito'dan, ikkita
# hisobot: jami (dashboard/summary) va sotuvchilar kesimi
# (top/responsible). Xodim o'z savdosini ko'rishi uchun uning Bito'dagi
# ismi bog'lanadi (sozlama: bito_name:<tg_id>).

BONUS_DEFAULT = 0.005      # 0.5% — market-bot standarti


def utc_range(day_from, day_to, tz_hours):
    """Mahalliy kunlar oralig'i -> UTC ISO chegaralar.

    Kun boshi 00:00, oxiri 23:59:59.999 mahalliy vaqtda; UTC ga
    o'girilmasa Bito kun chegarasini surib yuboradi (market-bot saboqi).
    """
    import datetime as _dt

    tz = _dt.timezone(_dt.timedelta(hours=tz_hours))
    start = _dt.datetime.combine(day_from, _dt.time.min, tz)
    end = (_dt.datetime.combine(day_to, _dt.time.min, tz)
           + _dt.timedelta(days=1) - _dt.timedelta(milliseconds=1))
    fmt = "%Y-%m-%dT%H:%M:%S.%f"
    return (start.astimezone(_dt.timezone.utc).strftime(fmt)[:-3] + "Z",
            end.astimezone(_dt.timezone.utc).strftime(fmt)[:-3] + "Z")


def sales_period(period, today):
    """'today'|'week'|'month' -> (sarlavha, boshlanish, tugash)."""
    import datetime as _dt

    if period == "week":
        return ("Haftalik savdo (so'nggi 7 kun)",
                today - _dt.timedelta(days=6), today)
    if period == "month":
        return (f"Oylik savdo — {today.strftime('%m.%Y')}",
                today.replace(day=1), today)
    return (f"Bugungi savdo — {today.strftime('%d.%m.%Y')}", today, today)


def responsible_name(item):
    return str(item.get("full_name") or item.get("name")
               or item.get("responsible") or "").strip()


def bonus_rate():
    return _num(tenant.get("savdo_bonus"), BONUS_DEFAULT)


def plan_progress(total, plan):
    """(foiz, chiziq) yoki None. Chiziq 10 katakli."""
    plan = _num(plan)
    if plan <= 0:
        return None
    pct = round(total / plan * 100)
    filled = min(pct // 10, 10)
    return pct, "█" * filled + "░" * (10 - filled)


def format_sales(summary, employees, title, currency):
    total = _num((summary or {}).get("gross_sales"))
    lines = [f"💵 <b>{ui.escape(title)}</b>", "",
             f"Jami: <b>{ui.money(total, currency)}</b>"]
    receipts = (summary or {}).get("receipts")
    if receipts:
        lines.append(f"Cheklar: {int(_num(receipts))}")
    rows = sorted(employees or [],
                  key=lambda x: -_num(x.get("gross_sales")))
    if rows:
        lines.append("")
        lines.append("<b>Sotuvchilar</b>")
        for i, item in enumerate(rows[:15], 1):
            name = responsible_name(item) or "—"
            lines.append(
                f"{i}. {ui.escape(name)} — "
                f"{ui.money(_num(item.get('gross_sales')), currency)}"
                f" ({int(_num(item.get('receipts')))} chek)")
    progress = plan_progress(total, tenant.get("savdo_reja"))
    if progress and title.startswith("Oylik"):
        pct, bar = progress
        lines += ["", f"🎯 Oy rejasi: {pct}%", bar,
                  f"{ui.money(total, currency)} / "
                  f"{ui.money(_num(tenant.get('savdo_reja')), currency)}"]
    return "\n".join(lines)


def my_sales(tg_id, client=None):
    """Xodimning bugungi savdosi: (gross, receipts, bonus) yoki None
    (Bito ismi bog'lanmagan)."""
    from . import xodimlar

    bito_name = tenant.get(f"bito_name:{tg_id}")
    if not bito_name:
        return None
    client = client or bito.client()
    today = xodimlar.today_local()
    frm, to = utc_range(today, today, xodimlar._tz_offset())
    items = client.sales_by_responsible(frm, to) or []
    mine = next((it for it in items
                 if responsible_name(it) == bito_name), None)
    gross = _num((mine or {}).get("gross_sales"))
    receipts = int(_num((mine or {}).get("receipts")))
    return {"name": bito_name, "gross": gross, "receipts": receipts,
            "bonus": round(gross * bonus_rate())}


@registry.implement("moliya")
class Moliya(base.Module):
    def menu(self, role):
        if role == "staff":
            return [("💵 Savdo", "mod:moliya:mysavdo")]
        return [("📊 Moliya", "mod:moliya:panel"),
                ("💵 Savdo", "mod:moliya:savdo")]

    def register(self, bot, guard):
        _register(bot, guard)


def _register(bot, guard):
    @bot.callback_query_handler(
        func=lambda c: (c.data or "").startswith("mod:moliya:"))
    @guard
    def _click(call):
        ui.ack(bot, call)
        action = call.data.split(":", 2)[2]
        chat_id, tg_id = call.message.chat.id, call.from_user.id

        # Xodimga ochiq yagona bo'lim — o'z savdosi
        if action == "mysavdo":
            _my_sales_screen(bot, chat_id, tg_id)
            return
        users.require_role(tg_id, "manager")

        if action == "panel":
            _panel(bot, chat_id, tg_id)
        elif action == "qarzlar":
            _debts(bot, chat_id, tg_id)
        elif action == "limit":
            _limit(bot, chat_id, tg_id)
        elif action == "savdo":
            _sales_menu(bot, chat_id)
        elif action in ("savdo_today", "savdo_week", "savdo_month"):
            _sales_report(bot, chat_id, action.split("_", 1)[1])
        elif action == "savdo_sana":
            sessions.set(tg_id, "moliya:savdo_sana", {})
            bot.send_message(chat_id,
                             "Oraliqni yozing: <code>01.08.2026 14.08.2026</code>"
                             "\n(bitta sana ham bo'ladi)", parse_mode="HTML")
        elif action == "savdo_reja":
            sessions.set(tg_id, "moliya:savdo_reja", {})
            current = _num(tenant.get("savdo_reja"))
            extra = (f"\nHozirgi: {ui.money(current, _currency())}"
                     if current else "")
            bot.send_message(chat_id,
                             f"🎯 Oylik savdo rejasini yozing (faqat son).{extra}")
        elif action == "savdo_bonus":
            sessions.set(tg_id, "moliya:savdo_bonus", {})
            bot.send_message(chat_id,
                             f"Bonus foizini yozing (hozirgi: "
                             f"{bonus_rate() * 100:g}%). Masalan: 0.5")
        elif action == "savdo_bogla":
            _link_pick_user(bot, chat_id)
        elif action.startswith("sb_u_"):
            _link_pick_name(bot, chat_id, tg_id, int(action[5:]))
        elif action.startswith("sb_n_"):
            _link_apply(bot, chat_id, tg_id, int(action[5:]))

    @bot.message_handler(
        func=lambda m: (sessions.get_global(m.from_user.id)[0] or "")
        .startswith("moliya:"),
        content_types=["text"])
    @guard
    def _text(message):
        tg_id, chat_id = message.from_user.id, message.chat.id
        users.require_role(tg_id, "manager")
        state, _data = sessions.get_global(tg_id)
        text = (message.text or "").strip()
        sessions.clear(tg_id)

        if state == "moliya:savdo_reja":
            tenant.set("savdo_reja", str(_num(text.replace(" ", ""))))
            bot.send_message(chat_id, "🎯 Reja saqlandi.")
            _sales_menu(bot, chat_id)
        elif state == "moliya:savdo_bonus":
            rate = _num(text.replace(",", ".").replace("%", "")) / 100
            if not 0 <= rate <= 0.2:
                raise BotError("Foiz 0 dan 20 gacha bo'lsin.")
            tenant.set("savdo_bonus", str(rate))
            bot.send_message(chat_id, f"Bonus: {rate * 100:g}% saqlandi.")
        elif state == "moliya:savdo_sana":
            frm, to = _parse_range(text)
            _sales_report(bot, chat_id, "custom", frm, to)


def _currency():
    return tenant.get("currency_name") or "so'm"


def _panel(bot, chat_id, tg_id):
    note = bot.send_message(chat_id, "Bito'dan ma'lumot olinmoqda…")
    client = bito.client()
    total, boxes = cash_on_hand(client)
    owed = debts(client)

    lines = ["<b>Moliya</b>", "",
             f"💰 Kassada: {ui.money(total, _currency())}"]
    for box in boxes[:5]:
        lines.append(f"    {ui.escape(box['name'])}: "
                     f"{ui.money(box['amount'])}")
    lines += ["",
              f"📥 Mijozlar qarzi: {ui.money(owed['customers'], _currency())}",
              f"📤 Firmalarga qarz: {ui.money(owed['suppliers'], _currency())}"]

    try:
        bot.delete_message(chat_id, note.message_id)
    except Exception:  # noqa: BLE001
        pass
    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML",
                     reply_markup=ui.buttons(
                         [("🏢 Firmalar qarzi", "mod:moliya:qarzlar"),
                          ("🛒 Zakaz limiti", "mod:moliya:limit")],
                         row_width=1, back="menu:root"))


def _debts(bot, chat_id, tg_id):
    note = bot.send_message(chat_id, "Firmalar ro'yxati olinmoqda…")
    rows = [row for row in suppliers_with_balance() if row["balance"]]
    try:
        bot.delete_message(chat_id, note.message_id)
    except Exception:  # noqa: BLE001
        pass

    if not rows:
        bot.send_message(chat_id, "Qarzdorlik yo'q. 👍",
                         reply_markup=ui.buttons([], back="mod:moliya:panel"))
        return

    owe = [row for row in rows if row["balance"] < 0]
    lines = [f"<b>Firmalar</b> — {len(rows)} ta", ""]
    if owe:
        lines.append("Biz qarzdormiz:")
        for row in owe[:15]:
            lines.append(f"  {ui.escape(row['name'])}: "
                         f"{ui.money(abs(row['balance']), _currency())}")
    ahead = [row for row in rows if row["balance"] > 0]
    if ahead:
        lines += ["", "Oldindan to'langan:"]
        for row in ahead[:10]:
            lines.append(f"  {ui.escape(row['name'])}: "
                         f"{ui.money(row['balance'], _currency())}")

    for chunk in ui.chunks("\n".join(lines)):
        bot.send_message(chat_id, chunk, parse_mode="HTML")
    bot.send_message(chat_id, "—",
                     reply_markup=ui.buttons([], back="mod:moliya:panel"))


def _limit(bot, chat_id, tg_id):
    note = bot.send_message(chat_id, "Hisoblanmoqda…")
    client = bito.client()
    cash, _ = cash_on_hand(client)
    owed = debts(client)
    horizon = int(tenant.get("zakaz_horizon") or DEFAULT_HORIZON)
    reserve = tenant.get("zakaz_reserve")

    limit = order_limit(cash, daily_income(client), owed["suppliers"],
                        horizon=horizon, reserve=reserve)
    average = avg_daily_purchase(client)

    try:
        bot.delete_message(chat_id, note.message_id)
    except Exception:  # noqa: BLE001
        pass

    currency = _currency()
    lines = [
        f"<b>Zakaz limiti</b> — {limit['horizon']} kunlik ufq", "",
        f"Kassada: {ui.money(limit['cash'], currency)}",
        f"Kutilayotgan tushum: +{ui.money(limit['expected_in'], currency)}",
        f"Firmalarga qarz: −{ui.money(limit['obligations'], currency)}",
        f"Zaxira: −{ui.money(limit['reserve'], currency)}",
        "",
        f"Bo'sh pul: {ui.money(limit['available'], currency)}",
        f"<b>Kunlik limit: {ui.money(limit['daily_limit'], currency)}</b>",
    ]
    if average:
        lines.append(f"Odatdagi kunlik zakaz: {ui.money(average, currency)}")
    lines += ["", advice(limit, average)]

    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML",
                     reply_markup=ui.buttons([], back="mod:moliya:panel"))


def _parse_range(text):
    """'01.08.2026 14.08.2026' yoki bitta sana -> (date, date)."""
    import datetime as _dt

    parts = text.split()
    try:
        days = [_dt.datetime.strptime(p, "%d.%m.%Y").date() for p in parts]
    except ValueError:
        raise BotError("Sana formati: KK.OO.YYYY, masalan 01.08.2026")
    if not days:
        raise BotError("Sana yozilmadi.")
    if len(days) == 1:
        return days[0], days[0]
    frm, to = min(days[0], days[1]), max(days[0], days[1])
    return frm, to


def _sales_menu(bot, chat_id):
    plan_line = ""
    progress = None
    try:
        from . import xodimlar
        today = xodimlar.today_local()
        frm, to = utc_range(today.replace(day=1), today,
                            xodimlar._tz_offset())
        summary = bito.client().sales_summary(
            frm, to, organization_id=tenant.get("bito_org_id"))
        progress = plan_progress(_num((summary or {}).get("gross_sales")),
                                 tenant.get("savdo_reja"))
    except (BitoError, Exception):  # noqa: BLE001 — menyu ochilaversin
        log.warning("Savdo menyusida reja holati chiqmadi", exc_info=True)
    if progress:
        pct, bar = progress
        plan_line = f"\n\n🎯 Oy rejasi: {pct}%\n{bar}"
    bot.send_message(
        chat_id,
        "💵 <b>Savdo hisoboti</b>\nBito'dan haqiqiy ma'lumot" + plan_line,
        parse_mode="HTML",
        reply_markup=ui.buttons([
            ("📅 Bugungi", "mod:moliya:savdo_today"),
            ("📆 Haftalik", "mod:moliya:savdo_week"),
            ("🗓 Oylik", "mod:moliya:savdo_month"),
            ("📋 Muddatli", "mod:moliya:savdo_sana"),
            ("🎯 Oylik reja", "mod:moliya:savdo_reja"),
            ("🎁 Bonus foizi", "mod:moliya:savdo_bonus"),
            ("🔗 Xodimni Bito'ga bog'lash", "mod:moliya:savdo_bogla"),
        ], row_width=2, back="menu:root"))


def _sales_report(bot, chat_id, period, day_from=None, day_to=None):
    from . import xodimlar

    today = xodimlar.today_local()
    if period == "custom":
        title = (f"Savdo: {day_from.strftime('%d.%m.%Y')} — "
                 f"{day_to.strftime('%d.%m.%Y')}")
    else:
        title, day_from, day_to = sales_period(period, today)

    note = bot.send_message(chat_id, "⏳ Bito'dan olinmoqda…")
    client = bito.client()
    frm, to = utc_range(day_from, day_to, xodimlar._tz_offset())
    summary = client.sales_summary(frm, to,
                                   organization_id=tenant.get("bito_org_id"))
    employees = client.sales_by_responsible(frm, to)
    try:
        bot.delete_message(chat_id, note.message_id)
    except Exception:  # noqa: BLE001
        pass
    for chunk in ui.chunks(format_sales(summary, employees, title,
                                        _currency())):
        bot.send_message(chat_id, chunk, parse_mode="HTML")


def _my_sales_screen(bot, chat_id, tg_id):
    got = my_sales(tg_id)
    if got is None:
        bot.send_message(
            chat_id,
            "Siz hali Bito bilan bog'lanmagansiz.\n"
            "Boshliqdan so'rang: Savdo → 🔗 Xodimni Bito'ga bog'lash")
        return
    currency = _currency()
    bot.send_message(
        chat_id,
        f"💵 <b>Bugungi savdongiz</b>\n\n"
        f"💰 Savdo: <b>{ui.money(got['gross'], currency)}</b>\n"
        f"🧾 Cheklar: {got['receipts']}\n"
        f"🎁 Bonus ({bonus_rate() * 100:g}%): "
        f"<b>{ui.money(got['bonus'], currency)}</b>",
        parse_mode="HTML")


def _link_pick_user(bot, chat_id):
    rows = [u for u in users.listing() if u["role"] != "owner"]
    if not rows:
        bot.send_message(chat_id, "Hali xodim yo'q.")
        return
    buttons = []
    for u in rows:
        linked = tenant.get(f"bito_name:{u['tg_id']}")
        mark = f" → {linked}" if linked else ""
        buttons.append((f"{u['name'] or u['tg_id']}{mark}"[:50],
                        f"mod:moliya:sb_u_{u['tg_id']}"))
    bot.send_message(chat_id, "Qaysi xodimni bog'laymiz?",
                     reply_markup=ui.buttons(buttons, row_width=1,
                                             back="mod:moliya:savdo"))


def _link_pick_name(bot, chat_id, tg_id, target_tg_id):
    """Oxirgi 30 kun sotuvchilaridan tanlash — nomni qo'lda yozdirmaymiz."""
    from . import xodimlar

    today = xodimlar.today_local()
    frm, to = utc_range(today - __import__("datetime").timedelta(days=30),
                        today, xodimlar._tz_offset())
    items = bito.client().sales_by_responsible(frm, to) or []
    names = sorted({responsible_name(it) for it in items
                    if responsible_name(it)})
    if not names:
        bot.send_message(chat_id, "Bito'da so'nggi 30 kunda sotuvchi "
                                  "topilmadi.")
        return
    sessions.set(tg_id, "moliya:savdo_link",
                 {"target": target_tg_id, "names": names[:60]})
    buttons = [(name[:45], f"mod:moliya:sb_n_{i}")
               for i, name in enumerate(names[:60])]
    bot.send_message(chat_id, "Bito'dagi qaysi ism?",
                     reply_markup=ui.buttons(buttons, row_width=1,
                                             back="mod:moliya:savdo_bogla"))


def _link_apply(bot, chat_id, tg_id, index):
    state, data = sessions.get_global(tg_id)
    if state != "moliya:savdo_link":
        bot.send_message(chat_id, "Tanlov eskirgan — qaytadan boshlang.")
        return
    sessions.clear(tg_id)
    names = data.get("names") or []
    target = data.get("target")
    if index >= len(names):
        bot.send_message(chat_id, "Tanlov eskirgan — qaytadan boshlang.")
        return
    tenant.set(f"bito_name:{target}", names[index])
    bot.send_message(chat_id, f"🔗 Bog'landi: {ui.escape(names[index])}",
                     parse_mode="HTML")
