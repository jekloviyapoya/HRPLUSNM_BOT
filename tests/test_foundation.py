"""Poydevor testlari. push.sh shularni chaqiradi."""

import datetime as dt
import importlib
import sys

import pytest


@pytest.fixture()
def app(tmp_path, monkeypatch):
    """Har test uchun toza baza va qayta yuklangan modullar."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
    monkeypatch.setenv("SAAS_OWNER_ID", "111")
    for name in list(sys.modules):
        if name == "bot" or name.startswith("bot."):
            del sys.modules[name]
    config = importlib.import_module("bot.config")
    db = importlib.import_module("bot.db")
    tenant = importlib.import_module("bot.tenant")
    license_ = importlib.import_module("bot.license")
    users = importlib.import_module("bot.users")
    db.migrate()
    ctx = importlib.import_module("bot.ctx")
    tenants = importlib.import_module("bot.tenants")
    tid = tenants.create(999, name="Test egasi")
    ctx.set(tid)
    return dict(config=config, db=db, tenant=tenant, license=license_,
                users=users, ctx=ctx, tenants=tenants, tenant_id=tid)


def test_migratsiya_ikki_marta_qollanmaydi(app):
    assert app["db"].migrate() == []


def test_sozlanmagan_qiymat_xato_beradi(app):
    tenant = app["tenant"]
    errors = importlib.import_module("bot.errors")
    with pytest.raises(errors.SetupError):
        tenant.require("warehouse_id")
    assert tenant.get("warehouse_id") is None


def test_sozlama_yoziladi_va_oqiladi(app):
    tenant = app["tenant"]
    tenant.set("shop_name", "Test do'kon")
    assert tenant.require("shop_name") == "Test do'kon"
    tenant.clear_cache()
    assert tenant.get("shop_name") == "Test do'kon"


def test_sinov_muddati_ochiladi(app):
    lic = app["license"]
    assert lic.state() == "trial"
    assert lic.days_left() == app["config"].TRIAL_DAYS


def test_muddat_tugasa_grace_keyin_qulf(app):
    lic, db = app["license"], app["db"]
    past = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    db.run("UPDATE license SET expires_at = ? WHERE tenant_id = ?", (past, app["tenant_id"]))
    assert lic.state() == "grace"

    far = (dt.date.today() - dt.timedelta(days=99)).isoformat()
    db.run("UPDATE license SET expires_at = ? WHERE tenant_id = ?", (far, app["tenant_id"]))
    assert lic.state() == "locked"
    assert lic.is_locked()


def test_uzaytirgach_faol_boladi(app):
    lic, db = app["license"], app["db"]
    db.run(
        "UPDATE license SET expires_at = ?, state = 'locked' WHERE tenant_id = ?",
        ((dt.date.today() - dt.timedelta(days=99)).isoformat(), app["tenant_id"]),
    )
    assert lic.is_locked()
    lic.extend((dt.date.today() + dt.timedelta(days=30)).isoformat())
    assert lic.state() == "active"


def test_modul_tekshiruvi(app):
    modules = importlib.import_module("bot.modules")
    modules.set_enabled(["xodimlar"])
    modules.require("xodimlar")          # xato bermasligi kerak
    with pytest.raises(modules.ModuleError):
        modules.require("nakladnoy")


def test_biznes_ochgan_odam_egasi_boladi(app):
    users = app["users"]
    assert users.has_owner()
    assert users.role_of(999) == "owner"


def test_rol_yetmasa_xato(app):
    users = app["users"]
    errors = importlib.import_module("bot.errors")
    users.upsert(600, name="Vali", role="staff")
    with pytest.raises(errors.AccessError):
        users.require_role(600, "manager")
    assert users.require_role(111, "owner") == "owner"  # sotuvchi


def test_takroriy_update_bir_marta_ishlanadi(app):
    db = app["db"]
    assert db.seen_update("msg:1:1") is False
    assert db.seen_update("msg:1:1") is True


def test_uzun_izoh_qisqartiriladi(app):
    ui = importlib.import_module("bot.ui")
    assert len(ui.caption("a" * 2000)) == 1024


def test_konfigda_dokonga_xos_qiymat_yoq(app):
    """Kodda qotirilgan do'kon qiymati bo'lmasligi kerak."""
    import pathlib

    banned = ("bonnu", "org_id =", "warehouse_id =", "price_id =")
    for f in pathlib.Path("bot").rglob("*.py"):
        text = f.read_text(encoding="utf-8").lower()
        for word in banned:
            assert word not in text, f"{f} ichida qotirilgan qiymat: {word}"




def test_html_qochirish(app):
    ui = importlib.import_module("bot.ui")
    assert ui.escape("<b>&x</b>") == "&lt;b&gt;&amp;x&lt;/b&gt;"


def test_sehrgar_qadamini_qaytaradi(app):
    onboarding = importlib.import_module("bot.onboarding")
    sessions = importlib.import_module("bot.sessions")
    assert onboarding.current_step(77) is None
    sessions.set(77, "setup:shop_name", {})
    assert onboarding.current_step(77) == "shop_name"
    sessions.clear(77)
    assert onboarding.current_step(77) is None


def test_sehrgar_qadamlari_sozlama_kalitlari(app):
    """STEPS dagi har kalit tenant sozlamasi bo'lishi kerak."""
    onboarding = importlib.import_module("bot.onboarding")
    tenant = app["tenant"]
    for key, label in onboarding.STEPS:
        assert isinstance(label, str) and label
        assert tenant.get(key) is None  # toza bazada hammasi bo'sh
    assert onboarding.STEPS[0][0] == "shop_name"


def test_pending_summary_sozlangach_qisqaradi(app):
    onboarding = importlib.import_module("bot.onboarding")
    tenant = app["tenant"]
    before = len(onboarding.pending_summary())
    tenant.set("shop_name", "X")
    assert len(onboarding.pending_summary()) == before - 1
