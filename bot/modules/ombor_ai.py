"""Ombor AI: sotuv tezligi, zakaz tavsiyasi, ABC tahlil, turib qolganlar.

Manba — Bito sotuv hisoboti. Ikkita saboq market-bot'dan:

- **`sales/by-item` faqat sotilganlarni beradi.** Umuman sotilmagan
  mahsulot bu hisobotda yo'q. «Turib qolganlar» ro'yxati katalogdan shu
  hisobotni AYIRIB olinadi — aks holda ro'yxat doim bo'sh chiqadi.
- **Hisobot keshlanadi.** Har savolda qayta so'ralsa bot bir necha
  daqiqa jim turardi.

Tavsiya hech qachon avtomatik bajarilmaydi — faqat ko'rsatiladi.
"""

import datetime as dt
import logging

from . import base, ombor, registry
from .. import bito, ctx, db, tenant, ui, users
from ..errors import BitoError, BotError

log = logging.getLogger(__name__)

DEFAULT_DAYS = 30
DEFAULT_HORIZON = 14      # necha kunga zaxira kerak
PAGE_LIMIT = 200
MAX_PAGES = 40

# ABC chegaralari: jami tushumdagi ulush bo'yicha
ABC_A = 0.80
ABC_B = 0.95


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ------------------------------------------------------------------- skaner


def scan_state():
    row = db.row("SELECT * FROM sales_scan WHERE tenant_id = ?",
                 (ctx.require(),))
    if row:
        return row
    db.run("INSERT INTO sales_scan (tenant_id) VALUES (?)", (ctx.require(),))
    return db.row("SELECT * FROM sales_scan WHERE tenant_id = ?",
                  (ctx.require(),))


def scan(days=DEFAULT_DAYS, client=None, max_pages=MAX_PAGES):
    """Sotuv hisobotini yig'ib keshga yozadi."""
    tid = ctx.require()
    client = client or bito.client()
    scan_state()

    to_date = dt.datetime.now()
    from_date = to_date - dt.timedelta(days=days)
    seen, page = [], 1
    try:
        while page <= max_pages:
            rows, _ = client.sales_by_item(
                page=page, limit=PAGE_LIMIT,
                from_date=from_date.strftime("%Y-%m-%dT00:00:00Z"),
                to_date=to_date.strftime("%Y-%m-%dT23:59:59Z"))
            if not rows:
                break
            for row in rows:
                pid = str(row.get("product_id") or row.get("_id") or "")
                if not pid:
                    continue
                qty = _num(row.get("amount") or row.get("qty")
                           or row.get("count"))
                revenue = _num(row.get("total") or row.get("revenue")
                               or row.get("sum"))
                seen.append(pid)
                db.run(
                    "INSERT INTO sales_stat (tenant_id, product_id, name, qty, "
                    "  revenue, days, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, datetime('now')) "
                    "ON CONFLICT (tenant_id, product_id) DO UPDATE SET "
                    "  name = excluded.name, qty = excluded.qty, "
                    "  revenue = excluded.revenue, days = excluded.days, "
                    "  updated_at = excluded.updated_at",
                    (tid, pid, row.get("name") or row.get("product_name"),
                     qty, revenue, days),
                )
            if len(rows) < PAGE_LIMIT:
                break
            page += 1
    except BitoError as e:
        db.run("UPDATE sales_scan SET error = ? WHERE tenant_id = ?",
               (e.user_message[:300], tid))
        raise

    if seen:
        marks = ",".join("?" * len(seen))
        db.run(f"DELETE FROM sales_stat WHERE tenant_id = ? "
               f"AND product_id NOT IN ({marks})", (tid, *seen))
    else:
        db.run("DELETE FROM sales_stat WHERE tenant_id = ?", (tid,))

    db.run("UPDATE sales_scan SET days = ?, total_items = ?, error = NULL, "
           "  finished_at = datetime('now') WHERE tenant_id = ?",
           (days, len(seen), tid))
    return {"items": len(seen), "days": days}


