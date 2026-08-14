"""Inventarizatsiya moduli: telefonda sanash.

Sanash **mahalliy** olib boriladi, Bito'ga faqat oxirida yoziladi.

Sabab market-bot'dan: Bito'da `done` holati qoldiqni **qaytarib
bo'lmaydigan** tarzda o'zgartiradi. Yarim sanalgan ro'yxat yuborilsa,
sanalmagan mahsulotlar nolga tushib qoladi va do'kon ombori buziladi.
Shuning uchun yuklash aniq tasdiq bilan, bitta amalda.

`starting_date` majburiy — aks holda Bito 400 qaytaradi (2026-08-01).
"""

import datetime as dt
import logging

from . import base, registry
from .. import bito, catalog, ctx, db, sessions, tenant, ui, users
from ..errors import BitoError, BotError

log = logging.getLogger(__name__)

ADD_CHUNK = 100


# ------------------------------------------------------------------- sanash


def start(tg_id, title=None):
    active = current()
    if active:
        raise BotError("Tugallanmagan inventarizatsiya bor. Avval uni "
                       "yakunlang yoki bekor qiling.")
    cur = db.run(
        "INSERT INTO stock_take (tenant_id, started_by, title) VALUES (?, ?, ?)",
        (ctx.require(), tg_id, title or f"Sanoq {dt.date.today():%d.%m.%Y}"),
    )
    return cur.lastrowid


def current():
    return db.row(
        "SELECT * FROM stock_take WHERE tenant_id = ? AND status = 'sanalmoqda' "
        "ORDER BY created_at DESC LIMIT 1",
        (ctx.require(),),
    )


def get(take_id):
    return db.row("SELECT * FROM stock_take WHERE tenant_id = ? AND id = ?",
                  (ctx.require(), take_id))


def count(take_id, product_id, amount, tg_id=None):
    """Sanalgan sonni yozadi. Takroriy sanash — almashtirish, qo'shish emas."""
    row = db.row("SELECT name, measure, amount FROM catalog "
                 "WHERE tenant_id = ? AND product_id = ?",
                 (ctx.require(), product_id))
    if not row:
        raise BotError("Mahsulot katalogda topilmadi. Ombor → Yangilash.")
    db.run(
        "INSERT INTO stock_take_item (tenant_id, take_id, product_id, name, "
        "  measure, expected, counted, counted_by, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now')) "
        "ON CONFLICT (tenant_id, take_id, product_id) DO UPDATE SET "
        "  counted = excluded.counted, counted_by = excluded.counted_by, "
        "  updated_at = excluded.updated_at",
        (ctx.require(), take_id, product_id, row["name"], row["measure"],
         float(row["amount"] or 0), float(amount), tg_id),
    )
    return db.row(
        "SELECT * FROM stock_take_item WHERE tenant_id = ? AND take_id = ? "
        "AND product_id = ?", (ctx.require(), take_id, product_id))


def items(take_id, only_diff=False):
    sql = ("SELECT * FROM stock_take_item WHERE tenant_id = ? AND take_id = ?")
    params = [ctx.require(), take_id]
    if only_diff:
        sql += " AND counted != expected"
    sql += " ORDER BY (counted - expected), name"
    return db.rows(sql, tuple(params))


def remove(take_id, product_id):
    db.run("DELETE FROM stock_take_item WHERE tenant_id = ? AND take_id = ? "
           "AND product_id = ?", (ctx.require(), take_id, product_id))


def summary(take_id):
    rows = items(take_id)
    surplus = [r for r in rows if r["counted"] > r["expected"]]
    shortage = [r for r in rows if r["counted"] < r["expected"]]
    return {
        "count": len(rows),
        "surplus": len(surplus),
        "shortage": len(shortage),
        "match": len(rows) - len(surplus) - len(shortage),
        "surplus_qty": sum(r["counted"] - r["expected"] for r in surplus),
        "shortage_qty": sum(r["expected"] - r["counted"] for r in shortage),
    }


def cancel(take_id):
    db.run("UPDATE stock_take SET status = 'bekor', "
           "  finished_at = datetime('now') WHERE tenant_id = ? AND id = ?",
           (ctx.require(), take_id))


def finish(take_id):
    """Sanashni yopadi. Bito'ga hali yozilmaydi."""
    if not items(take_id):
        raise BotError("Birorta mahsulot sanalmagan.")
    db.run("UPDATE stock_take SET status = 'yakunlandi', "
           "  finished_at = datetime('now') WHERE tenant_id = ? AND id = ?",
           (ctx.require(), take_id))
    return get(take_id)


# ------------------------------------------------------------- Bito'ga yozish


def _now_iso():
    return dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000Z")


