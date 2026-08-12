"""O'rnatish sehrgari.

1-bosqichda: egasini qayd qilish + do'kon nomi.
2-bosqichda qo'shiladi: Bito kaliti va tekshiruv, tashkilot, ombor,
narx-ro'yxati, valyuta, o'lchov birliklari, kanal, ish vaqti.

Har qadam sessiyada saqlanadi — uzilib qolsa o'sha joydan davom etadi.

parse_mode: HTML. Eski Markdown `**` ni tushunmaydi va xato ham bermaydi —
qalin matn jimgina oddiy matnga aylanadi.
"""

from . import sessions, tenant, ui, users

# Qadam kaliti -> (menyudagi nomi, o'tkazib yuborsa bo'ladimi)
STEPS = [
    ("shop_name", "Do'kon nomi", False),
    ("bito_api_key", "Bito API kaliti", False),
    ("bito_org_id", "Tashkilot", False),
    ("warehouse_id", "Ombor", False),
    ("price_id", "Sotuv narx-ro'yxati", False),
    ("currency_id", "Valyuta", True),
    ("uom_piece_id", "O'lchov birliklari", True),
    ("channel_id", "Telegram kanal", True),
    ("work_hours", "Ish vaqti va xabar vaqtlari", True),
]

# Qadam kaliti -> foydalanuvchiga beriladigan savol
QUESTIONS = {
    "shop_name": (
        "<b>1-qadam.</b> Do'koningiz nomi qanday?\n"
        "Bu nom hisobotlarda, postlarda va xabarlarda ishlatiladi."
    ),
}

WELCOME = (
    "Salom! Bu — do'kon boshqaruv boti.\n\n"
    "Siz birinchi bo'lib kirdingiz, shuning uchun <b>egasi</b> sifatida qayd "
    "etildingiz. Endi qisqa sozlash boshlanadi — bir necha savol, hammasi "
    "keyin Sozlamalardan o'zgartiriladi.\n\n"
)


def claim_owner(message):
    """Birinchi /start bosgan odam egasi bo'ladi."""
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
    """Sehrgar davom etayotgan bo'lsa qadam kalitini qaytaradi."""
    state, _ = sessions.get(tg_id)
    if state and state.startswith("setup:"):
        return state.split(":", 1)[1]
    return None


def start(bot, message):
    sessions.set(message.from_user.id, "setup:shop_name", {})
    bot.send_message(
        message.chat.id,
        WELCOME + QUESTIONS["shop_name"],
        parse_mode="HTML",
    )


def resume(bot, message, step):
    """Sehrgar o'rtasida /start bosilsa — savolni qayta beradi, menyu emas."""
    bot.send_message(
        message.chat.id,
        "Sozlash tugallanmagan. Shu savoldan davom etamiz.\n\n"
        + QUESTIONS.get(step, "Keyingi qadam tayyor emas."),
        parse_mode="HTML",
    )


def handle_text(bot, message):
    """Sehrgar bosqichidagi matnli javob. True qaytarsa — ishlandi."""
    step = current_step(message.from_user.id)
    if not step:
        return False

    if step == "shop_name":
        name = (message.text or "").strip()
        if len(name) < 2:
            bot.send_message(
                message.chat.id, "Nom juda qisqa. Qaytadan kiriting."
            )
            return True
        tenant.set("shop_name", name)
        sessions.clear(message.from_user.id)
        bot.send_message(
            message.chat.id,
            f"Yozib oldim: <b>{ui.escape(name)}</b>\n\n"
            "Qolgan qadamlar — Bito ulanishi, ombor, narx-ro'yxati — keyingi "
            "yangilanishda qo'shiladi. Hozircha menyu ochiq.",
            parse_mode="HTML",
            reply_markup=ui.main_menu(message.from_user.id),
        )
        return True

    # Boshqa qadamlar 2-bosqichda
    sessions.clear(message.from_user.id)
    return False


def pending_summary():
    """Sozlanmagan qadamlar ro'yxati — menyuda ogohlantirish uchun."""
    missing = tenant.missing([key for key, _, _ in STEPS])
    labels = {key: label for key, label, _ in STEPS}
    return [labels[k] for k in missing]
