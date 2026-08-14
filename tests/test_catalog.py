"""Katalog keshi va moslashtirish."""

import importlib
import sys

import pytest


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
    tenants = importlib.import_module("bot.tenants")
    tid = tenants.create(950)
    ctx.set(tid)
    return {"c": importlib.import_module("bot.catalog"),
            "db": db, "ctx": ctx, "tid": tid, "tenants": tenants}


def add(c, name, pid=None, sku=None, barcode=None, measure="Dona"):
    c.upsert({
        "_id": pid or name.lower().replace(" ", "-"),
        "name": name, "sku": sku,
        "barcodes": [barcode] if barcode else [],
        "measure": {"short_name": measure, "_id": "m1"},
        "category": {"name": "Ichimlik"},
    })


# --- normallash ---

def test_normallash_tinish_belgisini_olib_tashlaydi(env):
    c = env["c"]
    # Defis bo'shliqqa aylanadi: «Coca-Cola» va «Coca Cola» bir xil
    # so'zlarga bo'linsin va bir-birini topsin
    assert c.normalize("Coca-Cola 1L (yangi)") == "coca cola 1l yangi"
    assert c.normalize("Yog\' 5kg") == "yog 5kg"
    assert c.tokens("Coca-Cola") == c.tokens("Coca Cola")


def test_olcham_soqzlari_hisobga_olinmaydi(env):
    c = env["c"]
    assert "dona" not in c.tokens("Non 5 dona")


def test_ball_ustma_ustlik(env):
    c = env["c"]
    assert c.score(c.tokens("Coca Cola 1L"), c.tokens("Coca Cola 1L")) == 1.0
    assert c.score(c.tokens("Coca Cola"), c.tokens("Fanta Sprite")) == 0.0
    assert 0 < c.score(c.tokens("Coca Cola 1L"), c.tokens("Coca Cola 2L")) < 1


# --- kesh ---

def test_kesh_yoziladi_va_yangilanadi(env):
    c = env["c"]
    add(c, "Coca-Cola 1L", pid="p1")
    assert c.size() == 1
    add(c, "Coca-Cola 1 Litr", pid="p1")
    assert c.size() == 1
    assert c.all_rows()[0]["name"] == "Coca-Cola 1 Litr"


def test_kesh_biznesga_xos(env):
    c, tenants, ctx = env["c"], env["tenants"], env["ctx"]
    add(c, "Non")
    other = tenants.create(951)
    with ctx.scope(other):
        assert c.size() == 0
    assert c.size() == 1


def test_bosh_kesh_eskirgan_hisoblanadi(env):
    c = env["c"]
    assert c.is_stale()
    add(c, "Non")
    assert not c.is_stale()


# --- moslashtirish tartibi ---

def test_shtrix_kod_aniq_mos(env):
    c = env["c"]
    add(c, "Coca-Cola 1L", pid="p1", barcode="5449000000996")
    add(c, "Boshqa", pid="p2")
    got = c.match("umuman boshqa nom", barcode="5449000000996")
    assert got["state"] == "topildi"
    assert got["product_id"] == "p1"
    assert got["how"] == "shtrix-kod"


def test_sku_aniq_mos(env):
    c = env["c"]
    add(c, "Coca-Cola 1L", pid="p1", sku="27690")
    got = c.match("27690")
    assert got["product_id"] == "p1"
    assert got["how"] == "SKU"


def test_aniq_nom_mos(env):
    c = env["c"]
    add(c, "Coca-Cola 1L", pid="p1")
    got = c.match("coca cola 1l")
    assert got["state"] == "topildi"
    assert got["how"] == "nom"


def test_xotira_hammasidan_ustun(env):
    """Odam tanlagani eng ishonchli manba."""
    c = env["c"]
    add(c, "Coca-Cola 1L", pid="p1", barcode="111")
    add(c, "Fanta", pid="p2")
    c.remember("Coca-Cola 1L", "p2", "Fanta")
    got = c.match("Coca-Cola 1L", barcode="111")
    assert got["product_id"] == "p2"
    assert got["how"] == "xotira"


def test_xotira_unutiladi(env):
    c = env["c"]
    add(c, "Non", pid="p1")
    c.remember("Non", "p1", "Non")
    assert c.recall("Non")
    c.forget("Non")
    assert c.recall("Non") is None


def test_xotira_hisobi_oshadi(env):
    c = env["c"]
    c.remember("Non", "p1", "Non")
    c.remember("Non", "p1", "Non")
    assert c.aliases()[0]["used_count"] == 2


# --- taxmin qilinmaydi ---

def test_ikkilanishda_avtomatik_tanlanmaydi(env):
    """Noto'g'ri moslashtirish ombor qoldig'ini buzadi — taxmin yo'q."""
    c = env["c"]
    add(c, "Coca-Cola 1L", pid="p1")
    add(c, "Coca-Cola 2L", pid="p2")
    got = c.match("Coca-Cola")
    assert got["state"] == "yoq"
    assert len(got["candidates"]) == 2


def test_nomzodlar_ball_boyicha_tartiblanadi(env):
    c = env["c"]
    add(c, "Coca-Cola 1L", pid="p1")
    add(c, "Coca-Cola 1L yangi qadoq", pid="p2")
    got = c.match("Coca-Cola 1L original")
    names = [x["name"] for x in got["candidates"]]
    assert names[0] == "Coca-Cola 1L"


def test_umuman_oxshamasa_nomzod_yoq(env):
    c = env["c"]
    add(c, "Coca-Cola 1L", pid="p1")
    got = c.match("Kartoshka")
    assert got["state"] == "yoq"
    assert got["candidates"] == []


def test_bosh_katalogda_yiqilmaydi(env):
    c = env["c"]
    got = c.match("Non")
    assert got["state"] == "yoq"
    assert got["candidates"] == []


def test_royxat_bir_marta_oqiladi(env):
    c = env["c"]
    add(c, "Non", pid="p1")
    add(c, "Sut", pid="p2")
    results = c.match_all([
        {"raw_name": "Non", "barcode": ""},
        {"raw_name": "Sut", "barcode": ""},
        {"raw_name": "Yo'q narsa", "barcode": ""},
    ])
    assert [r["state"] for r in results] == ["topildi", "topildi", "yoq"]


# --- ombor skaneri katalogni to'ldiradimi ---

def test_ombor_skaneri_katalogni_toldiradi(env):
    c = env["c"]
    tenant = importlib.import_module("bot.tenant")
    tenant.set("bito_org_id", "o1")
    tenant.set("warehouse_id", "w1")
    ombor = importlib.import_module("bot.modules.ombor")

    class Client:
        def products(self, page=1, limit=200, search=None, category_id=None):
            if page > 1:
                return [], 2
            return [
                {"_id": "p1", "name": "Non", "sku": "1",
                 "measure": {"short_name": "Dona"},
                 "category": {"name": "Non"},
                 "organizations": [{"organization_id": "o1", "amount": 0}],
                 "_warehouses": {"w1": {"amount": 0}}},
                {"_id": "p2", "name": "Sut", "sku": "2",
                 "measure": {"short_name": "Litr"},
                 "category": {"name": "Sut"},
                 "organizations": [{"organization_id": "o1", "amount": 50}],
                 "_warehouses": {"w1": {"amount": 50}}},
            ], 2

    result = ombor.scan(client=Client())
    assert result["catalog"] == 2      # ikkalasi ham katalogda
    assert result["out"] == 1          # faqat Non tugagan
    assert c.match("Sut")["state"] == "topildi"