def upload(take_id, client=None):
    """Bito'da inventarizatsiya yaratadi va yakunlaydi.

    Uch qadam: create → add-products → set-status done.
    Oxirgi qadam qoldiqni o'zgartiradi va qaytarib bo'lmaydi.
    """
    take = get(take_id)
    if not take:
        raise BotError("Sanoq topilmadi.")
    if take["status"] == "yuklandi":
        raise BotError("Bu sanoq allaqachon yuklangan.")
    rows = items(take_id)
    if not rows:
        raise BotError("Birorta mahsulot sanalmagan.")

    client = client or bito.client()
    now = _now_iso()
    body = {
        "organization_id": tenant.require("bito_org_id"),
        "warehouse_id": tenant.require("warehouse_id"),
        "responsible_id": tenant.get("bito_responsible_id"),
        # Majburiy: busiz Bito 400 qaytaradi
        "starting_date": now,
        "ending_date": now,
        "description": take["title"] or "Bot inventarizatsiyasi",
        "set_counted": True,
    }
    resp = client.create_revision(body)
    if resp.status_code not in (200, 201):
        detail = _detail(resp)
        _fail(take_id, detail)
        raise BitoError(f"Inventarizatsiya yaratilmadi. {detail}")

    try:
        data = (resp.json() or {}).get("data") or {}
    except ValueError:
        data = {}
    revision_id = data.get("_id")
    if not revision_id:
        _fail(take_id, "javobda _id yo'q")
        raise BitoError("Bito javobida inventarizatsiya raqami yo'q.")

    db.run("UPDATE stock_take SET bito_id = ?, bito_number = ? "
           "WHERE tenant_id = ? AND id = ?",
           (revision_id, str(data.get("number") or ""), ctx.require(), take_id))

    # Mahsulotlarni bo'lib qo'shamiz — katta ro'yxat uzilib qolmasin
    for start_at in range(0, len(rows), ADD_CHUNK):
        chunk = rows[start_at:start_at + ADD_CHUNK]
        add_body = {
            "products": [{"product_id": row["product_id"],
                          "counted": row["counted"],
                          "amount": row["counted"]} for row in chunk],
        }
        add_resp = client.revision_add(revision_id, add_body)
        if add_resp.status_code not in (200, 201):
            detail = _detail(add_resp)
            _fail(take_id, detail)
            raise BitoError(
                f"Mahsulotlar qo'shilmadi. {detail}\n\n"
                f"Bito'da №{data.get('number') or revision_id} "
                "inventarizatsiyasi ochiq qoldi — uni Bito ichida yakunlang "
                "yoki bekor qiling.")

    status_resp = client.revision_status(revision_id, "done")
    if status_resp.status_code not in (200, 201):
        detail = _detail(status_resp)
        _fail(take_id, detail)
        raise BitoError(
            f"Yakunlab bo'lmadi. {detail}\n\nMahsulotlar qo'shildi, lekin "
            "qoldiq o'zgarmadi. Bito ichida «Yakunlash» tugmasini bosing.")

    db.run("UPDATE stock_take SET status = 'yuklandi', error = NULL, "
           "  finished_at = datetime('now') WHERE tenant_id = ? AND id = ?",
           (ctx.require(), take_id))
    return {"revision_id": revision_id,
            "number": data.get("number"), "count": len(rows)}


def _detail(resp):
    try:
        payload = resp.json()
    except ValueError:
        return f"HTTP {resp.status_code}: {resp.text[:120]}"
    if isinstance(payload, dict):
        message = payload.get("message") or payload.get("error")
        if message:
            return f"HTTP {resp.status_code}: {str(message)[:120]}"
    return f"HTTP {resp.status_code}"


def _fail(take_id, message):
    db.run("UPDATE stock_take SET error = ? WHERE tenant_id = ? AND id = ?",
           (str(message)[:300], ctx.require(), take_id))


# -------------------------------------------------------------------- modul


@registry.implement("inventarizatsiya")
class Inventarizatsiya(base.Module):
    def menu(self, role):
        return [("📋 Inventarizatsiya", "mod:inv:panel")]

    def register(self, bot, guard):
        _register(bot, guard)


