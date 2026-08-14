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
from .. import bito, catalog, ctx, db, sessions, tenant, ui, users
from ..errors import BitoError, BotError

log = logging.getLogger(__name__)


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

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
                # Katalog keshi ayni shu o'tishda to'ldiriladi — nakladnoy
                # moslashtirishi uchun. Ikkinchi marta varaqlash kerak emas.
                product["_amount"] = amount_of(product)
                catalog.upsert(product)

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
            "truncated": page > max_pages, "catalog": catalog.size()}


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


# ------------------------------------------------- zarur mahsulotlar
# market-bot tengligi (PARITY 3-band). Jamoaviy «tugayapti» ro'yxati:
# xodim ham qo'shadi, xodim faqat o'zinikini o'chiradi. Bito'da bor
# mahsulot kuzatiladi — qoldiq baseline'dan oshsa «keldi», qator o'chadi
# va qo'shgan odamga xabar boradi.

EXPECTED_CHOICES = [("bugun", "Bugun"), ("ertaga", "Ertaga"),
                    ("hafta", "Shu hafta"), ("nomalum", "Noma'lum")]

_NOTIFY_BOT = None      # _register da to'ldiriladi — fon ishi xabar uchun


def zarur_rows():
    return db.rows(
        "SELECT * FROM zarur WHERE tenant_id = ? "
        "ORDER BY stars DESC, id", (ctx.require(),))


def zarur_text():
    rows = zarur_rows()
    if not rows:
        return "🛒 Zarur mahsulotlar ro'yxati bo'sh."
    lines = ["🛒 <b>Zarur mahsulotlar</b> (yulduz bo'yicha)", ""]
    for i, row in enumerate(rows, 1):
        mark = "📦" if row["product_id"] else "✏️"
        who = users.get(row["added_by"])
        who_s = f" — {ui.escape(who['name'])}" if who and who["name"] else ""
        exp = (f" · ⏰ {ui.escape(row['expected'])}"
               if row["expected"] and row["expected"] != "Noma'lum" else "")
        lines.append(f"{i}. {'⭐' * (row['stars'] or 3)}\n"
                     f"   {mark} {ui.escape(row['name'])}{exp}{who_s}")
    lines += ["", "📦 — Bito'da bor (kelsa o'zi o'chadi) · ✏️ — faqat "
                  "ma'lumot"]
    return "\n".join(lines)


def zarur_add(entries, stars, expected, tg_id):
    """entries: [{product_id|None, name}]. Qaytadi: nechta qo'shildi."""
    stars = max(1, min(5, int(stars or 3)))
    for entry in entries:
        db.run(
            "INSERT INTO zarur (tenant_id, product_id, name, stars, "
            "  expected, added_by) VALUES (?, ?, ?, ?, ?, ?)",
            (ctx.require(), entry.get("product_id"),
             str(entry["name"]).strip()[:80], stars,
             (expected or "Noma'lum")[:40], tg_id),
        )
    return len(entries)


def zarur_delete(row_id, tg_id):
    """Xodim faqat o'zinikini, menejer/egasi hammasini o'chiradi."""
    row = db.row("SELECT * FROM zarur WHERE tenant_id = ? AND id = ?",
                 (ctx.require(), row_id))
    if not row:
        raise BotError("Qator topilmadi.")
    role = "owner" if users.is_seller(tg_id) else users.role_of(tg_id)
    if role not in ("owner", "manager") and row["added_by"] != tg_id:
        raise BotError("Faqat o'zingiz qo'shgan qatorni o'chira olasiz.")
    db.run("DELETE FROM zarur WHERE tenant_id = ? AND id = ?",
           (ctx.require(), row_id))
    return row["name"]


