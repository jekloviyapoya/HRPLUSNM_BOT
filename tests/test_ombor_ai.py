"""Ombor AI: sotuv tezligi, zakaz, ABC, turib qolganlar."""

import importlib
import sys

import pytest


class Client:
    def __init__(self, pages, boom=None):
        self.pages = pages
        self.boom = boom
        self.calls = []

    def sales_by_item(self, page=1, limit=200, from_date=None, to_date=None):
        self.calls.append({"page": page, "from": from_date})
        if self.boom and page >= self.boom:
            from bot.errors import BitoError
            raise BitoError("Bito nosozligi")
        index = page - 1
        rows = self.pages[index] if index < len(self.pages) else []
        return rows, len(rows)


def sale(pid, name, qty, revenue):
    return {"product_id": pid, "name": name, "amount": qty, "total": revenue}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
    monkeypatch.setenv("SAAS_OWNER_ID", "111")
    for name in list(sys.modules):
        if name == "bot" or name.startswith("bot."):
            del sys.modules[name]
    db = importlib.import_module("bot.db")
    db.migrate()
    ctx = importlib.import_module("bot.ctx")
    ctx.set(importlib.import_module("bot.tenants").create(10))
    tenant = importlib.import_module("bot.tenant")
    for key, value in [("bito_org_id", "o1"), ("warehouse_id", "w1"),
                       ("bito_api_key", "k"), ("price_id", "p1")]:
        tenant.set(key, value)
    catalog = importlib.import_module("bot.catalog")
    for pid, name, amount in [("p1", "Coca-Cola", 20), ("p2", "Non", 100),
                              ("p3", "Eskirgan tovar", 40),
                              ("p4", "Nol qoldiq", 0)]:
        catalog.upsert({"_id": pid, "name": name, "barcodes": [],
                        "measure": {"short_name": "Dona"}, "sku": None,
                        "category": {"name": "x"}, "_amount": amount})
    return {"a": importlib.import_module("bot.modules.ombor_ai"),
            "catalog": catalog, "db": db, "ctx": ctx,
            "errors": importlib.import_module("bot.errors")}


# --- skaner ---

def test_sotuv_yigiladi(env):
    a = env["a"]
    result = a.scan(days=30, client=Client([[sale("p1", "Coca-Cola", 300, 1_350_000)]]))
    assert result["items"] == 1
    rows = a.stats()
    assert rows[0]["qty"] == 300
    assert rows[0]["days"] == 30


def test_sahifalar_varaqlanadi(env):
    a = env["a"]
    pages = [[sale(f"x{i}", f"T{i}", 5, 100) for i in range(200)],
             [sale("oxirgi", "Oxirgi", 1, 10)]]
    result = a.scan(client=Client(pages))
    assert result["items"] == 201


def test_eski_yozuvlar_tozalanadi(env):
    a = env["a"]
    a.scan(client=Client([[sale("p1", "A", 10, 100), sale("p2", "B", 5, 50)]]))
    assert len(a.stats()) == 2
    a.scan(client=Client([[sale("p1", "A", 12, 120)]]))
    assert len(a.stats()) == 1


def test_xato_qayd_etiladi(env):
    a = env["a"]
    with pytest.raises(env["errors"].BitoError):
        a.scan(client=Client([[sale("p1", "A", 1, 1)] * 200], boom=2))
    assert a.scan_state()["error"]


# --- kunlik tezlik ---

def test_kunlik_tezlik(env):
    a = env["a"]
    assert a.daily_rate({"qty": 300, "days": 30}) == 10
    assert a.daily_rate({"qty": 7, "days": 0}) == 7        # nolga bo'linmaydi


# --- zakaz tavsiyasi ---

def test_zakaz_kerak_boladi(env):
    a = env["a"]
    # kuniga 10 dona sotiladi, qoldiq 20 -> 14 kunga 140 kerak
    a.scan(client=Client([[sale("p1", "Coca-Cola", 300, 1_000_000)]]))
    rows = a.reorder(horizon=14)
    assert len(rows) == 1
    assert rows[0]["need"] == pytest.approx(120)
    assert rows[0]["days_left"] == pytest.approx(2)


def test_qoldiq_yetarli_bolsa_tavsiya_yoq(env):
    a = env["a"]
    # kuniga 1 dona, qoldiq 100 -> 14 kunga yetadi
    a.scan(client=Client([[sale("p2", "Non", 30, 100_000)]]))
    assert a.reorder(horizon=14) == []


def test_sotilmagan_zakazga_tushmaydi(env):
    a = env["a"]
    a.scan(client=Client([[sale("p1", "Coca-Cola", 0, 0)]]))
    assert a.reorder() == []


def test_eng_shoshilinchi_birinchi(env):
    a = env["a"]
    a.scan(client=Client([[sale("p1", "Coca-Cola", 300, 1_000),   # 2 kun
                           sale("p2", "Non", 300, 1_000)]]))       # 10 kun
    rows = a.reorder(horizon=30)
    assert rows[0]["name"] == "Coca-Cola"


