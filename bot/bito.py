"""Bito API klienti.

Ikkita noaniqlik bor va ikkalasi ham taxmin qilinmaydi, aniqlanadi:

1. Autentifikatsiya sarlavhasi. Nomzodlar ketma-ket sinaladi, ishlagani
   sozlamalarga yoziladi va boshqa sinalmaydi.
2. Endpoint yo'llari. Xuddi shu tamoyil — `bito_paths` jadvalida keshlanadi.

Shu sabab bitta versiya o'zgarsa ham bot butunlay yiqilmaydi.
"""

import logging
import time

import requests

from . import config, ctx, db, tenant
from .errors import BitoError, SetupError

log = logging.getLogger(__name__)

TIMEOUT = 25
RETRIES = 2

# Sarlavha nomzodlari — ishlagani `bito_auth_scheme` ga yoziladi
AUTH_SCHEMES = [
    "x-api-key",
    "api-key",
    "bearer",
    "token",
    "authorization",
]

# Mantiqiy nom -> yo'l nomzodlari
PATHS = {
    "profile": ["profile/get-me", "profile/me", "profile"],
    "organizations": ["organization/get-all", "organizations/get-all"],
    "warehouses": ["warehouse/get-all", "warehouses/get-all"],
    "prices": ["price/get-all", "prices/get-all"],
    "uoms": [
        "units-of-measure/get-all",
        "unit-of-measure/get-all",
        "uom/get-all",
    ],
    "currencies": ["currency/get-all", "currencies/get-all"],
    "products": ["product/get-paging", "products/get-paging"],
    "product_by_barcode": ["product/get-by-barcode", "products/get-by-barcode"],
    "suppliers": ["supplier/get-paging", "suppliers/get-paging"],
    "purchase_create": ["purchase/create", "purchases/create"],
    "purchases": ["purchase/get-paging", "purchases/get-paging"],
}

# Sahifali so'rovlar. Bito `page` ni MAJBURIY talab qiladi — hujjatda
# ixtiyoriy deb yozilgan bo'lsa ham. Yuborilmasa 400 qaytadi.
PAGED = {"products", "suppliers", "purchases"}
MAX_LIMIT = 200


# --------------------------------------------------------------- yordamchilar


def _base():
    raw = tenant.get("bito_base_url") or config.BITO_BASE_URL
    return raw.rstrip("/") + "/"


def _headers(scheme, key):
    if scheme == "bearer":
        return {"Authorization": f"Bearer {key}"}
    if scheme == "authorization":
        return {"Authorization": key}
    return {scheme: key}


def unwrap(payload):
    """Bito javobini ro'yxat yoki lug'atga keltiradi.

    Ko'rilgan shakllar: [...], {"data": [...]}, {"data": {"data": [...]}}.
    """
    seen = 0
    while isinstance(payload, dict) and "data" in payload and seen < 3:
        payload = payload["data"]
        seen += 1
    return payload


def _explain(status, body):
    if status in (401, 403):
        return "Bito API kaliti qabul qilinmadi. Kalitni tekshiring."
    if status == 404:
        return "Bito bu manzilni topmadi. Versiya o'zgargan bo'lishi mumkin."
    if status == 429:
        return "Bito so'rovlar sonini cheklab qo'ydi. Biroz kuting."
    if status >= 500:
        return "Bito serverida vaqtinchalik nosozlik. Keyinroq urinib ko'ring."
    text = str(body)[:160]
    return f"Bito xatosi ({status}). {text}"


# --------------------------------------------------------------------- klient