def stats():
    return db.rows("SELECT * FROM sales_stat WHERE tenant_id = ?",
                   (ctx.require(),))


def daily_rate(row):
    """Kunlik o'rtacha sotuv."""
    days = max(int(row["days"] or 1), 1)
    return _num(row["qty"]) / days


# -------------------------------------------------------------- ABC tahlil


def abc(rows=None):
    """Tushumdagi ulush bo'yicha A / B / C sinflari.

    A — jami tushumning 80% ini beradiganlar, B — 95% gacha, qolgani C.
    """
    rows = rows if rows is not None else stats()
    ordered = sorted(rows, key=lambda row: -_num(row["revenue"]))
    total = sum(_num(row["revenue"]) for row in ordered)
    if total <= 0:
        return [dict(row, abc="C", share=0.0) for row in ordered]

    out, running = [], 0.0
    for row in ordered:
        # Sinf mahsulot QO'SHILGUNCHA bo'lgan ulushga qarab beriladi.
        # Aks holda chegarani kesib o'tgan mahsulot o'zi kesib o'tgan
        # sinfga tushib qolardi: eng katta tovar «C» bo'lib chiqardi.
        letter = "A" if running < ABC_A else ("B" if running < ABC_B else "C")
        running += _num(row["revenue"]) / total
        out.append(dict(row, abc=letter, share=_num(row["revenue"]) / total))
    return out


def abc_summary(rows=None):
    graded = abc(rows)
    out = {}
    for row in graded:
        key = row["abc"]
        entry = out.setdefault(key, {"count": 0, "revenue": 0.0})
        entry["count"] += 1
        entry["revenue"] += _num(row["revenue"])
    return out


# ---------------------------------------------------------- zakaz tavsiyasi


def reorder(horizon=DEFAULT_HORIZON, limit=30):
    """Zakaz qilish kerak bo'lganlar.

    kerak = kunlik_sotuv × ufq − mavjud qoldiq.
    Faqat musbat natijalar, tezligi yuqorisi birinchi.
    """
    horizon = max(int(horizon or 1), 1)
    rows = db.rows(
        "SELECT s.product_id, s.name, s.qty, s.days, s.revenue, "
        "  COALESCE(c.amount, 0) AS stock, c.measure "
        "FROM sales_stat s LEFT JOIN catalog c "
        "  ON c.tenant_id = s.tenant_id AND c.product_id = s.product_id "
        "WHERE s.tenant_id = ?", (ctx.require(),))

    out = []
    for row in rows:
        rate = daily_rate(row)
        if rate <= 0:
            continue
        need = rate * horizon - _num(row["stock"])
        if need <= 0:
            continue
        days_left = _num(row["stock"]) / rate if rate else 0
        out.append({
            "product_id": row["product_id"],
            "name": row["name"] or "—",
            "measure": row["measure"] or "",
            "stock": _num(row["stock"]),
            "rate": rate,
            "need": need,
            "days_left": days_left,
        })
    out.sort(key=lambda item: item["days_left"])
    return out[:limit]


# ---------------------------------------------------------- turib qolganlar


def stale(limit=30, min_stock=1):
    """Qoldig'i bor, lekin davr ichida umuman sotilmaganlar.

    Katalogdan sotuv keshini AYIRIB olinadi — Bito hisoboti
    sotilmaganlarni ko'rsatmaydi.
    """
    rows = db.rows(
        "SELECT c.product_id, c.name, c.amount, c.measure "
        "FROM catalog c LEFT JOIN sales_stat s "
        "  ON s.tenant_id = c.tenant_id AND s.product_id = c.product_id "
        "WHERE c.tenant_id = ? AND s.product_id IS NULL AND c.amount >= ? "
        "ORDER BY c.amount DESC LIMIT ?",
        (ctx.require(), min_stock, limit))
    return [dict(row) for row in rows]


