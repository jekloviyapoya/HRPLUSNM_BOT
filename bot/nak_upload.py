"""Nakladnoyni Bito'ga kirim qilib yuklash.

Bu — qaytarib bo'lmaydigan amal. Uchta xavf bor va uchalasi ham
market-bot'da amalda yuz bergan:

1. **504 «yaratilmadi» degani emas.** Bito nginx'i katta so'rovni ~60
   soniyada uzadi, kirim esa serverda yaratilgan bo'lishi mumkin.
   Avtomatik qayta yuborilsa — ikki marta kirim. Shuning uchun izohga
   betakror belgi yoziladi va uzilishdan keyin o'sha belgi bo'yicha
   qidiriladi.
2. **Katta hujjat 504 keltiradi.** Qatorlar partiyalarga bo'linadi.
3. **Miqdor birligi.** Bito'ga DONA soni kerak: `qty × block_size`.
   `cost` esa dona narxi, o'zgarishsiz.
"""

import logging
import secrets
import time

from . import bito, ctx, db, tenant
from .errors import BitoError

log = logging.getLogger(__name__)

BATCH_SIZE = 60          # bir kirimga shuncha qator
BATCH_PAUSE = 1.0
VERIFY_DELAY = 8         # Bito yozib tugatishiga ulgursin

# Bito xatosi: yuborilgan product_id topilmadi (mahsulot o'chirilgan)
ERR_PRODUCT_MISSING = 26000


def new_tag():
    """Betakror belgi — uzilishdan keyin aynan shu yuklashni topish uchun."""
    return "bot-" + secrets.token_hex(4)


def build_products(items):
    """Qatorlarni Bito shakliga o'giradi.

    INVARIANT yakuni: bu yerda va faqat bu yerda blok donaga aylanadi.
        amount = qty × block_size    (yakuniy dona soni)
        cost   = price               (dona narxi, o'zgarishsiz)
    """
    products = []
    for item in items:
        if not item.get("product_id"):
            continue
        block = int(item.get("block_size") or 1) or 1
        amount = float(item["qty"]) * block
        if amount <= 0:
            continue
        products.append({
            "product_id": str(item["product_id"]),
            "amount": amount,
            "cost": float(item["price"]),
        })
    return products


def total_of(products):
    return sum(p["amount"] * p["cost"] for p in products)


def batches(products, size=BATCH_SIZE):
    return [products[i:i + size] for i in range(0, len(products), size)]


