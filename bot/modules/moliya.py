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
from .. import bito, tenant, ui, users
from ..errors import BitoError

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
    """Bizga qarzdorlar (mijozlar) va biz qarzdormiz (firmalar)."""
    client = client or bito.client()
    result = {"customers": 0.0, "suppliers": 0.0}
    try:
        result["customers"] = _pick(client.debt_summary(),
                                    "total", "total_debt", "amount")
    except BitoError:
        log.warning("Mijoz qarzi olinmadi", exc_info=True)
    try:
        result["suppliers"] = _pick(client.credit_summary(),
                                    "total", "total_credit", "amount")
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


@registry.implement("moliya")
class Moliya(base.Module):
    def menu(self, role):
        if role == "staff":
            return []
        return [("📊 Moliya", "mod:moliya:panel")]

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
        users.require_role(tg_id, "manager")

        if action == "panel":
            _panel(bot, chat_id, tg_id)
        elif action == "qarzlar":
            _debts(bot, chat_id, tg_id)
        elif action == "limit":
            _limit(bot, chat_id, tg_id)


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
