"""Inventarizatsiya: mahalliy sanash, farq, Bito'ga yuklash."""

import importlib
import sys

import pytest


class Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError
        return self._payload


class Client:
    def __init__(self, create=None, add=None, status=None):
        self._create = create or Resp(200, {"data": {"_id": "r1",
                                                     "number": "INV-5"}})
        self._add = add or Resp(200, {})
        self._status = status or Resp(200, {})
        self.calls = []

    def create_revision(self, body):
        self.calls.append(("create", body))
        return self._create

    def revision_add(self, revision_id, body):
        self.calls.append(("add", body))
        return self._add

    def revision_status(self, revision_id, status):
        self.calls.append(("status", status))
        return self._status


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
    for pid, name, amount in [("p1", "Coca-Cola 1L", 50),
                              ("p2", "Non", 10), ("p3", "Sut", 0)]:
        catalog.upsert({"_id": pid, "name": name, "barcodes": [],
                        "measure": {"short_name": "Dona"}, "sku": None,
                        "category": {"name": "x"}, "_amount": amount})
    return {"i": importlib.import_module("bot.modules.inventarizatsiya"),
            "catalog": catalog, "db": db, "ctx": ctx,
            "errors": importlib.import_module("bot.errors")}


# --- sanash ---

def test_sanoq_boshlanadi(env):
    i = env["i"]
    take_id = i.start(10)
    assert i.current()["id"] == take_id
    assert i.get(take_id)["status"] == "sanalmoqda"


def test_ikkinchi_sanoq_ochilmaydi(env):
    i = env["i"]
    i.start(10)
    with pytest.raises(env["errors"].BotError):
        i.start(10)


def test_sanalgan_son_farqni_korsatadi(env):
    i = env["i"]
    take_id = i.start(10)
    row = i.count(take_id, "p1", 47)
    assert row["expected"] == 50
    assert row["counted"] == 47


def test_takroriy_sanash_almashtiradi(env):
    """Qo'shilmaydi — aks holda ikki marta sanagan odam ombori buziladi."""
    i = env["i"]
    take_id = i.start(10)
    i.count(take_id, "p1", 47)
    i.count(take_id, "p1", 52)
    rows = i.items(take_id)
    assert len(rows) == 1
    assert rows[0]["counted"] == 52


def test_katalogda_yoq_mahsulot(env):
    i = env["i"]
    take_id = i.start(10)
    with pytest.raises(env["errors"].BotError):
        i.count(take_id, "yoq", 5)


def test_xulosa(env):
    i = env["i"]
    take_id = i.start(10)
    i.count(take_id, "p1", 47)      # −3
    i.count(take_id, "p2", 12)      # +2
    i.count(take_id, "p3", 0)       # mos
    numbers = i.summary(take_id)
    assert numbers == {"count": 3, "surplus": 1, "shortage": 1, "match": 1,
                       "surplus_qty": 2, "shortage_qty": 3}


def test_faqat_farqlilar(env):
    i = env["i"]
    take_id = i.start(10)
    i.count(take_id, "p1", 47)
    i.count(take_id, "p3", 0)
    assert len(i.items(take_id, only_diff=True)) == 1


def test_bosh_sanoq_yakunlanmaydi(env):
    i = env["i"]
    take_id = i.start(10)
    with pytest.raises(env["errors"].BotError):
        i.finish(take_id)


def test_yakunlangach_yangi_sanoq_ochiladi(env):
    i = env["i"]
    take_id = i.start(10)
    i.count(take_id, "p1", 47)
    i.finish(take_id)
    assert i.current() is None
    assert i.start(10)


def test_bekor_qilingan_bito_ga_tegmaydi(env):
    i = env["i"]
    take_id = i.start(10)
    i.count(take_id, "p1", 47)
    i.cancel(take_id)
    assert i.get(take_id)["status"] == "bekor"
    assert i.current() is None


# --- Bito'ga yuklash ---

