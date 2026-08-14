"""Ombor moduli: chegara, skaner, qidiruv."""

import importlib
import sys

import pytest


class FakeClient:
    """Bito o'rniga: sahifalab mahsulot qaytaradi."""

    def __init__(self, pages, total=None, boom=None):
        self.pages = pages
        self.total = total if total is not None else sum(len(p) for p in pages)
        self.boom = boom
        self.calls = []

    def products(self, page=1, limit=200, search=None, category_id=None):
        self.calls.append({"page": page, "limit": limit, "search": search})
        if self.boom and page >= self.boom:
            from bot.errors import BitoError
            raise BitoError("Bito serverida nosozlik")
        if search is not None:
            rows = [p for page_rows in self.pages for p in page_rows
                    if search.lower() in (p.get("name") or "").lower()]
            return rows[:limit], len(rows)
        index = page - 1
        rows = self.pages[index] if index < len(self.pages) else []
        return rows, self.total


ORG = "org1"
WH = "wh1"


def product(name, amount, red=0, yellow=0, pid=None, sku="", measure="Dona"):
    return {
        "_id": pid or name.lower().replace(" ", "-"),
        "name": name,
        "sku": sku,
        "measure": {"short_name": measure, "name": measure},
        "category": {"name": "Ichimlik"},
        "organizations": [{
            "organization_id": ORG, "amount": amount,
            "red_line": red, "yellow_line": yellow, "standard": 10,
        }],
        "_warehouses": {WH: {"amount": amount}},
    }


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
    tid = tenants.create(800, name="Egasi")
    ctx.set(tid)
    tenant = importlib.import_module("bot.tenant")
    tenant.set("bito_org_id", ORG)
    tenant.set("warehouse_id", WH)
    tenant.set("bito_api_key", "GB-x")
    tenant.set("price_id", "p1")
    return {"o": importlib.import_module("bot.modules.ombor"),
            "tenant": tenant, "db": db, "ctx": ctx, "tid": tid,
            "tenants": tenants}


# --- qoldiq va chegara ---

def test_ombor_boyicha_qoldiq_olinadi(env):
    o = env["o"]
    assert o.amount_of(product("Non", 14)) == 14


def test_ombor_yozuvi_yoq_bolsa_tashkilotdan(env):
    o = env["o"]
    p = product("Non", 14)
    del p["_warehouses"]
    assert o.amount_of(p) == 14


def test_boshqa_ombor_qoldigi_qoshilmaydi(env):
    o = env["o"]
    p = product("Non", 5)
    p["_warehouses"] = {"boshqa": {"amount": 999}}
    assert o.amount_of(p) == 0


def test_qizil_chiziq_chegara_boladi(env):
    o = env["o"]
    assert o.threshold_of(product("Non", 5, red=3)) == 3


def test_qizil_yoq_bolsa_sariq(env):
    o = env["o"]
    assert o.threshold_of(product("Non", 5, yellow=7)) == 7


def test_chegara_toldirilmagan_bolsa_yoq(env):
    """Eng muhim: aks holda 11 000 mahsulotning yarmi «kam» bo'lib chiqadi."""
    o = env["o"]
    assert o.threshold_of(product("Non", 5)) is None
    assert o.status_of(product("Non", 5)) is None


def test_sozlamadagi_standart_chegara(env):
    o, tenant = env["o"], env["tenant"]
    tenant.set("low_stock_default", 10)
    assert o.threshold_of(product("Non", 5)) == 10
    assert o.status_of(product("Non", 5)) == "kam"
    assert o.status_of(product("Non", 50)) is None


def test_nol_qoldiq_har_doim_tugagan(env):
    o = env["o"]
    assert o.status_of(product("Non", 0)) == "tugagan"
    assert o.status_of(product("Non", -2)) == "tugagan"


def test_chegaraga_teng_ham_kam_hisoblanadi(env):
    o = env["o"]
    assert o.status_of(product("Non", 3, red=3)) == "kam"
    assert o.status_of(product("Non", 4, red=3)) is None


