"""Ombor moduli: qoldiq, kam qolganlar, qidiruv.

Ma'lumot manbai — Bito. Ikkita yo'l:

- **Qidiruv** jonli: bitta so'rov, tez.
- **Kam qolganlar** keshdan: Bito'da 10 000+ mahsulot bo'lishi mumkin,
  sahifa hajmi 200 ta. Ro'yxatni har safar yig'ish 50+ so'rov degani —
  bot javobi uchun juda sekin. Fonda skanerlanadi.

Chegara qayerdan olinadi
------------------------
Bito'da har mahsulotda `red_line`, `yellow_line`, `standard` bor, lekin
ko'p do'konlarda ular to'ldirilmagan (0 yoki hammasiga bir xil 10).
Shuning uchun: `red_line` > 0 bo'lsa o'sha, aks holda `yellow_line`,
aks holda tenant sozlamasi, u ham yo'q bo'lsa faqat tugaganlar ko'rsatiladi.
Aks holda 11 000 ta mahsulotning yarmi «kam qolgan» bo'lib chiqadi.
"""

import logging

from . import base, registry
from .. import bito, ctx, db, sessions, tenant, ui, users
from ..errors import BitoError, BotError

log = logging.getLogger(__name__)

PAGE_LIMIT = 200
MAX_PAGES = 80          # 16 000 mahsulot — undan ortig'i bo'lsa ogohlantiriladi
SEARCH_LIMIT = 8


# --------------------------------------------------------------- yordamchilar


def warehouse_id():
    return tenant.require("warehouse_id")


def org_id():
    return tenant.require("bito_org_id")


def amount_of(product):
    """Tanlangan ombordagi qoldiq.

    `_warehouses` bor bo'lsa — **faqat o'sha** hukmron. Bizning ombor unda
    yo'q bo'lsa, qoldiq nol. Tashkilot yig'indisiga tushib ketish mumkin
    emas: ko'p omborli do'konda mijoz boshqa filialning tovarini o'ziniki
    deb ko'rardi.
    """
    warehouses = product.get("_warehouses")
    if isinstance(warehouses, dict):
        row = warehouses.get(str(warehouse_id()))
        if isinstance(row, dict):
            return float(row.get("amount") or 0)
        return 0.0
    for org in product.get("organizations") or []:
        if str(org.get("organization_id")) == str(org_id()):
            return float(org.get("amount") or 0)
    return 0.0


def _org_config(product):
    for org in product.get("organizations") or []:
        if str(org.get("organization_id")) == str(org_id()):
            return org
    return {}