def test_uch_qadam_ketma_ket(env):
    i = env["i"]
    take_id = i.start(10)
    i.count(take_id, "p1", 47)
    i.finish(take_id)
    client = Client()
    result = i.upload(take_id, client=client)
    assert [c[0] for c in client.calls] == ["create", "add", "status"]
    assert client.calls[2][1] == "done"
    assert result["number"] == "INV-5"
    assert i.get(take_id)["status"] == "yuklandi"


def test_starting_date_yuboriladi(env):
    """Majburiy maydon — busiz Bito 400 qaytaradi."""
    i = env["i"]
    take_id = i.start(10)
    i.count(take_id, "p1", 47)
    client = Client()
    i.upload(take_id, client=client)
    body = client.calls[0][1]
    assert body["starting_date"]
    assert body["ending_date"]
    assert body["organization_id"] == "o1"
    assert body["warehouse_id"] == "w1"


def test_yaratish_yiqilsa_yuklanmaydi(env):
    i = env["i"]
    take_id = i.start(10)
    i.count(take_id, "p1", 47)
    client = Client(create=Resp(400, {"message": "starting_date"}))
    with pytest.raises(env["errors"].BitoError):
        i.upload(take_id, client=client)
    assert i.get(take_id)["status"] != "yuklandi"
    assert "starting_date" in i.get(take_id)["error"]


def test_mahsulot_qoshilmasa_ochiq_qolgani_aytiladi(env):
    """Mijoz Bito'da osilib qolgan hujjatni bilishi kerak."""
    i = env["i"]
    take_id = i.start(10)
    i.count(take_id, "p1", 47)
    client = Client(add=Resp(500, {"message": "server"}))
    with pytest.raises(env["errors"].BitoError) as exc:
        i.upload(take_id, client=client)
    assert "ochiq qoldi" in str(exc.value)


def test_yakunlanmasa_qoldiq_ozgarmagani_aytiladi(env):
    i = env["i"]
    take_id = i.start(10)
    i.count(take_id, "p1", 47)
    client = Client(status=Resp(500, {}))
    with pytest.raises(env["errors"].BitoError) as exc:
        i.upload(take_id, client=client)
    assert "qoldiq o'zgarmadi" in str(exc.value)


def test_ikki_marta_yuklanmaydi(env):
    i = env["i"]
    take_id = i.start(10)
    i.count(take_id, "p1", 47)
    i.upload(take_id, client=Client())
    with pytest.raises(env["errors"].BotError):
        i.upload(take_id, client=Client())


def test_katta_royxat_bolinadi(env):
    i = env["i"]
    catalog = env["catalog"]
    for n in range(250):
        catalog.upsert({"_id": f"x{n}", "name": f"Tovar {n}", "barcodes": [],
                        "measure": {"short_name": "Dona"}, "sku": None,
                        "category": {"name": "x"}, "_amount": 5})
    take_id = i.start(10)
    for n in range(250):
        i.count(take_id, f"x{n}", 4)
    client = Client()
    i.upload(take_id, client=client)
    adds = [c for c in client.calls if c[0] == "add"]
    assert len(adds) == 3          # 100 + 100 + 50


def test_bosh_sanoq_yuklanmaydi(env):
    i = env["i"]
    take_id = i.start(10)
    with pytest.raises(env["errors"].BotError):
        i.upload(take_id, client=Client())


def test_sanoq_biznesga_xos(env):
    i, ctx = env["i"], env["ctx"]
    tenants = importlib.import_module("bot.tenants")
    i.start(10)
    with ctx.scope(tenants.create(50)):
        assert i.current() is None


def test_modul_reyestrda_omborga_boglik(env):
    registry = importlib.import_module("bot.modules.registry")
    registry.load()
    modules = importlib.import_module("bot.modules")
    assert registry.BY_KEY["inventarizatsiya"].ready
    assert modules.needs_bito("inventarizatsiya")
    assert registry.BY_KEY["inventarizatsiya"].depends == ("ombor",)