# --- skaner ---

def test_skaner_faqat_chegaradan_pastdagilarni_saqlaydi(env):
    o = env["o"]
    client = FakeClient([[
        product("Non", 0),
        product("Sut", 2, red=5),
        product("Yog'", 100, red=5),
    ]])
    result = o.scan(client=client)
    assert result["out"] == 1
    assert result["low"] == 1
    names = {r["name"] for r in o.low_items()}
    assert names == {"Non", "Sut"}


def test_skaner_sahifalarni_varaqlaydi(env):
    o = env["o"]
    pages = [[product(f"P{i}", 0) for i in range(200)],
             [product("Oxirgi", 0)]]
    client = FakeClient(pages, total=201)
    result = o.scan(client=client)
    assert result["out"] == 201
    assert [c["page"] for c in client.calls] == [1, 2]


def test_qoldiq_tiklangach_keshdan_ochadi(env):
    o = env["o"]
    o.scan(client=FakeClient([[product("Non", 0)]]))
    assert o.counts()["out"] == 1
    o.scan(client=FakeClient([[product("Non", 50)]]))
    assert o.counts()["all"] == 0


def test_skaner_xatosi_qayd_etiladi(env):
    o = env["o"]
    errors = importlib.import_module("bot.errors")
    client = FakeClient([[product("Non", 0)] * 200, []], boom=2)
    with pytest.raises(errors.BitoError):
        o.scan(client=client)
    assert o.scan_state()["error"]
    assert o.scan_state()["finished_at"] is None


def test_juda_katta_katalog_belgilanadi(env):
    o = env["o"]
    pages = [[product(f"P{p}-{i}", 0) for i in range(200)] for p in range(3)]
    result = o.scan(client=FakeClient(pages), max_pages=2)
    assert result["truncated"] is True


def test_skaner_biznesga_xos(env):
    o, tenants, ctx, tenant = env["o"], env["tenants"], env["ctx"], env["tenant"]
    o.scan(client=FakeClient([[product("Non", 0)]]))
    other = tenants.create(801)
    with ctx.scope(other):
        tenant.set("bito_org_id", ORG)
        tenant.set("warehouse_id", WH)
        assert o.counts()["all"] == 0
    assert o.counts()["all"] == 1


def test_hisoblar(env):
    o = env["o"]
    o.scan(client=FakeClient([[
        product("A", 0), product("B", 0), product("C", 1, red=5),
    ]]))
    assert o.counts() == {"all": 3, "out": 2, "low": 1}


# --- qidiruv ---

def test_qidiruv_jonli_bitta_sorov(env):
    o = env["o"]
    client = FakeClient([[product("Lochira non", 2), product("Sut", 5)]])
    rows = o.search("non", client=client)
    assert len(rows) == 1
    assert rows[0]["name"] == "Lochira non"
    assert rows[0]["amount"] == 2
    assert len(client.calls) == 1
    assert client.calls[0]["page"] == 1


def test_qidiruvda_holat_korsatiladi(env):
    o = env["o"]
    client = FakeClient([[product("Non", 0), product("Nonushta", 99)]])
    rows = {r["name"]: r for r in o.search("non", client=client)}
    assert rows["Non"]["status"] == "tugagan"
    assert rows["Nonushta"]["status"] is None


# --- modul ---

def test_modul_reyestrda_va_bito_talab_qiladi(env):
    registry = importlib.import_module("bot.modules.registry")
    registry.load()
    assert registry.BY_KEY["ombor"].ready
    modules = importlib.import_module("bot.modules")
    assert modules.needs_bito("ombor")


def test_fon_ishi_elon_qilingan(env):
    registry = importlib.import_module("bot.modules.registry")
    registry.load()
    jobs = registry.BY_KEY["ombor"].impl.jobs()
    assert jobs and jobs[0][0] == "ombor_scan"