def threshold_of(product):
    """Kam qolgan deb hisoblanadigan chegara. None — faqat tugagani muhim."""
    config = _org_config(product)
    for field in ("red_line", "yellow_line"):
        try:
            value = float(config.get(field) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
    default = tenant.get("low_stock_default")
    try:
        value = float(default)
        return value if value > 0 else None
    except (TypeError, ValueError):
        return None


def status_of(product):
    """'tugagan' | 'kam' | None"""
    amount = amount_of(product)
    if amount <= 0:
        return "tugagan"
    limit = threshold_of(product)
    if limit is not None and amount <= limit:
        return "kam"
    return None


def measure_of(product):
    measure = product.get("measure") or {}
    return measure.get("short_name") or measure.get("name") or ""


def category_of(product):
    return (product.get("category") or {}).get("name") or ""


def fmt(product_row):
    """Kesh qatorini bir satrga."""
    amount = product_row["amount"]
    text = f"{amount:g}".rstrip("0").rstrip(".") if amount % 1 else f"{int(amount)}"
    mark = "🔴" if product_row["status"] == "tugagan" else "🟡"
    tail = f" / {product_row['threshold']:g}" if product_row["threshold"] else ""
    return (f"{mark} {ui.escape(product_row['name'] or '—')} — "
            f"{text}{tail} {ui.escape(product_row['measure'] or '')}".rstrip())


# ------------------------------------------------------------------ skaner


def scan_state():
    row = db.row("SELECT * FROM stock_scan WHERE tenant_id = ?", (ctx.require(),))
    if row:
        return row
    db.run("INSERT INTO stock_scan (tenant_id) VALUES (?)", (ctx.require(),))
    return db.row("SELECT * FROM stock_scan WHERE tenant_id = ?", (ctx.require(),))


def scan(client=None, max_pages=MAX_PAGES):
    """Butun katalogni varaqlab, chegaradan pastdagilarni keshga yozadi.

    Fon ishida yoki qo'lda «Yangilash» tugmasi bilan chaqiriladi.
    """
    tid = ctx.require()
    client = client or bito.client()
    scan_state()
    db.run(
        "UPDATE stock_scan SET started_at = datetime('now'), finished_at = NULL, "
        "  error = NULL, pages_done = 0 WHERE tenant_id = ?",
        (tid,),
    )

    seen, low, out, total = [], 0, 0, None
    page = 1
    try:
        while page <= max_pages:
            rows, reported = client.products(page=page, limit=PAGE_LIMIT)
            if reported is not None:
                total = reported
            if not rows:
                break
            for product in rows:
                status = status_of(product)
                if not status:
                    continue
                pid = str(product.get("_id") or product.get("id") or "")
                if not pid:
                    continue
                seen.append(pid)
                if status == "tugagan":
                    out += 1
                else:
                    low += 1
                threshold = threshold_of(product)
                db.run(
                    "INSERT INTO stock_item (tenant_id, product_id, name, sku, "
                    "  category, measure, amount, threshold, status, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now')) "
                    "ON CONFLICT (tenant_id, product_id) DO UPDATE SET "
                    "  name = excluded.name, sku = excluded.sku, "
                    "  category = excluded.category, measure = excluded.measure, "
                    "  amount = excluded.amount, threshold = excluded.threshold, "
                    "  status = excluded.status, updated_at = excluded.updated_at",
                    (tid, pid, product.get("name"), product.get("sku"),
                     category_of(product), measure_of(product),
                     amount_of(product), threshold, status),
                )
            if len(rows) < PAGE_LIMIT:
                break
            page += 1
    except BitoError as e:
        db.run("UPDATE stock_scan SET error = ?, pages_done = ? WHERE tenant_id = ?",
               (e.user_message, page - 1, tid))
        raise

    # Endi chegaradan yuqoriga chiqqanlarni keshdan olib tashlash
    if seen:
        marks = ",".join("?" * len(seen))
        db.run(
            f"DELETE FROM stock_item WHERE tenant_id = ? "
            f"AND product_id NOT IN ({marks})",
            (tid, *seen),
        )
    else:
        db.run("DELETE FROM stock_item WHERE tenant_id = ?", (tid,))

    db.run(
        "UPDATE stock_scan SET finished_at = datetime('now'), total_products = ?, "
        "  low_count = ?, out_count = ?, pages_done = ? WHERE tenant_id = ?",
        (total, low, out, page, tid),
    )
    return {"total": total, "low": low, "out": out, "pages": page,
            "truncated": page > max_pages}


def low_items(status=None, limit=30):
    sql = ("SELECT * FROM stock_item WHERE tenant_id = ?"
           + (" AND status = ?" if status else "")
           + " ORDER BY status, amount, name LIMIT ?")
    params = [ctx.require()] + ([status] if status else []) + [limit]
    return db.rows(sql, tuple(params))


def counts():
    row = db.row(
        "SELECT COUNT(*) AS all_low, "
        "  SUM(status = 'tugagan') AS out, SUM(status = 'kam') AS low "
        "FROM stock_item WHERE tenant_id = ?",
        (ctx.require(),),
    )
    return {"all": row["all_low"] or 0, "out": row["out"] or 0,
            "low": row["low"] or 0}


# ------------------------------------------------------------------ qidiruv


def search(text, client=None):
    """Jonli qidiruv — bitta so'rov, keshsiz."""
    client = client or bito.client()
    rows, _ = client.products(page=1, limit=SEARCH_LIMIT, search=text.strip())
    out = []
    for product in rows:
        out.append({
            "id": str(product.get("_id") or ""),
            "name": product.get("name") or "—",
            "sku": product.get("sku") or "",
            "amount": amount_of(product),
            "measure": measure_of(product),
            "category": category_of(product),
            "threshold": threshold_of(product),
            "status": status_of(product),
        })
    return out


# -------------------------------------------------------------------- modul


@registry.implement("ombor")
class Ombor(base.Module):
    def menu(self, role):
        return [("📦 Ombor", "mod:ombor:panel")]

    def register(self, bot, guard):
        _register(bot, guard)

    def jobs(self):
        # Kuniga bir marta — katalog kun davomida kam o'zgaradi
        return [("ombor_scan", lambda: scan(), 24 * 3600)]


def _register(bot, guard):
    @bot.callback_query_handler(
        func=lambda c: (c.data or "").startswith("mod:ombor:"))
    @guard
    def _click(call):
        ui.ack(bot, call)
        action = call.data.split(":", 2)[2]
        chat_id, tg_id = call.message.chat.id, call.from_user.id

        if action == "panel":
            _panel(bot, chat_id, tg_id)
        elif action in ("tugagan", "kam", "hammasi"):
            _list(bot, chat_id, tg_id, action)
        elif action == "qidir":
            sessions.set(tg_id, "ombor:qidir", {})
            bot.send_message(
                chat_id,
                "Mahsulot nomini, SKU yoki shtrix-kodini yozing.",
            )
        elif action == "yangila":
            _refresh(bot, chat_id, tg_id)

    @bot.message_handler(
        func=lambda m: sessions.get_global(m.from_user.id)[0] == "ombor:qidir",
        content_types=["text"])
    @guard
    def _search(message):
        sessions.clear(message.from_user.id)
        text = (message.text or "").strip()
        if len(text) < 2:
            bot.send_message(message.chat.id, "Kamida ikki belgi yozing.")
            return
        rows = search(text)
        if not rows:
            bot.send_message(
                message.chat.id,
                f"«{ui.escape(text)}» bo'yicha hech narsa topilmadi.",
                parse_mode="HTML",
                reply_markup=ui.buttons([("🔍 Yana qidirish", "mod:ombor:qidir")],
                                        back="mod:ombor:panel"))
            return
        lines = [f"<b>Qidiruv:</b> {ui.escape(text)}", ""]
        for row in rows:
            mark = {"tugagan": "🔴", "kam": "🟡"}.get(row["status"], "🟢")
            amount = (f"{row['amount']:g}" if row["amount"] % 1
                      else f"{int(row['amount'])}")
            lines.append(
                f"{mark} <b>{ui.escape(row['name'])}</b>\n"
                f"    {amount} {ui.escape(row['measure'])}"
                + (f" · {ui.escape(row['category'])}" if row["category"] else "")
                + (f" · SKU {ui.escape(row['sku'])}" if row["sku"] else "")
            )
        for chunk in ui.chunks("\n".join(lines)):
            bot.send_message(message.chat.id, chunk, parse_mode="HTML")
        bot.send_message(
            message.chat.id, "Yana qidirasizmi?",
            reply_markup=ui.buttons([("🔍 Yana qidirish", "mod:ombor:qidir")],
                                    back="mod:ombor:panel"))


def _panel(bot, chat_id, tg_id):
    state = scan_state()
    stats = counts()
    lines = ["<b>Ombor</b>", ""]

    if not state["finished_at"]:
        lines.append("Hali skanerlanmagan. «Yangilash» tugmasini bosing.")
    else:
        lines.append(f"🔴 Tugagan: {stats['out']} ta")
        lines.append(f"🟡 Kam qolgan: {stats['low']} ta")
        if state["total_products"]:
            lines.append(f"Katalogda: {state['total_products']} ta mahsulot")
        lines.append("")
        lines.append(f"Oxirgi tekshiruv: {state['finished_at']} UTC")

    if state["error"]:
        lines.append(f"\n⚠️ Oxirgi skanerda xato: {ui.escape(state['error'])}")

    if not tenant.get("low_stock_default"):
        lines.append(
            "\nℹ️ «Kam qolgan» chegarasi Bito'dagi qizil chiziqdan olinadi. "
            "U to'ldirilmagan bo'lsa faqat tugaganlar ko'rinadi."
        )

    buttons = [("🔴 Tugaganlar", "mod:ombor:tugagan"),
               ("🟡 Kam qolganlar", "mod:ombor:kam"),
               ("🔍 Qidirish", "mod:ombor:qidir")]
    if users.role_of(tg_id) in ("owner", "manager"):
        buttons.append(("🔄 Yangilash", "mod:ombor:yangila"))
    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML",
                     reply_markup=ui.buttons(buttons, back="menu:root"))


