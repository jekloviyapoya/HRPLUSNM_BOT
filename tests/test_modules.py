"""Modul litsenziyasi: yoqish, bog'liqlik, menyu."""

import importlib
import json
import sys

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
    ctx = importlib.import_module("bot.ctx")
    tenants = importlib.import_module("bot.tenants")
    tid = tenants.create(700)
    ctx.set(tid)
    return {
        "db": db, "ctx": ctx, "tid": tid, "tenants": tenants,
        "modules": importlib.import_module("bot.modules"),
        "registry": importlib.import_module("bot.modules.registry"),
        "license": importlib.import_module("bot.license"),
    }


def test_yangi_biznesda_sinov_modullari(mod):
    """Sinov davrida hammasi ochiq — mijoz nima olishini ko'rib tanlasin."""
    modules = mod["modules"]
    assert set(modules.list_enabled()) == set(modules.KEYS)


def test_boglik_modul_avtomatik_qoshiladi(mod):
    modules = mod["modules"]
    got = modules.set_enabled(["ombor_ai"])
    assert "ombor" in got                  # ombor_ai -> ombor
    assert modules.enabled("ombor")


def test_boglik_modulsiz_ishlamaydi(mod):
    """Bazaga qo'lda yozilgan noto'g'ri holat ham ushlanadi."""
    modules, db, tid = mod["modules"], mod["db"], mod["tid"]
    db.run("UPDATE license SET modules = ? WHERE tenant_id = ?",
           (json.dumps(["ombor_ai"]), tid))
    with pytest.raises(modules.ModuleError):
        modules.require("ombor_ai")


def test_nomalum_kalit_etiborsiz(mod):
    """Kelajakdagi modullar eski botni yiqitmasin."""
    modules = mod["modules"]
    got = modules.set_enabled(["xodimlar", "kelajakdagi_modul"])
    assert got == ["xodimlar"]


def test_yoqilmagan_modul_xato_beradi(mod):
    modules = mod["modules"]
    modules.set_enabled(["xodimlar"])
    with pytest.raises(modules.ModuleError) as exc:
        modules.require("nakladnoy")
    assert "Nakladnoy" in str(exc.value)


def test_qulflangan_obunada_hamma_modul_yopiq(mod):
    modules, lic, db, tid = mod["modules"], mod["license"], mod["db"], mod["tid"]
    modules.set_enabled(["xodimlar"])
    db.run("UPDATE license SET expires_at = '2000-01-01', state = 'locked' "
           "WHERE tenant_id = ?", (tid,))
    with pytest.raises(lic.LicenseError):
        modules.require("xodimlar")


def test_tartib_katalog_boyicha(mod):
    modules = mod["modules"]
    modules.set_enabled(["mijoz", "xodimlar", "ombor"])
    assert modules.list_enabled() == ["xodimlar", "ombor", "mijoz"]


def test_yozilmagan_modul_menyuda_yoq(mod):
    """Katalogda bor, lekin impl yo'q -> menyuda ko'rinmaydi."""
    modules = mod["modules"]
    modules.set_enabled(list(modules.KEYS))
    ready = {s.key for s in modules.registry.implemented()}
    shown = {s.key for s in modules.available()}
    assert shown == ready


def test_katalog_holati_uch_qismli(mod):
    modules = mod["modules"]
    modules.set_enabled(["xodimlar"])
    status = dict((s.key, (on, ready)) for s, on, ready in modules.catalog_status())
    assert status["xodimlar"][0] is True
    assert status["nakladnoy"][0] is False
    assert len(status) == len(modules.KEYS)


def test_buzuq_json_botni_yiqitmaydi(mod):
    modules, db, tid = mod["modules"], mod["db"], mod["tid"]
    db.run("UPDATE license SET modules = 'buzuq{' WHERE tenant_id = ?", (tid,))
    assert modules.list_enabled() == []
    with pytest.raises(modules.ModuleError):
        modules.require("xodimlar")


def test_modul_boyicha_tenantlar(mod):
    modules, tenants, ctx = mod["modules"], mod["tenants"], mod["ctx"]
    b = tenants.create(701)
    modules.set_enabled(["xodimlar"])
    with ctx.scope(b):
        modules.set_enabled(["ombor"])
    assert mod["tid"] in modules.tenants_with("xodimlar")
    assert b not in modules.tenants_with("xodimlar")
    assert b in modules.tenants_with("ombor")


def test_serverdan_modullar_kelmasa_eskisi_saqlanadi(mod):
    """Server nosozligi mijozning modullarini o'chirib qo'ymasin."""
    modules, lic = mod["modules"], mod["license"]
    licsrv = importlib.import_module("bot.licsrv")
    modules.set_enabled(["xodimlar", "ombor"])
    assert licsrv.modules_of({"status": "active"}) is None
    assert licsrv.modules_of({"status": "active", "modules": []}) == []
    assert licsrv.modules_of({"modules": ["a", "b"]}) == ["a", "b"]


def test_expires_ikkala_nom_bilan(mod):
    licsrv = importlib.import_module("bot.licsrv")
    assert licsrv.expires_of({"expires_at": "2026-12-31T00:00:00"}) == "2026-12-31"
    assert licsrv.expires_of({"expires": "2026-11-30"}) == "2026-11-30"
    assert licsrv.expires_of({}) is None


def test_message_maydoni_notice_orniga(mod):
    licsrv = importlib.import_module("bot.licsrv")
    got = licsrv.notice_of({"message": "To'lov kutilmoqda"})
    assert got["text"] == "To'lov kutilmoqda"
    assert licsrv.notice_of({}) is None
