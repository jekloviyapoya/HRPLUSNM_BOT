"""O'rnatish sehrgari.

To'rt savol: do'kon nomi, Bito kaliti, tashkilot, ombor + narx-ro'yxati.
Valyuta narx-ro'yxatidan olinadi, o'lchov birliklari `system_code` orqali
topiladi — foydalanuvchidan so'ralmaydi.

ID qo'lda kiritilmaydi: hamma tanlov Bito'dan kelgan ro'yxat, tugma ko'rinishida.
Har qadam sessiyada — uzilib qolsa o'sha joydan davom etadi.

parse_mode: HTML. Eski Markdown `**` ni jimgina yeb qo'yadi.
"""

import logging

from . import bito, sessions, tenant, ui, users
from .errors import BitoError

log = logging.getLogger(__name__)

# Sozlanishi kerak bo'lgan kalitlar -> menyudagi nomi
STEPS = [
    ("shop_name", "Do'kon nomi"),
    ("bito_api_key", "Bito ulanishi"),
    ("bito_org_id", "Tashkilot"),
    ("warehouse_id", "Ombor"),
    ("price_id", "Sotuv narx-ro'yxati"),
]

Q_SHOP = (
    "<b>1-qadam.</b> Do'koningiz nomi qanday?\n"
    "Bu nom hisobotlarda, postlarda va xabarlarda ishlatiladi."
)

Q_KEY = (
    "<b>2-qadam.</b> Bito API kalitini yuboring.\n\n"
    "Bito → Sozlamalar → Integratsiya bo'limidan olinadi. "
    "Kalitni yuborganingizdan keyin xabaringizni o'chirib tashlang — "
    "u sizning hisobingizga to'liq kirish beradi."
)

WELCOME = (
    "Salom! Bu — do'kon boshqaruv boti.\n\n"
    "Siz birinchi bo'lib kirdingiz, shuning uchun <b>egasi</b> sifatida qayd "
    "etildingiz. Endi to'rtta savol — hammasi keyin Sozlamalardan "
    "o'zgartiriladi.\n\n"
)


# ----------------------------------------------------------------- egasi

def claim_owner(message):
    if users.has_owner():
        return False
    users.upsert(
        message.from_user.id,
        name=(message.from_user.first_name or "").strip() or None,
        username=message.from_user.username,
        role="owner",
    )
    return True


def current_step(tg_id):
    state, _ = sessions.get(tg_id)
    if state and state.startswith("setup:"):
        return state.split(":", 1)[1]
    return None


def pending_summary():
    labels = dict(STEPS)
    return [labels[k] for k in tenant.missing([k for k, _ in STEPS])]


# ----------------------------------------------------------------- qadamlar

def start(bot, message):
    sessions.set(message.from_user.id, "setup:shop_name", {})
    bot.send_message(message.chat.id, WELCOME + Q_SHOP, parse_mode="HTML")


def resume(bot, message, step):
    bot.send_message(
        message.chat.id,
        "Sozlash tugallanmagan. Shu joydan davom etamiz.",
    )
    _ask(bot, message.chat.id, message.from_user.id, step)


def _ask(bot, chat_id, tg_id, step):
    """Berilgan qadam savolini beradi."""
    if step == "shop_name":
        bot.send_message(chat_id, Q_SHOP, parse_mode="HTML")
    elif step == "bito_api_key":
        bot.send_message(chat_id, Q_KEY, parse_mode="HTML")
    elif step == "bito_org_id":
        _ask_orgs(bot, chat_id, tg_id)
    elif step == "warehouse_id":
        _ask_warehouses(bot, chat_id, tg_id)
    elif step == "price_id":
        _ask_prices(bot, chat_id, tg_id)
    else:
        _finish(bot, chat_id, tg_id)


def _advance(bot, chat_id, tg_id, step):
    sessions.set(tg_id, f"setup:{step}", sessions.get(tg_id)[1])
    _ask(bot, chat_id, tg_id, step)


# -- 3-qadam: tashkilot --

