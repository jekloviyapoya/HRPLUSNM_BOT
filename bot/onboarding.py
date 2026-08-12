"""O'rnatish sehrgari.

1-bosqichda: egasini qayd qilish + do'kon nomi.
2-bosqichda qo'shiladi: Bito kaliti va tekshiruv, tashkilot, ombor,
narx-ro'yxati, valyuta, o'lchov birliklari, kanal, ish vaqti.

Har qadam sessiyada saqlanadi — uzilib qolsa o'sha joydan davom etadi.
"""

from . import sessions, tenant, ui, users

# Qadam nomi -> (savol matni, o'tkazib yuborsa bo'ladimi)
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

WELCOME = (
    "Salom! Bu — do'kon boshqaruv boti.\n\n"
    "Siz birinchi bo'lib kirdingiz, shuning uchun **egasi** sifatida qayd "
    "etildingiz. Endi qisqa sozlash boshlanadi — bir necha savol, hammasi "
    "keyin Sozlamalardan o'zgartiriladi.\n\n"
    "**1-qadam.** Do'koningiz nomi qanday? Bu nom hisobotlarda, "
    "postlarda va xabarlarda ishlatiladi."
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


def start(bot, message):
    sessions.set(message.from_user.id, "setup:shop_name", {})
    bot.send_message(message.chat.id, WELCOME, parse_mode="Markdown")


def handle_text(bot, message):
    """Sehrgar bosqichidagi matnli javob. True qaytarsa — ishlandi."""
    state, _ = sessions.get(message.from_user.id)
    if not state or not state.startswith("setup:"):
        return False

    step = state.split(":", 1)[1]

    if step == "shop_name":
        name = (message.text or "").strip()
        if len(name) < 2:
            bot.send_message(message.chat.id, "Nom juda qisqa. Qaytadan kiriting.")
            return True
        tenant.set("shop_name", name)
        sessions.clear(message.from_user.id)
        bot.send_message(
            message.chat.id,
            f"Yozib oldim: **{name}**\n\n"
            "Qolgan qadamlar (Bito ulanishi, ombor, narx-ro'yxati) keyingi "
            "yangilanishda qo'shiladi. Hozircha menyu ochiq.",
            parse_mode="Markdown",
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