def _register(bot, guard):
    @bot.callback_query_handler(
        func=lambda c: (c.data or "").startswith("mod:inv:"))
    @guard
    def _click(call):
        ui.ack(bot, call)
        action = call.data.split(":", 2)[2]
        chat_id, tg_id = call.message.chat.id, call.from_user.id

        if action == "panel":
            _panel(bot, chat_id, tg_id)
        elif action == "boshla":
            users.require_role(tg_id, "manager")
            take_id = start(tg_id)
            bot.send_message(
                chat_id,
                "Sanoq boshlandi.\n\nMahsulot nomini yoki shtrix-kodini "
                "yozing, keyin sanalgan sonni.")
            _count_mode(bot, chat_id, tg_id, take_id)
        elif action.startswith("sana_"):
            _count_mode(bot, chat_id, tg_id, int(action.split("_")[1]))
        elif action.startswith("tanla_"):
            _, take_id, product_id = action.split("_", 2)
            sessions.set(tg_id, "inv:son",
                         {"take_id": int(take_id), "product_id": product_id})
            row = db.row("SELECT name FROM catalog WHERE tenant_id = ? "
                         "AND product_id = ?", (ctx.require(), product_id))
            bot.send_message(
                chat_id,
                f"<b>{ui.escape(row['name'] if row else '—')}</b>\n"
                "Nechta bor? Sonni yozing.",
                parse_mode="HTML")
        elif action.startswith("royxat_"):
            _list(bot, chat_id, tg_id, int(action.split("_")[1]))
        elif action.startswith("yakun_"):
            _finish(bot, chat_id, tg_id, int(action.split("_")[1]))
        elif action.startswith("yukla_"):
            _confirm_upload(bot, chat_id, tg_id, int(action.split("_")[1]))
        elif action.startswith("haqiqatan_"):
            _upload(bot, chat_id, tg_id, int(action.split("_")[1]))
        elif action.startswith("bekor_"):
            users.require_role(tg_id, "manager")
            cancel(int(action.split("_")[1]))
            bot.send_message(chat_id, "Sanoq bekor qilindi. Bito'ga hech "
                                      "narsa yozilmadi.",
                             reply_markup=ui.main_menu(tg_id))

    @bot.message_handler(
        func=lambda m: (sessions.get_global(m.from_user.id)[0] or "")
        .startswith("inv:"),
        content_types=["text"])
    @guard
    def _input(message):
        state, data = sessions.get_global(message.from_user.id)
        sessions.clear(message.from_user.id)
        _apply(bot, message, state, data)


def _apply(bot, message, state, data):
    chat_id, tg_id = message.chat.id, message.from_user.id
    text = (message.text or "").strip()
    take_id = data.get("take_id")

    if state == "inv:qidir":
        rows = db.rows(
            "SELECT product_id, name, barcodes FROM catalog "
            "WHERE tenant_id = ? AND (key LIKE ? OR barcodes LIKE ? "
            "OR sku = ?) LIMIT 8",
            (ctx.require(), f"%{catalog.normalize(text)}%", f"%{text}%", text))
        if not rows:
            bot.send_message(chat_id, f"«{ui.escape(text)}» topilmadi.",
                             parse_mode="HTML")
            _count_mode(bot, chat_id, tg_id, take_id)
            return
        if len(rows) == 1:
            sessions.set(tg_id, "inv:son",
                         {"take_id": take_id,
                          "product_id": rows[0]["product_id"]})
            bot.send_message(chat_id,
                             f"<b>{ui.escape(rows[0]['name'])}</b>\n"
                             "Nechta bor? Sonni yozing.",
                             parse_mode="HTML")
            return
        bot.send_message(
            chat_id, "Qaysi mahsulot?",
            reply_markup=ui.buttons(
                [(row["name"][:45],
                  f"mod:inv:tanla_{take_id}_{row['product_id']}")
                 for row in rows], row_width=1))
        return

    if state == "inv:son":
        try:
            amount = float(text.replace(",", "."))
        except ValueError:
            bot.send_message(chat_id, "Faqat raqam yozing.")
            sessions.set(tg_id, "inv:son", data)
            return
        row = count(take_id, data["product_id"], amount, tg_id)
        diff = row["counted"] - row["expected"]
        mark = "✅" if abs(diff) < 0.001 else ("🟢" if diff > 0 else "🔴")
        line = (f"{mark} {ui.escape(row['name'] or '—')}: "
                f"sanaldi {row['counted']:g}, bazada {row['expected']:g}")
        if abs(diff) >= 0.001:
            line += f" ({diff:+g})"
        bot.send_message(chat_id, line, parse_mode="HTML")
        _count_mode(bot, chat_id, tg_id, take_id)


def _count_mode(bot, chat_id, tg_id, take_id):
    sessions.set(tg_id, "inv:qidir", {"take_id": take_id})
    numbers = summary(take_id)
    bot.send_message(
        chat_id,
        f"Sanalgan: {numbers['count']} ta · farqli: "
        f"{numbers['surplus'] + numbers['shortage']} ta\n\n"
        "Keyingi mahsulot nomini yoki shtrix-kodini yozing.",
        reply_markup=ui.buttons(
            [("📄 Ro'yxat", f"mod:inv:royxat_{take_id}"),
             ("🏁 Yakunlash", f"mod:inv:yakun_{take_id}"),
             ("🗑 Bekor qilish", f"mod:inv:bekor_{take_id}")],
            row_width=1))