def _ask_orgs(bot, chat_id, tg_id):
    client = bito.client()
    items = client.organizations()
    if not items:
        bot.send_message(
            chat_id,
            "⚠️ Bito'da faol tashkilot topilmadi. Bito ichida tashkilot "
            "yarating va /start bosing.",
        )
        return
    if len(items) == 1:
        _save_org(bot, chat_id, tg_id, items[0])
        return

    bot.send_message(
        chat_id,
        "<b>3-qadam.</b> Qaysi tashkilot bilan ishlaysiz?",
        parse_mode="HTML",
        reply_markup=ui.buttons(
            [(ui.escape(o.get("name") or "—"), f"setup:org:{o['id']}")
             for o in items],
            row_width=1,
        ),
    )


def _save_org(bot, chat_id, tg_id, org):
    tenant.set("bito_org_id", org["id"])
    tenant.set("bito_org_name", org.get("name") or "")
    if org.get("currency_id"):
        tenant.set("currency_id", org["currency_id"])
    bot.send_message(chat_id, f"Tashkilot: {ui.escape(org.get('name') or '—')}")
    _advance(bot, chat_id, tg_id, "warehouse_id")


# -- 4-qadam: ombor --

def _ask_warehouses(bot, chat_id, tg_id):
    client = bito.client()
    items = client.warehouses(organization_id=tenant.get("bito_org_id"))
    if not items:
        bot.send_message(
            chat_id,
            "⚠️ Bu tashkilotda faol ombor yo'q. Bito ichida ombor yarating "
            "va /start bosing.",
        )
        return
    if len(items) == 1:
        _save_warehouse(bot, chat_id, tg_id, items[0])
        return

    main = [w for w in items if w.get("is_main")]
    hint = ""
    if main:
        hint = f"\nAsosiy ombor: {ui.escape(main[0].get('name') or '—')}"
    bot.send_message(
        chat_id,
        "<b>4-qadam.</b> Qaysi ombordan ishlaysiz?" + hint,
        parse_mode="HTML",
        reply_markup=ui.buttons(
            [(ui.escape(w.get("name") or "—"), f"setup:wh:{w['id']}")
             for w in items],
            row_width=1,
        ),
    )


def _save_warehouse(bot, chat_id, tg_id, wh):
    tenant.set("warehouse_id", wh["id"])
    tenant.set("warehouse_name", wh.get("name") or "")
    bot.send_message(chat_id, f"Ombor: {ui.escape(wh.get('name') or '—')}")
    _advance(bot, chat_id, tg_id, "price_id")


# -- 5-qadam: narx-ro'yxati --

def _ask_prices(bot, chat_id, tg_id):
    client = bito.client()
    items = client.prices()
    if not items:
        bot.send_message(
            chat_id,
            "⚠️ Faol sotuv narx-ro'yxati topilmadi. Bito ichida yarating "
            "va /start bosing.",
        )
        return

    auto = bito.pick_default(items, "is_main", "is_default")
    if auto:
        _save_price(bot, chat_id, tg_id, auto)
        return

    bot.send_message(
        chat_id,
        "<b>5-qadam.</b> Sotuv narxlari qaysi ro'yxatdan olinsin?",
        parse_mode="HTML",
        reply_markup=ui.buttons(
            [(ui.escape(p.get("name") or "—"), f"setup:price:{p['id']}")
             for p in items],
            row_width=1,
        ),
    )


def _save_price(bot, chat_id, tg_id, price):
    tenant.set("price_id", price["id"])
    tenant.set("price_name", price.get("name") or "")
    # Valyuta narx-ro'yxatidan keladi — alohida savol keraksiz
    if price.get("currency_id"):
        tenant.set("currency_id", price["currency_id"])
    bot.send_message(chat_id, f"Narx-ro'yxati: {ui.escape(price.get('name') or '—')}")
    _detect_uoms(bot, chat_id)
    _finish(bot, chat_id, tg_id)


# -- o'lchov birliklari: savol emas, aniqlash --