# --- ABC ---

def test_abc_sinflari(env):
    a = env["a"]
    a.scan(client=Client([[
        sale("p1", "Katta", 10, 800_000),
        sale("p2", "O'rta", 10, 150_000),
        sale("p3", "Kichik", 10, 50_000),
    ]]))
    graded = {row["name"]: row["abc"] for row in a.abc()}
    assert graded["Katta"] == "A"
    assert graded["O'rta"] == "B"
    assert graded["Kichik"] == "C"


def test_abc_tushumsiz_yiqilmaydi(env):
    a = env["a"]
    a.scan(client=Client([[sale("p1", "Bekor", 5, 0)]]))
    assert a.abc()[0]["abc"] == "C"


def test_abc_xulosasi(env):
    a = env["a"]
    a.scan(client=Client([[sale("p1", "A1", 1, 900_000),
                           sale("p2", "C1", 1, 10_000)]]))
    numbers = a.abc_summary()
    assert numbers["A"]["count"] == 1
    assert numbers["A"]["revenue"] == 900_000


def test_abc_tushum_boyicha_tartiblanadi(env):
    a = env["a"]
    a.scan(client=Client([[sale("p2", "Kichik", 1, 100),
                           sale("p1", "Katta", 1, 9000)]]))
    assert a.abc()[0]["name"] == "Katta"


# --- turib qolganlar ---

def test_umuman_sotilmagan_katalogdan_ayiriladi(env):
    """Bito hisoboti sotilmaganlarni ko'rsatmaydi — ayirish shart."""
    a = env["a"]
    a.scan(client=Client([[sale("p1", "Coca-Cola", 300, 1000)]]))
    names = {row["name"] for row in a.stale()}
    assert "Eskirgan tovar" in names
    assert "Non" in names
    assert "Coca-Cola" not in names


def test_nol_qoldiqli_turib_qolganlarga_tushmaydi(env):
    a = env["a"]
    a.scan(client=Client([[sale("p1", "Coca-Cola", 1, 1)]]))
    names = {row["name"] for row in a.stale()}
    assert "Nol qoldiq" not in names


def test_katta_qoldiq_birinchi(env):
    a = env["a"]
    a.scan(client=Client([[sale("p1", "Coca-Cola", 1, 1)]]))
    rows = a.stale()
    assert rows[0]["name"] == "Non"        # 100 dona


# --- sekin sotilayotganlar ---

def test_sekin_sotilayotganlar(env):
    a = env["a"]
    # Non: kuniga 0.1 dona, qoldiq 100 -> 1000 kun
    a.scan(client=Client([[sale("p2", "Non", 3, 1000)]]))
    rows = a.slow_movers(max_days_stock=90)
    assert rows and rows[0]["name"] == "Non"
    assert rows[0]["days_left"] > 900


def test_tez_sotilayotgan_sekin_royxatda_yoq(env):
    a = env["a"]
    a.scan(client=Client([[sale("p1", "Coca-Cola", 300, 1000)]]))
    assert a.slow_movers(max_days_stock=90) == []


def test_tahlil_biznesga_xos(env):
    a, ctx = env["a"], env["ctx"]
    tenants = importlib.import_module("bot.tenants")
    a.scan(client=Client([[sale("p1", "Coca-Cola", 300, 1000)]]))
    with ctx.scope(tenants.create(50)):
        assert a.stats() == []


def test_modul_omborga_boglik(env):
    registry = importlib.import_module("bot.modules.registry")
    registry.load()
    modules = importlib.import_module("bot.modules")
    assert registry.BY_KEY["ombor_ai"].ready
    assert registry.BY_KEY["ombor_ai"].depends == ("ombor",)
    assert modules.needs_bito("ombor_ai")


# --- firma bo'yicha zakaz (PARITY 2-band) ---


class ZakazClient:
    """supplier filtri + xaridlar + get-by-id soxta klienti."""

    def __init__(self, supports_filter=None, purchases=None, fulls=None):
        self.supports = supports_filter          # masalan "supplier_ids"
        self._purchases = purchases or []        # [{_id, supplier_id, date}]
        self._fulls = fulls or {}                # id -> full dict
        self.paged_calls = []

    def paged(self, logical, page=1, limit=200, **filters):
        assert logical == "purchases"
        self.paged_calls.append(dict(filters))
        filters.pop("sort", None)
        if filters:
            (name, _value), = filters.items()
            if name != self.supports:
                # Bito noma'lum parametrni e'tiborsiz qoldiradi —
                # FILTRSIZ ro'yxat qaytadi (aynan xavfli holat)
                rows = self._purchases
            else:
                rows = [p for p in self._purchases
                        if str(p["supplier_id"]) == "SUP-1"]
        else:
            rows = self._purchases
        start = (page - 1) * limit
        return rows[start:start + limit], len(rows)

    def purchase_by_id(self, pid):
        return self._fulls.get(pid, {})


