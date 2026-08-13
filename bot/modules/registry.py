"""Modul reyestri.

Ikki qismdan iborat:

1. **Katalog** — barcha modullarning ta'rifi (kalit, nomi, bog'liqliklari).
   U kod yozilmasdan oldin ham to'liq: BMP_BOT sotuvchiga modullarni
   belgilash oynasini shu ro'yxatdan quradi.
2. **Amalga oshirish** — `@implement("xodimlar")` bilan biriktirilgan sinf.
   Hali yozilmagan modul katalogda bor, lekin menyuda ko'rinmaydi.

Nima uchun handlerlar shartsiz ro'yxatdan o'tadi
------------------------------------------------
Bitta bot 50 ta biznesga xizmat qiladi. Modul A biznesda yoqilgan, B da yo'q
bo'lishi mumkin. Telegram handlerlari esa botga bir marta, hamma uchun
biriktiriladi — «yoqilmagan modul handlerini ro'yxatdan o'tkazmaslik»
texnik jihatdan mumkin emas.

Shuning uchun: handlerlar hamma modul uchun biriktiriladi, lekin har biri
kirishida `modules.require(kalit)` chaqiradi. Menyu esa tenant bo'yicha
quriladi, ya'ni mijoz sotib olmagan tugmani ko'rmaydi.
"""

import importlib
import logging
import pkgutil

log = logging.getLogger(__name__)


class ModuleSpec:
    def __init__(self, key, title, summary, requires=(), depends=()):
        self.key = key
        self.title = title
        self.summary = summary
        self.requires = tuple(requires)   # 'bito' — tashqi shart
        self.depends = tuple(depends)     # boshqa modullar
        self.impl = None                  # amalga oshirilgan sinf nusxasi

    @property
    def ready(self):
        return self.impl is not None

    def __repr__(self):
        return f"<Module {self.key}{'' if self.ready else ' (yozilmagan)'}>"


# Katalog. Tartib menyudagi tartibni belgilaydi.
CATALOG = [
    ModuleSpec(
        "xodimlar", "👥 Xodimlar",
        "Davomat, ish haqi, ballar, reyting, jadval",
    ),
    ModuleSpec(
        "vazifalar", "📋 Vazifalar",
        "Vazifa berish, hisobot, qaytarish, muddat jarimasi",
    ),
    ModuleSpec(
        "hr", "🧑‍💼 Ishga qabul",
        "Vakansiya, AI suhbat, nomzod baholash",
    ),
    ModuleSpec(
        "ombor", "📦 Ombor",
        "Qoldiq, turib qolganlar, zakaz tavsiyasi",
        requires=("bito",),
    ),
    ModuleSpec(
        "ombor_ai", "🤖 Ombor AI tavsiyalari",
        "Sotuv tezligiga qarab zakaz, ABC-XYZ tahlil",
        requires=("bito",), depends=("ombor",),
    ),
    ModuleSpec(
        "nakladnoy", "🧾 Nakladnoy",
        "Rasm/PDF/Excel → AI o'qish → Bito'ga kirim",
        requires=("bito",),
    ),
    ModuleSpec(
        "inventarizatsiya", "📋 Inventarizatsiya",
        "Telefonda sanash, CSV import",
        requires=("bito",), depends=("ombor",),
    ),
    ModuleSpec(
        "moliya", "📊 Moliya",
        "Pul taqvimi, zakaz limiti, qarzlar",
        requires=("bito",),
    ),
    ModuleSpec(
        "marketing", "📣 Marketing",
        "Aksiya posti, AI poster, kanal",
        requires=("bito",),
    ),
    ModuleSpec(
        "mijoz", "⭐ Mijoz baholari",
        "QR orqali baho, takliflar va shikoyatlar",
    ),
]

BY_KEY = {spec.key: spec for spec in CATALOG}
KEYS = tuple(spec.key for spec in CATALOG)


def implement(key):
    """@implement("xodimlar") — modul sinfini katalogga biriktiradi."""

    def decorator(cls):
        spec = BY_KEY.get(key)
        if spec is None:
            raise KeyError(f"Katalogda «{key}» moduli yo'q")
        spec.impl = cls()
        spec.impl.spec = spec
        return cls

    return decorator


def load():
    """bot/modules/ ichidagi modul fayllarini yuklaydi."""
    import bot.modules as package

    for info in pkgutil.iter_modules(package.__path__):
        if info.name in ("registry", "base"):
            continue
        try:
            importlib.import_module(f"bot.modules.{info.name}")
        except Exception:  # noqa: BLE001 — bitta modul butun botni yiqitmasin
            log.exception("Modul yuklanmadi: %s", info.name)

    ready = [s.key for s in CATALOG if s.ready]
    log.info("Modullar yuklandi: %s", ready or "hali yo'q")
    return ready


def implemented():
    return [spec for spec in CATALOG if spec.ready]


def resolve_depends(keys):
    """Bog'liqliklarni qo'shib, tartiblangan ro'yxat qaytaradi."""
    result = set()
    for key in keys:
        spec = BY_KEY.get(key)
        if not spec:
            continue          # noma'lum kalit e'tiborsiz — kelajak modullari
        result.add(key)
        result.update(spec.depends)
    return [k for k in KEYS if k in result]


def missing_depends(keys):
    """Bog'liqligi yetishmayotgan modullar: {modul: (yetishmagan, ...)}"""
    chosen = set(keys)
    out = {}
    for key in keys:
        spec = BY_KEY.get(key)
        if not spec:
            continue
        gaps = tuple(d for d in spec.depends if d not in chosen)
        if gaps:
            out[key] = gaps
    return out