def _detect_uoms(bot, chat_id):
    try:
        items = bito.client().uoms()
    except BitoError:
        log.warning("O'lchov birliklari olinmadi", exc_info=True)
        return

    piece = bito.pick_uom(items, "piece", ("dona", "pcs", "sht"))
    kg = bito.pick_uom(items, "kilogram", ("kg", "kilogram"))
    found = []
    if piece:
        tenant.set("uom_piece_id", piece["id"])
        found.append(f"dona = {ui.escape(piece.get('name') or '')}")
    if kg:
        tenant.set("uom_kg_id", kg["id"])
        found.append(f"kg = {ui.escape(kg.get('name') or '')}")
    if found:
        bot.send_message(chat_id, "O'lchov birliklari aniqlandi: " + ", ".join(found))


def _finish(bot, chat_id, tg_id):
    sessions.clear(tg_id)
    tenant.mark_setup_done()
    left = pending_summary()
    tail = ""
    if left:
        tail = "\n\n⚙️ To'ldirilmagan: " + ", ".join(left) + \
               "\nSozlamalar bo'limidan qo'shishingiz mumkin."
    bot.send_message(
        chat_id,
        f"✅ Sozlash tugadi — <b>{ui.escape(tenant.shop_name())}</b>{tail}",
        parse_mode="HTML",
        reply_markup=ui.main_menu(tg_id),
    )


# ------------------------------------------------------------- matnli javob

def handle_text(bot, message):
    """True qaytarsa — xabar sehrgar tomonidan ishlandi."""
    step = current_step(message.from_user.id)
    if not step:
        return False
    chat_id, tg_id = message.chat.id, message.from_user.id
    text = (message.text or "").strip()

    if step == "shop_name":
        if len(text) < 2:
            bot.send_message(chat_id, "Nom juda qisqa. Qaytadan kiriting.")
            return True
        tenant.set("shop_name", text)
        bot.send_message(chat_id, f"Yozib oldim: <b>{ui.escape(text)}</b>",
                         parse_mode="HTML")
        _advance(bot, chat_id, tg_id, "bito_api_key")
        return True

    if step == "bito_api_key":
        if len(text) < 8:
            bot.send_message(chat_id, "Bu kalitga o'xshamaydi. Qaytadan yuboring.")
            return True
        bot.send_message(chat_id, "Kalit tekshirilmoqda…")
        probe = bito.Bito(api_key=text)
        try:
            profile, scheme = probe.verify()
        except BitoError as e:
            bot.send_message(chat_id, f"⚠️ {e.user_message}")
            return True

        tenant.set("bito_api_key", text)
        tenant.set("bito_auth_scheme", scheme)
        company = profile.get("company_name") or profile.get("full_name") or ""
        bot.send_message(
            chat_id,
            f"✅ Ulandi: <b>{ui.escape(company)}</b>",
            parse_mode="HTML",
        )
        _advance(bot, chat_id, tg_id, "bito_org_id")
        return True

    # Tugma kutilayotgan qadamda matn kelsa
    bot.send_message(chat_id, "Quyidagi tugmalardan birini tanlang.")
    return True


# ----------------------------------------------------------- tugma javoblari

def handle_callback(bot, call):
    """setup:* tugmalari. True qaytarsa — ishlandi."""
    parts = (call.data or "").split(":")
    if len(parts) != 3 or parts[0] != "setup":
        return False
    kind, value = parts[1], parts[2]
    chat_id, tg_id = call.message.chat.id, call.from_user.id
    client = bito.client()

    if kind == "org":
        match = [o for o in client.organizations() if str(o["id"]) == value]
        if match:
            _save_org(bot, chat_id, tg_id, match[0])
        return True

    if kind == "wh":
        match = [w for w in client.warehouses(
            organization_id=tenant.get("bito_org_id")) if str(w["id"]) == value]
        if match:
            _save_warehouse(bot, chat_id, tg_id, match[0])
        return True

    if kind == "price":
        match = [p for p in client.prices() if str(p["id"]) == value]
        if match:
            _save_price(bot, chat_id, tg_id, match[0])
        return True

    return False