def slow_movers(limit=20, max_days_stock=90):
    """Sotilyapti, lekin juda sekin — zaxira uzoq yetadi."""
    out = []
    for row in stats():
        rate = daily_rate(row)
        if rate <= 0:
            continue
        stock = db.value("SELECT amount FROM catalog WHERE tenant_id = ? "
                         "AND product_id = ?",
                         (ctx.require(), row["product_id"]), default=0)
        days_left = _num(stock) / rate
        if days_left >= max_days_stock:
            out.append({"name": row["name"] or "—", "stock": _num(stock),
                        "days_left": days_left, "rate": rate})
    out.sort(key=lambda item: -item["days_left"])
    return out[:limit]


# -------------------------------------------------------------------- modul


@registry.implement("ombor_ai")
class OmborAI(base.Module):
    def menu(self, role):
        if role == "staff":
            return []
        return [("🤖 Ombor tahlili", "mod:oai:panel")]

    def register(self, bot, guard):
        _register(bot, guard)

    def jobs(self):
        return [("sotuv_skan", lambda: scan(), 24 * 3600)]


def _register(bot, guard):
    @bot.callback_query_handler(
        func=lambda c: (c.data or "").startswith("mod:oai:"))
    @guard
    def _click(call):
        ui.ack(bot, call)
        action = call.data.split(":", 2)[2]
        chat_id, tg_id = call.message.chat.id, call.from_user.id
        users.require_role(tg_id, "manager")

        if action == "panel":
            _panel(bot, chat_id, tg_id)
        elif action == "zakaz":
            _reorder(bot, chat_id, tg_id)
        elif action == "turib":
            _stale(bot, chat_id, tg_id)
        elif action == "sekin":
            _slow(bot, chat_id, tg_id)
        elif action == "abc":
            _abc(bot, chat_id, tg_id)
        elif action == "yangila":
            note = bot.send_message(chat_id, "Sotuv hisoboti olinmoqda…")
            result = scan()
            try:
                bot.delete_message(chat_id, note.message_id)
            except Exception:  # noqa: BLE001
                pass
            bot.send_message(
                chat_id,
                f"✅ {result['items']} ta mahsulot bo'yicha "
                f"{result['days']} kunlik sotuv yig'ildi.")
            _panel(bot, chat_id, tg_id)


def _fresh(bot, chat_id):
    state = scan_state()
    if not state["finished_at"]:
        bot.send_message(chat_id, "Sotuv ma'lumoti yig'ilmagan. "
                                  "«Yangilash» tugmasini bosing.")
        return False
    return True


def _panel(bot, chat_id, tg_id):
    state = scan_state()
    lines = ["<b>Ombor tahlili</b>", ""]
    if state["finished_at"]:
        lines.append(f"Sotuv ma'lumoti: {state['total_items']} ta mahsulot, "
                     f"{state['days']} kunlik")
        lines.append(f"Oxirgi yangilash: {state['finished_at']} UTC")
    else:
        lines.append("Sotuv ma'lumoti hali yig'ilmagan.")
    if state["error"]:
        lines.append(f"\n⚠️ {ui.escape(state['error'])}")
    if ombor.scan_state()["finished_at"] is None:
        lines.append("\n⚠️ Ombor katalogi yangilanmagan — qoldiqsiz tahlil "
                     "to'liq bo'lmaydi.")

    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML",
                     reply_markup=ui.buttons(
                         [("🛒 Zakaz tavsiyasi", "mod:oai:zakaz"),
                          ("🧊 Turib qolganlar", "mod:oai:turib"),
                          ("🐢 Sekin sotilayotganlar", "mod:oai:sekin"),
                          ("📊 ABC tahlil", "mod:oai:abc"),
                          ("🔄 Yangilash", "mod:oai:yangila")],
                         row_width=1, back="menu:root"))