class Bito:
    def __init__(self, api_key=None, scheme=None, base_url=None, session=None):
        self.api_key = api_key
        self.scheme = scheme
        self.base_url = base_url
        self.session = session or requests

    # -- past daraja --

    def _url(self, path):
        return (self.base_url or _base()) + path.lstrip("/")

    def raw(self, path, method="GET", scheme=None, timeout=None, **kwargs):
        """Bitta so'rov. Javob obyektini qaytaradi, xato tashlamaydi."""
        scheme = scheme or self.scheme
        if not self.api_key:
            raise SetupError.for_key("bito_api_key", "Sozlamalar → Bito ulanishi")
        headers = _headers(scheme, self.api_key)
        headers["Accept"] = "application/json"

        last = None
        for attempt in range(RETRIES + 1):
            try:
                return self.session.request(
                    method,
                    self._url(path),
                    headers=headers,
                    timeout=timeout or TIMEOUT,
                    **kwargs,
                )
            except Exception as e:  # noqa: BLE001 — tarmoq xatosi
                last = e
                log.warning("Bito so'rov xatosi (%s-urinish): %s", attempt + 1, e)
                if attempt < RETRIES:
                    time.sleep(1.5 * (attempt + 1))
        raise BitoError(
            "Bito bilan aloqa yo'q. Internet yoki Bito serveri ishlamayapti.",
            path=path,
            raw=str(last),
        )

    def call(self, path, method="GET", **kwargs):
        """So'rov + xato tekshiruvi + javobni ochish."""
        resp = self.raw(path, method, **kwargs)
        if resp.status_code >= 400:
            body = None
            try:
                body = resp.json()
            except Exception:  # noqa: BLE001
                body = resp.text
            code = None
            if isinstance(body, dict):
                code = body.get("code") or body.get("error_code")
            raise BitoError(_explain(resp.status_code, body), code=code, path=path,
                            raw=body)
        try:
            return unwrap(resp.json())
        except ValueError:
            raise BitoError("Bito tushunarsiz javob qaytardi.", path=path)

    # -- yo'l aniqlash --

    def resolve(self, logical):
        cached = db.value(
            "SELECT resolved FROM bito_paths WHERE tenant_id = ? AND logical = ?",
            (ctx.require(), logical),
        )
        if cached:
            return cached

        errors = []
        for candidate in PATHS[logical]:
            resp = self.raw(candidate)
            if resp.status_code < 400:
                db.run(
                    "INSERT INTO bito_paths (tenant_id, logical, resolved) "
                    "VALUES (?, ?, ?) ON CONFLICT (tenant_id, logical) "
                    "DO UPDATE SET resolved = excluded.resolved, "
                    "  checked_at = datetime('now')",
                    (ctx.require(), logical, candidate),
                )
                log.info("Bito yo'li aniqlandi: %s -> %s", logical, candidate)
                return candidate
            if resp.status_code in (401, 403):
                raise BitoError(_explain(resp.status_code, None), path=candidate)
            if resp.status_code >= 500 or resp.status_code == 429:
                # Server nosozligi — yo'l noto'g'ri degani emas. Qolganini
                # sinash bekor, aks holda xato sababi yashirinadi.
                raise BitoError(_explain(resp.status_code, None), path=candidate)
            errors.append(f"{candidate}={resp.status_code}")

        raise BitoError(
            f"«{logical}» uchun ishlaydigan manzil topilmadi.",
            path=", ".join(errors),
        )

    def get(self, logical, **kwargs):
        return self.call(self.resolve(logical), **kwargs)

    def paged(self, logical, page=1, limit=MAX_LIMIT, **filters):
        """Sahifali so'rov. `page` doim yuboriladi — Bito busiz 400 beradi.

        Qaytadi: (qatorlar, jami). Usul (GET/POST) noma'lum bo'lgani uchun
        ikkalasi sinaladi va ishlagani keshlanadi.
        """
        params = {"page": int(page), "limit": min(int(limit), MAX_LIMIT)}
        params.update({k: v for k, v in filters.items() if v not in (None, "")})
        path = self.resolve(logical)

        cached = tenant.get(f"bito_method_{logical}")
        methods = [cached] if cached else ["GET", "POST"]
        last = None
        for method in methods:
            kwargs = {"params": params} if method == "GET" else {"json": params}
            resp = self.raw(path, method, **kwargs)
            if resp.status_code < 400:
                if not cached:
                    tenant.set(f"bito_method_{logical}", method)
                try:
                    payload = unwrap(resp.json())
                except ValueError:
                    raise BitoError("Bito tushunarsiz javob qaytardi.", path=path)
                return self._items(payload), self._total(payload)
            last = resp
        raise BitoError(
            _explain(last.status_code if last else 0, None), path=path
        )

    # -- kalitni tekshirish --

    def verify(self):
        """Kalitni tekshiradi va ishlagan sxemani qaytaradi.

        Muvaffaqiyat: (profil, sxema). Aks holda BitoError.
        """
        path_errors = []
        for scheme in AUTH_SCHEMES:
            for path in PATHS["profile"]:
                resp = self.raw(path, scheme=scheme)
                if resp.status_code < 400:
                    try:
                        profile = unwrap(resp.json())
                    except ValueError:
                        continue
                    if isinstance(profile, dict) and profile.get("id"):
                        self.scheme = scheme
                        return profile, scheme
                elif resp.status_code not in (401, 403):
                    path_errors.append(f"{path}={resp.status_code}")

        if path_errors:
            raise BitoError(
                "Bito javob berdi, lekin profil manzili topilmadi: "
                + ", ".join(sorted(set(path_errors))[:4])
            )
        raise BitoError(
            "Kalit qabul qilinmadi. Bito → Sozlamalar → Integratsiya "
            "bo'limidan kalitni qayta nusxalang."
        )

    # -- ma'lumot ro'yxatlari --

    @staticmethod
    def _total(payload):
        if isinstance(payload, dict):
            for key in ("total", "total_count", "count"):
                if isinstance(payload.get(key), int):
                    return payload[key]
        return None

    @staticmethod
    def _items(payload):
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("items", "list", "results", "docs"):
                if isinstance(payload.get(key), list):
                    return payload[key]
        return []

    def organizations(self, only_active=True):
        items = self._items(self.get("organizations"))
        if only_active:
            items = [o for o in items if o.get("is_active") is not False]
        return items

    def warehouses(self, organization_id=None, only_active=True):
        items = self._items(self.get("warehouses"))
        if only_active:
            items = [w for w in items if w.get("status") != "inactive"]
        if organization_id:
            items = [w for w in items
                     if str(w.get("organization_id")) == str(organization_id)]
        return items

    def prices(self, sale_only=True, only_active=True):
        items = self._items(self.get("prices"))
        if only_active:
            items = [p for p in items if p.get("status") != "inactive"]
        if sale_only:
            sale = [p for p in items if p.get("type") == "sale"]
            if sale:
                items = sale
        return items

    def products(self, page=1, limit=MAX_LIMIT, search=None, category_id=None):
        return self.paged("products", page=page, limit=limit,
                          search=search, category_id=category_id)

    def suppliers(self, page=1, limit=MAX_LIMIT, search=None):
        return self.paged("suppliers", page=page, limit=limit, search=search)

    def create_purchase(self, body, timeout=None):
        """Kirim yaratadi. Javob obyektini QAYTARADI, xato tashlamaydi.

        Sabab: 502/504 «yaratilmadi» degani emas — Bito nginx'i javobni
        kutmay uzishi mumkin, kirim esa serverda yaratilgan bo'ladi.
        Qaror chaqiruvchida qabul qilinadi.
        """
        path = self.resolve("purchase_create")
        return self.raw(path, "POST", json=body,
                        **({"timeout": timeout} if timeout else {}))

    def uoms(self, only_active=True):
        items = self._items(self.get("uoms"))
        if only_active:
            items = [u for u in items if u.get("status") != "inactive"]
        return [u for u in items if u.get("type") != "service"]


# ------------------------------------------------------------------- moslama


def client():
    """Sozlamalardagi kalit bilan tayyor klient."""
    return Bito(
        api_key=tenant.require("bito_api_key"),
        scheme=tenant.get("bito_auth_scheme") or AUTH_SCHEMES[0],
    )


def pick_uom(uoms, system_code, fallback_names=()):
    """system_code bo'yicha topadi, topilmasa nom bo'yicha."""
    for u in uoms:
        if u.get("system_code") == system_code:
            return u
    lowered = tuple(n.lower() for n in fallback_names)
    for u in uoms:
        name = str(u.get("name") or "").lower()
        code = str(u.get("code") or "").lower()
        if name in lowered or code in lowered:
            return u
    return None


def pick_default(items, *flags):
    """is_main / is_default belgisiga ko'ra bittasini tanlaydi."""
    for flag in flags:
        marked = [i for i in items if i.get(flag)]
        if len(marked) == 1:
            return marked[0]
    return items[0] if len(items) == 1 else None
