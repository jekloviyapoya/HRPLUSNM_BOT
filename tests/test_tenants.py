"""Ko'p ijarachi: ajratilganlik va taklif kodlari."""

import importlib
import sys
import threading

import pytest


@pytest.fixture()
def mod(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
    monkeypatch.setenv("SAAS_OWNER_ID", "111")
    for name in list(sys.modules):
        if name == "bot" or name.startswith("bot."):
            del sys.modules[name]
    db = importlib.import_module("bot.db")
    db.migrate()
    return {
        "db": db,
        "ctx": importlib.import_module("bot.ctx"),
        "tenants": importlib.import_module("bot.tenants"),
        "tenant": importlib.import_module("bot.tenant"),
        "users": importlib.import_module("bot.users"),
        "license": importlib.import_module("bot.license"),
        "errors": importlib.import_module("bot.errors"),
    }


def test_ikki_biznes_sozlamasi_aralashmaydi(mod):
    t, tenant, ctx = mod["tenants"], mod["tenant"], mod["ctx"]
    a = t.create(1001, name="Ali")
    b = t.create(1002, name="Vali")
    assert a != b

    with ctx.scope(a):
        tenant.set("bito_api_key", "KALIT-A")
        tenant.set("shop_name", "Do'kon A")
    with ctx.scope(b):
        tenant.set("bito_api_key", "KALIT-B")
        tenant.set("shop_name", "Do'kon B")

    with ctx.scope(a):
        assert tenant.get("bito_api_key") == "KALIT-A"
        assert tenant.shop_name() == "Do'kon A"
    with ctx.scope(b):
        assert tenant.get("bito_api_key") == "KALIT-B"
        assert tenant.shop_name() == "Do'kon B"


def test_kontekstsiz_sozlama_oqilmaydi(mod):
    ctx, tenant = mod["ctx"], mod["tenant"]
    ctx.clear()
    with pytest.raises(ctx.NoTenant):
        tenant.get("shop_name")


def test_kesh_bizneslar_orasida_oqmaydi(mod):
    t, tenant, ctx = mod["tenants"], mod["tenant"], mod["ctx"]
    a, b = t.create(2001), t.create(2002)
    with ctx.scope(a):
        tenant.set("price_id", "A")
        assert tenant.get("price_id") == "A"
    with ctx.scope(b):
        assert tenant.get("price_id") is None


def test_taklif_kodi_bilan_qoshilish(mod):
    t, ctx, users = mod["tenants"], mod["ctx"], mod["users"]
    a = t.create(3001)
    with ctx.scope(a):
        code = t.invite_code()
    assert len(code) == 6

    joined = t.join(3002, code, name="Xodim")
    assert joined == a
    with ctx.scope(a):
        assert users.role_of(3002) == "staff"
        assert len(users.listing()) == 2


def test_notogri_kod_rad_etiladi(mod):
    t = mod["tenants"]
    t.create(4001)
    with pytest.raises(t.JoinError):
        t.join(4002, "YOQKOD")


def test_kod_yangilangach_eskisi_ishlamaydi(mod):
    t, ctx = mod["tenants"], mod["ctx"]
    a = t.create(5001)
    with ctx.scope(a):
        old = t.invite_code()
        new = t.rotate_code()
    assert old != new
    with pytest.raises(t.JoinError):
        t.join(5002, old)
    assert t.join(5003, new) == a


def test_bir_odam_bitta_biznesda(mod):
    t = mod["tenants"]
    errors = mod["errors"]
    a = t.create(6001)
    with pytest.raises(errors.BotError):
        t.create(6001)
    b = t.create(6002)
    with ctx_code(mod, b) as code:
        with pytest.raises(t.JoinError):
            t.join(6001, code)
    assert t.find_by_user(6001) == a


class ctx_code:
    def __init__(self, mod, tenant_id):
        self.mod, self.tenant_id = mod, tenant_id

    def __enter__(self):
        self.scope = self.mod["ctx"].scope(self.tenant_id)
        self.scope.__enter__()
        return self.mod["tenants"].invite_code()

    def __exit__(self, *exc):
        return self.scope.__exit__(*exc)


def test_modullar_har_biznesda_alohida(mod):
    t, ctx = mod["tenants"], mod["ctx"]
    modules = importlib.import_module("bot.modules")
    a, b = t.create(7001), t.create(7002)
    with ctx.scope(a):
        modules.set_enabled(["xodimlar", "ombor"])
    with ctx.scope(b):
        modules.set_enabled(["mijoz"])
    with ctx.scope(a):
        assert modules.list_enabled() == ["xodimlar", "ombor"]
        assert modules.enabled("ombor")
    with ctx.scope(b):
        assert modules.list_enabled() == ["mijoz"]
        assert not modules.enabled("ombor")


def test_threadlar_orasida_kontekst_oqmaydi(mod):
    """Eng muhim test: ikki thread bir vaqtda boshqa biznesda ishlaydi."""
    t, tenant, ctx = mod["tenants"], mod["tenant"], mod["ctx"]
    a, b = t.create(8001), t.create(8002)
    with ctx.scope(a):
        tenant.set("shop_name", "A")
    with ctx.scope(b):
        tenant.set("shop_name", "B")

    seen = {}
    barrier = threading.Barrier(2)

    def worker(tenant_id, label):
        with ctx.scope(tenant_id):
            barrier.wait(timeout=5)   # ikkalasi bir vaqtda kontekst ichida
            seen[label] = tenant.shop_name()

    threads = [
        threading.Thread(target=worker, args=(a, "a")),
        threading.Thread(target=worker, args=(b, "b")),
    ]
    for th in threads:
        th.start()
    for th in threads:
        th.join(timeout=5)

    assert seen == {"a": "A", "b": "B"}


def test_sotuvchi_royxati(mod):
    t, ctx, tenant = mod["tenants"], mod["ctx"], mod["tenant"]
    a = t.create(9001)
    with ctx.scope(a):
        tenant.set("shop_name", "Ro'yxat testi")
    rows = t.listing()
    assert len(rows) == 1
    assert rows[0]["shop_name"] == "Ro'yxat testi"
    assert rows[0]["staff_count"] == 1
    assert rows[0]["state"] == "trial"