def _list(bot, chat_id, tg_id, kind):
    status = None if kind == "hammasi" else kind
    rows = low_items(status=status)
    titles = {"tugagan": "Tugaganlar", "kam": "Kam qolganlar",
              "hammasi": "Diqqat talab qiladiganlar"}
    if not rows:
        bot.send_message(chat_id, f"{titles[kind]}: ro'yxat bo'sh. 👍",
                         reply_markup=ui.buttons([], back="mod:ombor:panel"))
        return
    lines = [f"<b>{titles[kind]}</b> — {len(rows)} ta", ""]
    lines += [fmt(row) for row in rows]
    if len(rows) >= 30:
        lines.append("\n(Birinchi 30 tasi ko'rsatildi.)")
    for chunk in ui.chunks("\n".join(lines)):
        bot.send_message(chat_id, chunk, parse_mode="HTML")
    bot.send_message(chat_id, "—",
                     reply_markup=ui.buttons([], back="mod:ombor:panel"))


def _refresh(bot, chat_id, tg_id):
    users.require_role(tg_id, "manager")
    bot.send_message(chat_id, "Skanerlash boshlandi, bir necha daqiqa olishi "
                              "mumkin…")
    result = scan()
    text = (f"✅ Tayyor.\n\n"
            f"🔴 Tugagan: {result['out']} ta\n"
            f"🟡 Kam qolgan: {result['low']} ta")
    if result["total"]:
        text += f"\nKatalogda: {result['total']} ta mahsulot"
    if result["truncated"]:
        text += ("\n\n⚠️ Katalog juda katta — hammasi ko'rilmadi. "
                 "Kategoriya bo'yicha bo'lib skanerlash kerak.")
    bot.send_message(chat_id, text,
                     reply_markup=ui.buttons([], back="mod:ombor:panel"))