def _list(bot, chat_id, tg_id, take_id):
    rows = items(take_id)
    if not rows:
        bot.send_message(chat_id, "Hali hech narsa sanalmagan.")
        _count_mode(bot, chat_id, tg_id, take_id)
        return
    lines = [f"<b>Sanalgan</b> — {len(rows)} ta", ""]
    for row in rows:
        diff = row["counted"] - row["expected"]
        mark = "✅" if abs(diff) < 0.001 else ("🟢" if diff > 0 else "🔴")
        lines.append(f"{mark} {ui.escape(row['name'] or '—')}: "
                     f"{row['counted']:g} / {row['expected']:g}"
                     + (f" ({diff:+g})" if abs(diff) >= 0.001 else ""))
    for chunk in ui.chunks("\n".join(lines)):
        bot.send_message(chat_id, chunk, parse_mode="HTML")
    _count_mode(bot, chat_id, tg_id, take_id)


def _finish(bot, chat_id, tg_id, take_id):
    users.require_role(tg_id, "manager")
    sessions.clear(tg_id)
    finish(take_id)
    numbers = summary(take_id)
    lines = [
        "<b>Sanoq yakunlandi</b>", "",
        f"Jami sanalgan: {numbers['count']} ta",
        f"✅ Mos keldi: {numbers['match']} ta",
        f"🟢 Ortiqcha: {numbers['surplus']} ta ({numbers['surplus_qty']:+g})",
        f"🔴 Kam chiqdi: {numbers['shortage']} ta "
        f"(−{numbers['shortage_qty']:g})",
        "", "Bito'ga hali yozilmadi.",
    ]
    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML",
                     reply_markup=ui.buttons(
                         [("📄 Ro'yxat", f"mod:inv:royxat_{take_id}"),
                          ("⬆️ Bito'ga yuklash", f"mod:inv:yukla_{take_id}"),
                          ("🗑 Bekor qilish", f"mod:inv:bekor_{take_id}")],
                         row_width=1, back="menu:root"))


def _confirm_upload(bot, chat_id, tg_id, take_id):
    users.require_role(tg_id, "owner")
    numbers = summary(take_id)
    bot.send_message(
        chat_id,
        "⚠️ <b>Diqqat</b>\n\n"
        "Yuklangach Bito'dagi qoldiq sanalgan songa almashadi. "
        "Bu amalni qaytarib bo'lmaydi.\n\n"
        f"O'zgaradi: {numbers['surplus'] + numbers['shortage']} ta mahsulot.\n"
        f"Sanalmagan mahsulotlarga tegilmaydi.\n\n"
        "Davom etamizmi?",
        parse_mode="HTML",
        reply_markup=ui.buttons(
            [("Ha, yuklansin", f"mod:inv:haqiqatan_{take_id}")],
            back=f"mod:inv:yakun_{take_id}"))


def _upload(bot, chat_id, tg_id, take_id):
    users.require_role(tg_id, "owner")
    note = bot.send_message(chat_id, "Bito'ga yuklanmoqda…")
    try:
        result = upload(take_id)
    finally:
        try:
            bot.delete_message(chat_id, note.message_id)
        except Exception:  # noqa: BLE001
            pass
    bot.send_message(
        chat_id,
        f"✅ Yuklandi.\nInventarizatsiya №{result['number'] or '—'}, "
        f"{result['count']} ta mahsulot.\n\n"
        "Qoldiqni yangilash uchun Ombor → Yangilash tugmasini bosing.",
        reply_markup=ui.main_menu(tg_id))


def _panel(bot, chat_id, tg_id):
    active = current()
    lines = ["<b>Inventarizatsiya</b>", ""]
    if catalog.is_stale():
        lines.append("⚠️ Katalog eskirgan. Avval Ombor → Yangilash.")
    if active:
        numbers = summary(active["id"])
        lines += [f"Davom etmoqda: {ui.escape(active['title'] or '')}",
                  f"Sanalgan: {numbers['count']} ta"]
        buttons = [("▶️ Davom etish", f"mod:inv:sana_{active['id']}"),
                   ("📄 Ro'yxat", f"mod:inv:royxat_{active['id']}"),
                   ("🏁 Yakunlash", f"mod:inv:yakun_{active['id']}")]
    else:
        lines.append("Mahsulotlarni telefonda sanaysiz, bot farqni "
                     "ko'rsatadi. Bito'ga faqat siz tasdiqlagach yoziladi.")
        buttons = [("▶️ Sanashni boshlash", "mod:inv:boshla")]

    last = db.row("SELECT * FROM stock_take WHERE tenant_id = ? "
                  "AND status = 'yuklandi' ORDER BY finished_at DESC LIMIT 1",
                  (ctx.require(),))
    if last:
        lines += ["", f"Oxirgi yuklangan: {last['finished_at']} "
                      f"(№{last['bito_number'] or '—'})"]

    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML",
                     reply_markup=ui.buttons(buttons, row_width=1,
                                             back="menu:root"))