def _live_amount(client, product_id, name_hint):
    """Bitta mahsulotning jonli qoldig'i — qidiruv orqali."""
    try:
        rows, _total = client.products(page=1, limit=5,
                                       search=(name_hint or "")[:40])
    except BitoError:
        return None
    for product in rows or []:
        if not isinstance(product, dict):
            continue
        if str(product.get("_id")) != str(product_id):
            continue
        warehouses = (product.get("_warehouses")
                      or product.get("warehouses") or {})
        if isinstance(warehouses, dict):
            return sum(_num(w.get("amount")) for w in warehouses.values()
                       if isinstance(w, dict))
        if isinstance(warehouses, list):
            return sum(_num(w.get("amount")) for w in warehouses
                       if isinstance(w, dict))
        return _num(product.get("in_stock"))
    return None


def zarur_arrival_check(client=None, notify=None):
    """Fon ishi: kelganlarni aniqlab o'chiradi.

    Baseline qoidasi (market-bot): birinchi tekshiruvda joriy qoldiq
    YOZILADI, hech narsa o'chmaydi. Keyingisida qoldiq oshsa — keldi.
    Ro'yxat bo'sh bo'lsa Bito'ga so'rov ketmaydi.
    """
    rows = db.rows("SELECT * FROM zarur WHERE tenant_id = ? "
                   "AND product_id IS NOT NULL", (ctx.require(),))
    if not rows:
        return []
    client = client or bito.client()
    arrived = []
    for row in rows:
        current = _live_amount(client, row["product_id"], row["name"])
        if current is None:
            continue
        if row["baseline"] is None:
            db.run("UPDATE zarur SET baseline = ? WHERE tenant_id = ? "
                   "AND id = ?", (current, ctx.require(), row["id"]))
            continue
        if current > _num(row["baseline"]) + 0.001:
            db.run("DELETE FROM zarur WHERE tenant_id = ? AND id = ?",
                   (ctx.require(), row["id"]))
            arrived.append({"name": row["name"], "added_by": row["added_by"],
                            "was": _num(row["baseline"]), "now": current})
            if notify:
                try:
                    notify(arrived[-1])
                except Exception:  # noqa: BLE001
                    log.warning("Zarur xabari ketmadi", exc_info=True)
    return arrived


def _zarur_job():
    """30 daqiqalik kuzatuv — xabarlar qo'shgan odamga va egalarga."""
    bot = _NOTIFY_BOT

    def tell(item):
        if not bot:
            return
        text = (f"✅ 🛒 <b>{ui.escape(item['name'])}</b> keldi "
                f"({item['was']:g} → {item['now']:g}) — zarur ro'yxatidan "
                "o'chirildi.")
        targets = {item["added_by"]}
        targets.update(u["tg_id"] for u in users.listing()
                       if u["role"] in ("owner", "manager"))
        for target in targets:
            try:
                bot.send_message(target, text, parse_mode="HTML")
            except Exception:  # noqa: BLE001
                pass

    zarur_arrival_check(notify=tell)



@registry.implement("ombor")
class Ombor(base.Module):
    def menu(self, role):
        if role == "staff":
            return [("🛒 Zarur mahsulotlar", "mod:ombor:zr")]
        return [("📦 Ombor", "mod:ombor:panel"),
                ("🛒 Zarur mahsulotlar", "mod:ombor:zr")]

    def register(self, bot, guard):
        _register(bot, guard)

    def jobs(self):
        # Kuniga bir marta — katalog kun davomida kam o'zgaradi
        return [("ombor_scan", lambda: scan(), 24 * 3600),
                ("zarur_kuzatuv", lambda: _zarur_job(), 1800)]


