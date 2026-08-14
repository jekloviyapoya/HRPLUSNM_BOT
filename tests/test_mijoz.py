"""Mijoz baholari: statistika, QR, oqim."""

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
    tid = importlib.import_module("bot.tenants").create(10, name="Egasi")
    ctx.set(tid)
    return {"m": importlib.import_module("bot.modules.mijoz"),
            "db": db, "ctx": ctx, "tid": tid}


# --- yozuvlar ---

def test_baho_qoshiladi(env):
    m = env["m"]
    fid = m.add(tg_id=500, stars=5)
    row = m.get(fid)
    assert row["stars"] == 5
    assert row["status"] == "yangi"
    assert row["kind"] == "baho"


def test_mijoz_users_jadvaliga_yozilmaydi(env):
    """Mijoz tenant foydalanuvchisi emas."""
    m = env["m"]
    users = importlib.import_module("bot.users")
    m.add(tg_id=500, stars=4)
    assert users.get(500) is None


def test_qisman_yangilanadi(env):
    m = env["m"]
    fid = m.add(tg_id=500, stars=2)
    m.update(fid, text="Navbat uzun")
    row = m.get(fid)
    assert row["stars"] == 2          # yo'qolmadi
    assert row["text"] == "Navbat uzun"


def test_baho_chegarasi(env):
    m, db = env["m"], env["db"]
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        db.run("INSERT INTO feedback (tenant_id, stars) VALUES (?, 9)",
               (env["tid"],))


# --- statistika ---

def test_ortacha_baho(env):
    m = env["m"]
    for star in (5, 5, 4, 2):
        m.add(stars=star)
    numbers = m.stats()
    assert numbers["total"] == 4
    assert numbers["average"] == 4.0
    assert numbers["spread"][5] == 2
    assert numbers["low"] == 1        # 1 va 2 yulduz


def test_bahosiz_yozuv_ortachaga_kirmaydi(env):
    m = env["m"]
    m.add(stars=5)
    m.add(kind="taklif", text="Yangi mahsulot qo'shing")
    assert m.stats()["total"] == 1


def test_bosh_statistika_yiqilmaydi(env):
    m = env["m"]
    numbers = m.stats()
    assert numbers["total"] == 0
    assert numbers["average"] is None


# --- ro'yxat ---

def test_yangilar_sanaladi(env):
    m = env["m"]
    fid = m.add(stars=3)
    assert m.new_count() == 1
    m.update(fid, status="korildi")
    assert m.new_count() == 0


def test_turi_boyicha_filtr(env):
    m = env["m"]
    m.add(stars=5)
    m.add(kind="shikoyat", stars=1, text="Yomon")
    assert len(m.listing(kind="shikoyat")) == 1
    assert len(m.listing()) == 2


def test_yangi_avval_korsatiladi(env):
    m = env["m"]
    first = m.add(stars=1)
    second = m.add(stars=5)
    assert m.listing()[0]["id"] == second
    del first


def test_hal_qilingan_belgilanadi(env):
    m = env["m"]
    fid = m.add(stars=1, kind="shikoyat", text="Muammo")
    m.update(fid, status="hal_qilindi", answered_by=10)
    assert m.get(fid)["status"] == "hal_qilindi"


# --- QR ---

def test_qr_havolasi_tenantga_bogliq(env):
    m = env["m"]
    link = m.qr_link("HRPLUSNM_BOT")
    assert link.endswith(f"?start=baho_{env['tid']}")


def test_qr_rasm_yasaladi(env):
    m = env["m"]
    image = m.qr_png("https://t.me/x?start=baho_1")
    assert image is not None
    assert image.read(4) == b"\x89PNG"


# --- ko'rinish ---

def test_xulosa_matni(env):
    m = env["m"]
    fid = m.add(stars=2, kind="shikoyat", text="Navbat uzun", phone="+998901234567")
    text = m.summary_text(m.get(fid))
    assert "⭐⭐" in text
    assert "Shikoyat" in text
    assert "Navbat uzun" in text
    assert "+998901234567" in text


def test_past_baho_chegarasi(env):
    m = env["m"]
    assert m.ALERT_BELOW == 3        # 1 va 2 yulduz darhol egaga boradi


# --- ajratilganlik ---

def test_baholar_biznesga_xos(env):
    m, ctx = env["m"], env["ctx"]
    tenants = importlib.import_module("bot.tenants")
    m.add(stars=5)
    with ctx.scope(tenants.create(50)):
        assert m.stats()["total"] == 0
        assert m.new_count() == 0


def test_modul_bitosiz(env):
    registry = importlib.import_module("bot.modules.registry")
    registry.load()
    modules = importlib.import_module("bot.modules")
    assert registry.BY_KEY["mijoz"].ready
    assert not modules.needs_bito("mijoz")


def test_hamma_modul_yozilgan(env):
    """Katalogdagi 10 ta modulning hammasi amalga oshirilgan."""
    registry = importlib.import_module("bot.modules.registry")
    registry.load()
    missing = [spec.key for spec in registry.CATALOG if not spec.ready]
    assert missing == []
    assert len(registry.implemented()) == 10
