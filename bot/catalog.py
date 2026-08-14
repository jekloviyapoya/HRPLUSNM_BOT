"""Mahsulot katalogi keshi va nom bo'yicha moslashtirish.

Ombor skaneri hamma sahifani varaqlab o'tadi — o'sha o'tishda katalog ham
yoziladi. Ikkinchi marta varaqlash kerak emas.

Moslashtirish tartibi (birinchi topilgani g'olib):

1. **Xotira** — foydalanuvchi ilgari shu nomni qaysi mahsulotga
   bog'lagan bo'lsa, o'sha. Eng ishonchli manba: odam tanlagan.
2. **Shtrix-kod** — aniq mos kelish.
3. **SKU** — aniq mos kelish.
4. **Normallashtirilgan nom** — aniq mos kelish.
5. **So'z ustma-ustligi** — nomzodlar ro'yxati, ball bilan.

Beshinchi bosqich hech qachon avtomatik tasdiqlanmaydi: nomzodlar
foydalanuvchiga ko'rsatiladi. Noto'g'ri moslashtirish ombor qoldig'ini
buzadi va uni qo'lda tuzatish og'ir — shuning uchun taxmin qilinmaydi.
"""

import logging
import re

from . import ctx, db

log = logging.getLogger(__name__)

# Nomdagi ma'nosiz farqlar: o'lcham, brend belgisi va h.k. saqlanadi,
# faqat tinish belgisi va ortiqcha bo'shliq olib tashlanadi
_CLEAN = re.compile(r"[^0-9a-zа-яёўқғҳ ]+", re.IGNORECASE)
_SPACE = re.compile(r"\s+")

# Moslashtirishda hisobga olinmaydigan so'zlar
STOP_WORDS = {"dona", "kg", "gr", "ml", "l", "sht", "шт", "бл", "blok",
              "упак", "kor", "korobka", "pack", "and", "va"}

AUTO_SCORE = 0.86        # bundan yuqori ball — avtomatik qabul
SHOW_SCORE = 0.35        # bundan past — umuman ko'rsatilmaydi
MAX_CANDIDATES = 5


def normalize(name):
    """Moslashtirish uchun kalit: kichik harf, tinish belgisiz."""
    text = str(name or "").lower().replace("ʻ", "'").replace("`", "'")
    text = text.replace("'", "")
    text = _CLEAN.sub(" ", text)
    return _SPACE.sub(" ", text).strip()


def tokens(name):
    return {word for word in normalize(name).split()
            if word and word not in STOP_WORDS}


def score(a_tokens, b_tokens):
    """0..1 — so'z ustma-ustligi (Jaccard, uzunlik jazosi bilan)."""
    if not a_tokens or not b_tokens:
        return 0.0
    common = a_tokens & b_tokens
    if not common:
        return 0.0
    return len(common) / len(a_tokens | b_tokens)


# --------------------------------------------------------------------- kesh


def upsert(product):
    """Bito mahsulotini keshga yozadi. Ombor skaneri chaqiradi."""
    pid = str(product.get("_id") or product.get("id") or "")
    if not pid:
        return
    name = str(product.get("name") or "").strip()
    if not name:
        return
    measure = product.get("measure") or {}
    barcodes = product.get("barcodes") or []
    if product.get("barcode"):
        barcodes = list(barcodes) + [product["barcode"]]
    db.run(
        "INSERT INTO catalog (tenant_id, product_id, name, key, sku, barcodes, "
        "  measure, measure_id, category, amount, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now')) "
        "ON CONFLICT (tenant_id, product_id) DO UPDATE SET "
        "  name = excluded.name, key = excluded.key, sku = excluded.sku, "
        "  barcodes = excluded.barcodes, measure = excluded.measure, "
        "  measure_id = excluded.measure_id, category = excluded.category, "
        "  amount = excluded.amount, updated_at = excluded.updated_at",
        (ctx.require(), pid, name, normalize(name), product.get("sku"),
         ",".join(str(b) for b in barcodes if b),
         measure.get("short_name") or measure.get("name"),
         measure.get("_id"),
         (product.get("category") or {}).get("name"),
         float(product.get("_amount") or 0)),
    )


def size():
    return db.value("SELECT COUNT(*) FROM catalog WHERE tenant_id = ?",
                    (ctx.require(),), default=0)


