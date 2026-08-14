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