def _register(bot, guard):
    global _NOTIFY_BOT
    _NOTIFY_BOT = bot          # fon kuzatuvchisi xabar yuborishi uchun

    @bot.callback_query_handler(
        func=lambda c: (c.data or "").startswith("mod:ombor:"))
    @guard
    def _click(call):
        ui.ack(bot, call)
        action = call.data.split(":", 2)[2]
        chat_id, tg_id = call.message.chat.id, call.from_user.id

        # Zarur ro'yxati — xodimga ham ochiq, rol tekshiruvidan OLDIN
        if action == "zr":
            bot.send_message(chat_id, zarur_text(), parse_mode="HTML",
                             reply_markup=ui.buttons(
                                 [("➕ Qo'shish", "mod:ombor:zr_add"),
                                  ("🗑 O'chirish", "mod:ombor:zr_del")],
                                 row_width=2, back="menu:root"))
            return
        if action == "zr_add":
            sessions.set(tg_id, "ombor:zarur_nom", {})
            bot.send_message(chat_id,
                             "Mahsulot nomini yozing (Bito'dan qidiraman):")
            return
        if action == "zr_del":
            role = ("owner" if users.is_seller(tg_id)
                    else users.role_of(tg_id))
            buttons = []
            for row in zarur_rows()[:25]:
                if role in ("owner", "manager") or row["added_by"] == tg_id:
                    buttons.append((f"🗑 {row['name'][:42]}",
                                    f"mod:ombor:zr_delc_{row['id']}"))
            if not buttons:
                bot.send_message(chat_id, "O'chiradigan qatoringiz yo'q.")
                return
            bot.send_message(chat_id, "Qaysi qatorni o'chiray?",
                             reply_markup=ui.buttons(buttons, row_width=1,
                                                     back="mod:ombor:zr"))
            return
        if action.startswith("zr_delc_"):
            name = zarur_delete(int(action[8:]), tg_id)
            bot.send_message(chat_id, f"🗑 «{ui.escape(name)}» o'chirildi.",
                             parse_mode="HTML")
            return
        if action.startswith("zr_p_") or action == "zr_free":
            state, data = sessions.get_global(tg_id)
            if state != "ombor:zarur_tanlov":
                bot.send_message(chat_id, "Tanlov eskirgan — qaytadan.")
                return
            if action == "zr_free":
                data["free"] = not data.get("free")
            else:
                j = int(action[5:])
                sel = set(data.get("sel") or [])
                sel.symmetric_difference_update({j})
                data["sel"] = sorted(sel)
            sessions.set(tg_id, state, data)
            try:
                bot.edit_message_reply_markup(
                    chat_id, call.message.message_id,
                    reply_markup=_zarur_cand_kb(data))
            except Exception:  # noqa: BLE001
                pass
            return
        if action == "zr_ok":
            state, data = sessions.get_global(tg_id)
            if state != "ombor:zarur_tanlov":
                bot.send_message(chat_id, "Tanlov eskirgan — qaytadan.")
                return
            entries = [{"product_id": data["cands"][j]["product_id"],
                        "name": data["cands"][j]["name"]}
                       for j in (data.get("sel") or [])]
            if data.get("free"):
                entries.append({"product_id": None,
                                "name": data.get("nom") or "?"})
            if not entries:
                bot.send_message(chat_id, "Hech narsa tanlanmadi — mahsulot "
                                          "tugmasini yoki ✏️ ni bosing.")
                return
            data["entries"] = entries
            sessions.set(tg_id, "ombor:zarur_yulduz", data)
            bot.send_message(chat_id, "Muhimligi qancha?",
                             reply_markup=ui.buttons(
                                 [("⭐" * n, f"mod:ombor:zr_s_{n}")
                                  for n in range(1, 6)], row_width=5))
            return
        if action.startswith("zr_s_"):
            state, data = sessions.get_global(tg_id)
            if state != "ombor:zarur_yulduz":
                return
            data["stars"] = int(action[5:])
            sessions.set(tg_id, "ombor:zarur_muddat", data)
            bot.send_message(chat_id,
                             "Qachon kelishi kutilmoqda? (yoki sanani "
                             "yozib yuboring)",
                             reply_markup=ui.buttons(
                                 [(label, f"mod:ombor:zr_e_{code}")
                                  for code, label in EXPECTED_CHOICES],
                                 row_width=2))
            return
        if action.startswith("zr_e_"):
            label = dict(EXPECTED_CHOICES).get(action[5:], "Noma'lum")
            _zarur_finish(bot, chat_id, tg_id, label)
            return

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
        func=lambda m: sessions.get_global(m.from_user.id)[0]
        == "ombor:zarur_nom",
        content_types=["text"])
    @guard
    def _zarur_nom(message):
        tg_id = message.from_user.id
        query = (message.text or "").strip()
        if not query:
            return
        found = catalog.match(query)
        cands = found.get("candidates") or []
        if found.get("product_id") and not any(
                c["product_id"] == found["product_id"] for c in cands):
            cands = [{"product_id": found["product_id"],
                      "name": found["product_name"]}] + cands
        data = {"nom": query, "cands": cands[:6], "sel": [], "free": False}
        sessions.set(tg_id, "ombor:zarur_tanlov", data)
        bot.send_message(
            message.chat.id,
            ("Bito'dan topilganlar — bir nechtasini tanlash mumkin, "
             "keyin «Bo'ldi»:" if cands else
             "Bito'da topilmadi — ✏️ ni tanlab «Bo'ldi» bosing:"),
            reply_markup=_zarur_cand_kb(data))

    @bot.message_handler(
        func=lambda m: sessions.get_global(m.from_user.id)[0]
        == "ombor:zarur_muddat",
        content_types=["text"])
    @guard
    def _zarur_muddat(message):
        _zarur_finish(bot, message.chat.id, message.from_user.id,
                      (message.text or "").strip()[:40] or "Noma'lum")

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