def is_stale():
    """Kesh bo'sh yoki bir haftadan eski bo'lsa — yangilash kerak."""
    if not size():
        return True
    newest = db.value(
        "SELECT MAX(updated_at) FROM catalog WHERE tenant_id = ?",
        (ctx.require(),))
    if not newest:
        return True
    return bool(db.value(
        "SELECT ? < datetime('now', '-7 days')", (newest,), default=0))


def all_rows():
    return db.rows(
        "SELECT product_id, name, key, sku, barcodes, measure, measure_id "
        "FROM catalog WHERE tenant_id = ?", (ctx.require(),))


# ------------------------------------------------------------------ xotira


def remember(raw_name, product_id, product_name=None):
    key = normalize(raw_name)
    if not key or not product_id:
        return
    db.run(
        "INSERT INTO nak_alias (tenant_id, key, product_id, product_name) "
        "VALUES (?, ?, ?, ?) ON CONFLICT (tenant_id, key) DO UPDATE SET "
        "  product_id = excluded.product_id, "
        "  product_name = excluded.product_name, "
        "  used_count = used_count + 1, updated_at = datetime('now')",
        (ctx.require(), key, str(product_id), product_name),
    )


def forget(raw_name):
    db.run("DELETE FROM nak_alias WHERE tenant_id = ? AND key = ?",
           (ctx.require(), normalize(raw_name)))


def recall(raw_name):
    return db.row(
        "SELECT * FROM nak_alias WHERE tenant_id = ? AND key = ?",
        (ctx.require(), normalize(raw_name)),
    )


def aliases():
    return db.rows(
        "SELECT * FROM nak_alias WHERE tenant_id = ? "
        "ORDER BY used_count DESC, updated_at DESC",
        (ctx.require(),),
    )


# ----------------------------------------------------------- moslashtirish


def match(raw_name, barcode=None, rows=None):
    """Bitta qatorni moslashtiradi.

    Qaytadi: {"state", "product_id", "product_name", "how", "candidates"}
    state: 'topildi' — ishonchli; 'yoq' — foydalanuvchi tanlaydi.
    """
    result = {"state": "yoq", "product_id": None, "product_name": None,
              "how": None, "candidates": []}

    # 1. Xotira — odam tanlagani eng ishonchli
    saved = recall(raw_name)
    if saved:
        result.update(state="topildi", product_id=saved["product_id"],
                      product_name=saved["product_name"], how="xotira")
        return result

    rows = all_rows() if rows is None else rows
    if not rows:
        return result

    # 2. Shtrix-kod
    code = str(barcode or "").strip()
    if code:
        for row in rows:
            codes = (row["barcodes"] or "").split(",")
            if code in [c.strip() for c in codes if c.strip()]:
                result.update(state="topildi", product_id=row["product_id"],
                              product_name=row["name"], how="shtrix-kod")
                return result

    key = normalize(raw_name)

    # 3. SKU
    for row in rows:
        if row["sku"] and normalize(row["sku"]) == key:
            result.update(state="topildi", product_id=row["product_id"],
                          product_name=row["name"], how="SKU")
            return result

    # 4. Aniq nom
    exact = [row for row in rows if row["key"] == key]
    if len(exact) == 1:
        result.update(state="topildi", product_id=exact[0]["product_id"],
                      product_name=exact[0]["name"], how="nom")
        return result

    # 5. So'z ustma-ustligi — taxmin qilinmaydi, ko'rsatiladi
    mine = tokens(raw_name)
    scored = []
    for row in rows:
        value = score(mine, tokens(row["name"]))
        if value >= SHOW_SCORE:
            scored.append((value, row))
    scored.sort(key=lambda pair: -pair[0])

    result["candidates"] = [
        {"product_id": row["product_id"], "name": row["name"],
         "score": round(value, 3), "measure": row["measure"]}
        for value, row in scored[:MAX_CANDIDATES]
    ]

    # Yagona va juda kuchli mos kelish bo'lsagina avtomatik
    if scored and scored[0][0] >= AUTO_SCORE:
        if len(scored) == 1 or scored[0][0] - scored[1][0] > 0.15:
            best = scored[0][1]
            result.update(state="topildi", product_id=best["product_id"],
                          product_name=best["name"], how="o'xshashlik")
    return result


def match_all(items):
    """Ro'yxatni moslashtiradi. Katalog bir marta o'qiladi."""
    rows = all_rows()
    out = []
    for item in items:
        out.append(match(item.get("raw_name") or item.get("name"),
                         barcode=item.get("barcode"), rows=rows))
    return out