def _full(date, *products):
    return {"date": date, "orders": [{"products": [
        {"product": {"_id": pid, "name": name}, "cost": cost,
         "amount": qty, "total_cost": cost * qty}
        for pid, name, cost, qty in products]}]}


def _seed_cache(env, pid, name, qty30, stock):
    db, ctx = env["db"], env["ctx"]
    db.run("INSERT INTO sales_stat (tenant_id, product_id, name, qty, days, "
           "revenue) VALUES (?, ?, ?, ?, 30, 0)",
           (ctx.current(), pid, name, qty30))
    env["catalog"].upsert({"_id": pid, "name": name, "barcodes": [],
                           "measure": {"short_name": "Dona"}, "sku": None,
                           "category": {"name": "x"}, "_amount": stock})


def test_filtr_hammasi_mos_kelsagina_qabul(env):
    """Bito noma'lum parametrni jim o'tkazadi — 200 kelishi yetarli emas."""
    m = env["a"]
    purchases = [{"_id": "P1", "supplier_id": "SUP-1", "date": "2026-08-10"},
                 {"_id": "P2", "supplier_id": "SUP-2", "date": "2026-08-09"}]
    client = ZakazClient(supports_filter="supplier_ids",
                         purchases=purchases)
    build = m._detect_supplier_filter(client, "SUP-1")
    assert build is not None
    assert "supplier_ids" in build("SUP-1")
    # Keshlangan — keyingi safar birinchi bo'lib shu sinaladi
    tenant = importlib.import_module("bot.tenant")
    assert tenant.get("zakaz_filter_param") == "supplier_ids"


def test_filtr_ishlamasa_bruteforce(env):
    m = env["a"]
    purchases = [{"_id": f"P{i}", "supplier_id": ("SUP-1" if i % 2 else "X"),
                  "date": f"2026-08-{10 + i:02d}"} for i in range(6)]
    client = ZakazClient(supports_filter=None, purchases=purchases)
    got = m.supplier_purchases("SUP-1", client)
    assert [p["_id"] for p in got] == ["P1", "P3", "P5"]


def test_collect_products_market_bot_shakli(env):
    m = env["a"]
    fulls = [_full("2026-08-01", ("A", "Cola", 4000, 10)),
             _full("2026-08-10", ("A", "Cola", 4500, 5),
                   ("B", "Fanta", 0, 4))]
    # Fanta: cost yo'q -> total_cost/amount = 0 (total ham 0) — 0 qoladi
    records = m.collect_products(fulls)
    assert len(records) == 3
    prices = m.last_prices(records)
    assert prices["A"] == 4500          # eng yangi sana g'olib


def test_qty_text_kasr_halol(env):
    m = env["a"]
    assert m.qty_text(0.496) == "0.5"
    assert m.qty_text(2.512) == "2.51"
    assert m.qty_text(30) == "30"
    assert m.qty_text(1500) == "1,500"


def test_zakaz_hisobi(env):
    """kerak = hafta_savdosi × hafta − qoldiq; sotilmagani stale."""
    m = env["a"]
    _seed_cache(env, "A", "Cola", qty30=60, stock=4)     # kunlik 2, hafta 14
    _seed_cache(env, "B", "Sekin", qty30=0, stock=7)
    purchases = [{"_id": "P1", "supplier_id": "SUP-1", "date": "2026-08-10"}]
    fulls = {"P1": _full("2026-08-10", ("A", "Cola", 4000, 12),
                         ("B", "Sekin", 900, 6))}
    client = ZakazClient(supports_filter="supplier_id",
                         purchases=purchases, fulls=fulls)
    result = m.zakaz_for_supplier("SUP-1", weeks=2, client=client)
    assert len(result["order"]) == 1
    item = result["order"][0]
    assert item["name"] == "Cola"
    assert item["need"] == 14 * 2 - 4                    # 24
    assert item["cost"] == 24 * 4000
    assert result["total"] == 96000
    assert [s["name"] for s in result["stale"]] == ["Sekin"]


def test_zakaz_qoldiq_yetarli_bolsa_bosh(env):
    m = env["a"]
    _seed_cache(env, "A", "Cola", qty30=30, stock=100)   # hafta 7, qoldiq 100
    purchases = [{"_id": "P1", "supplier_id": "SUP-1", "date": "2026-08-10"}]
    fulls = {"P1": _full("2026-08-10", ("A", "Cola", 4000, 12))}
    client = ZakazClient(supports_filter="supplier_id",
                         purchases=purchases, fulls=fulls)
    result = m.zakaz_for_supplier("SUP-1", weeks=1, client=client)
    assert result["order"] == []
    assert result["stale"] == []