def _zarur_cand_kb(data):
    """Nomzodlar: tanlanganlar ☑️. Telegram tugma holat saqlamaydi —
    har bosishda qayta quriladi."""
    sel = set(data.get("sel") or [])
    buttons = []
    for j, candidate in enumerate(data.get("cands") or []):
        mark = "☑️ " if j in sel else "📦 "
        buttons.append((mark + candidate["name"][:44], f"mod:ombor:zr_p_{j}"))
    free_mark = "☑️ " if data.get("free") else "✏️ "
    buttons.append((free_mark + "Bito'da yo'q — shunday yozib qo'y",
                    "mod:ombor:zr_free"))
    count = len(sel) + (1 if data.get("free") else 0)
    buttons.append((f"✅ Bo'ldi ({count} ta)", "mod:ombor:zr_ok"))
    return ui.buttons(buttons, row_width=1)


def _zarur_finish(bot, chat_id, tg_id, expected):
    state, data = sessions.get_global(tg_id)
    if state != "ombor:zarur_muddat":
        return
    sessions.clear(tg_id)
    entries = data.get("entries") or []
    stars = data.get("stars", 3)
    count = zarur_add(entries, stars, expected, tg_id)
    names = "\n".join(
        ("📦 " if e.get("product_id") else "✏️ ") + ui.escape(e["name"])
        for e in entries)
    bot.send_message(chat_id,
                     f"✅ {count} ta qo'shildi {'⭐' * stars} · "
                     f"⏰ {ui.escape(expected)}:\n{names}",
                     parse_mode="HTML",
                     reply_markup=ui.buttons(
                         [("➕ Yana qo'shish", "mod:ombor:zr_add"),
                          ("📋 Ro'yxat", "mod:ombor:zr")], row_width=2))
    # Xodim qo'shsa — rahbarlarga xabar
    role = "owner" if users.is_seller(tg_id) else users.role_of(tg_id)
    if role not in ("owner", "manager"):
        who = users.get(tg_id)
        who_name = (who["name"] if who else None) or str(tg_id)
        for user in users.listing():
            if user["role"] in ("owner", "manager"):
                try:
                    bot.send_message(
                        user["tg_id"],
                        f"🛒 {ui.escape(who_name)} zarur ro'yxatiga "
                        f"{count} ta qo'shdi {'⭐' * stars}:\n{names}",
                        parse_mode="HTML")
                except Exception:  # noqa: BLE001
                    pass