def _reorder(bot, chat_id, tg_id):
    if not _fresh(bot, chat_id):
        return
    horizon = int(tenant.get("zakaz_horizon") or DEFAULT_HORIZON)
    rows = reorder(horizon=horizon)
    if not rows:
        bot.send_message(chat_id, "Hozircha zakaz kerak emas. 👍",
                         reply_markup=ui.buttons([], back="mod:oai:panel"))
        return
    lines = [f"<b>Zakaz tavsiyasi</b> — {horizon} kunlik zaxira uchun", ""]
    for row in rows:
        lines.append(
            f"• {ui.escape(row['name'])}\n"
            f"    qoldiq {row['stock']:g} · kuniga {row['rate']:.1f} · "
            f"{row['days_left']:.0f} kunga yetadi\n"
            f"    <b>zakaz: {row['need']:.0f} {ui.escape(row['measure'])}</b>")
    lines.append("\nTavsiya — qaror sizniki. Bot hech narsa buyurtma qilmaydi.")
    for chunk in ui.chunks("\n".join(lines)):
        bot.send_message(chat_id, chunk, parse_mode="HTML")
    bot.send_message(chat_id, "—",
                     reply_markup=ui.buttons([], back="mod:oai:panel"))


def _stale(bot, chat_id, tg_id):
    if not _fresh(bot, chat_id):
        return
    rows = stale()
    state = scan_state()
    if not rows:
        bot.send_message(chat_id, "Turib qolgan mahsulot yo'q. 👍",
                         reply_markup=ui.buttons([], back="mod:oai:panel"))
        return
    lines = [f"<b>Turib qolganlar</b> — {state['days']} kunda umuman "
             f"sotilmagan", ""]
    for row in rows:
        lines.append(f"• {ui.escape(row['name'])}: {row['amount']:g} "
                     f"{ui.escape(row['measure'] or '')}")
    lines.append("\nChegirma yoki aksiya haqida o'ylab ko'ring.")
    for chunk in ui.chunks("\n".join(lines)):
        bot.send_message(chat_id, chunk, parse_mode="HTML")
    bot.send_message(chat_id, "—",
                     reply_markup=ui.buttons([], back="mod:oai:panel"))


def _slow(bot, chat_id, tg_id):
    if not _fresh(bot, chat_id):
        return
    rows = slow_movers()
    if not rows:
        bot.send_message(chat_id, "Ortiqcha zaxira yo'q. 👍",
                         reply_markup=ui.buttons([], back="mod:oai:panel"))
        return
    lines = ["<b>Sekin sotilayotganlar</b>", "",
             "Zaxira uzoq muddatga yetadi — puli band bo'lib turibdi:", ""]
    for row in rows:
        lines.append(f"• {ui.escape(row['name'])}: {row['stock']:g} dona, "
                     f"{row['days_left']:.0f} kunga yetadi")
    for chunk in ui.chunks("\n".join(lines)):
        bot.send_message(chat_id, chunk, parse_mode="HTML")
    bot.send_message(chat_id, "—",
                     reply_markup=ui.buttons([], back="mod:oai:panel"))


def _abc(bot, chat_id, tg_id):
    if not _fresh(bot, chat_id):
        return
    graded = abc()
    if not graded:
        bot.send_message(chat_id, "Sotuv ma'lumoti yo'q.")
        return
    numbers = abc_summary(graded)
    currency = tenant.get("currency_name") or "so'm"
    lines = ["<b>ABC tahlil</b>", "",
             "A — tushumning 80% ini beradiganlar",
             "B — keyingi 15%", "C — qolgan 5%", ""]
    for letter in ("A", "B", "C"):
        entry = numbers.get(letter)
        if entry:
            lines.append(f"<b>{letter}</b>: {entry['count']} ta mahsulot, "
                         f"{ui.money(entry['revenue'], currency)}")
    lines += ["", "<b>Eng ko'p tushum keltirganlar:</b>"]
    for row in graded[:10]:
        lines.append(f"  {row['abc']} · {ui.escape(row['name'] or '—')} — "
                     f"{ui.money(row['revenue'], currency)}")
    lines.append("\nA guruhidagi mahsulot tugab qolmasligi kerak.")
    for chunk in ui.chunks("\n".join(lines)):
        bot.send_message(chat_id, chunk, parse_mode="HTML")
    bot.send_message(chat_id, "—",
                     reply_markup=ui.buttons([], back="mod:oai:panel"))