def _timeout_for(count):
    """Katta partiya uzoqroq kutiladi."""
    return max(60, 30 + (count // 50) * 30)


def _body(products, supplier_id, tag, part=None, parts=None):
    suffix = f" ({part}/{parts})" if parts and parts > 1 else ""
    return {
        "organization_id": tenant.require("bito_org_id"),
        "warehouse_id": tenant.require("warehouse_id"),
        "currency_id": tenant.get("currency_id"),
        "responsible_id": tenant.get("bito_responsible_id"),
        "supplier_id": supplier_id,
        "state": "new",
        "date": _today(),
        "income_date": _today(),
        "is_auto_income": True,
        "additional_costs": [],
        "note": f"Telegram bot orqali nakladnoydan yuklandi{suffix} [{tag}]",
        "orders": [{"products": products}],
    }


def _today():
    import datetime as dt
    return dt.date.today().isoformat()


def _error_code(payload):
    if isinstance(payload, dict):
        for key in ("code", "error_code"):
            value = payload.get(key)
            if isinstance(value, int):
                return value
        upstream = payload.get("upstream")
        if isinstance(upstream, dict):
            return _error_code(upstream)
    return None


def _missing_product_id(payload):
    """26000 xatosida qaysi mahsulot ekanini topadi."""
    if not isinstance(payload, dict):
        return None
    if _error_code(payload) != ERR_PRODUCT_MISSING:
        return None
    for key in ("data", "field", "value"):
        value = payload.get(key)
        if isinstance(value, str) and len(value) == 24:
            return value
    upstream = payload.get("upstream")
    if isinstance(upstream, dict):
        return _missing_product_id(upstream)
    return None


def find_by_tag(supplier_id, tag, client=None):
    """Uzilishdan keyin: shu belgili kirim yaratilganmi?"""
    client = client or bito.client()
    try:
        rows, _ = client.paged("purchases", page=1, limit=20)
    except BitoError:
        log.warning("Uzilishdan keyin tekshirib bo'lmadi", exc_info=True)
        return None
    for row in rows or []:
        if tag in str(row.get("note") or ""):
            return row
    return None


def send_batch(products, supplier_id, tag, part=1, parts=1, client=None,
               id2name=None):
    """Bitta partiya. Qaytadi: (ok, natija_matni)."""
    client = client or bito.client()
    body = _body(products, supplier_id, tag, part, parts)
    resp = client.create_purchase(body, timeout=_timeout_for(len(products)))

    if resp.status_code == 200:
        try:
            payload = resp.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            number = (data or {}).get("number") or (data or {}).get("code")
        except ValueError:
            number = None
        return True, str(number or "?")

    # Uzilish — kirim yaratilgan bo'lishi mumkin. QAYTA YUBORILMAYDI.
    if resp.status_code in (502, 503, 504):
        log.warning("Bito uzildi (%s), tekshirilmoqda: %s",
                    resp.status_code, tag)
        time.sleep(VERIFY_DELAY)
        found = find_by_tag(supplier_id, tag, client=client)
        if found:
            return True, str(found.get("number") or "?")
        return False, (f"Bito javob bermadi ({resp.status_code}). Tekshirdim — "
                       "kirim yaratilmagan, qayta urinib ko'ring.")

    try:
        payload = resp.json()
    except ValueError:
        payload = resp.text

    missing = _missing_product_id(payload if isinstance(payload, dict) else {})
    if missing:
        name = (id2name or {}).get(missing, "mahsulot")
        return False, (f"«{name}» Bito'da topilmadi — o'chirilgan bo'lishi "
                       "mumkin. Nakladnoyni qayta moslashtiring.")

    detail = str(payload)[:150]
    return False, f"HTTP {resp.status_code}: {detail}"


def upload(items, supplier_id, client=None, progress=None):
    """Hamma qatorlarni yuklaydi.

    Qaytadi: {ok, numbers, failed, uploaded_count, uploaded_total, tag}
    """
    products = build_products(items)
    if not products:
        raise BitoError("Yuklash uchun moslashtirilgan qator yo'q.")

    id2name = {str(item["product_id"]): item.get("product_name")
               or item.get("raw_name") or "mahsulot"
               for item in items if item.get("product_id")}

    client = client or bito.client()
    tag = new_tag()
    parts = batches(products)
    numbers, failed = [], []
    uploaded_count, uploaded_total = 0, 0.0

    for index, chunk in enumerate(parts, 1):
        if progress:
            try:
                progress(index, len(parts))
            except Exception:  # noqa: BLE001
                pass
        ok, info = send_batch(chunk, supplier_id, tag, index, len(parts),
                              client=client, id2name=id2name)
        if ok:
            numbers.append(info)
            uploaded_count += len(chunk)
            uploaded_total += total_of(chunk)
        else:
            failed.append({"part": index, "count": len(chunk), "error": info})
        if index < len(parts):
            time.sleep(BATCH_PAUSE)

    return {
        "ok": bool(numbers),
        "numbers": numbers,
        "failed": failed,
        "uploaded_count": uploaded_count,
        "uploaded_total": uploaded_total,
        "total_count": len(products),
        "total_sum": total_of(products),
        "tag": tag,
    }


def mark_uploaded(doc_id, result):
    db.run(
        "UPDATE nak_doc SET status = ?, error = ?, updated_at = datetime('now') "
        "WHERE tenant_id = ? AND id = ?",
        ("yuklandi" if result["ok"] and not result["failed"] else "xato",
         None if result["ok"] and not result["failed"]
         else "; ".join(f["error"] for f in result["failed"])[:300],
         ctx.require(), doc_id),
    )
