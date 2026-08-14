"""Vazifalar: oqim, ballar, muddat."""

import datetime as dt
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
    users = importlib.import_module("bot.users")
    users.upsert(20, name="Ali", role="staff")
    users.upsert(21, name="Vali", role="staff")
    users.upsert(30, name="Menejer", role="manager")
    return {"v": importlib.import_module("bot.modules.vazifalar"),
            "x": importlib.import_module("bot.modules.xodimlar"),
            "users": users, "db": db, "ctx": ctx,
            "errors": importlib.import_module("bot.errors")}


def _freeze(env, monkeypatch, when):
    monkeypatch.setattr(env["v"], "now", lambda: when)
    monkeypatch.setattr(env["x"], "now_local", lambda: when)


TZ = dt.timezone(dt.timedelta(hours=5))


# --- muddat matnini o'qish ---

def test_muddat_bugun_ertaga(env, monkeypatch):
    v = env["v"]
    _freeze(env, monkeypatch, dt.datetime(2026, 8, 17, 10, 0, tzinfo=TZ))
    assert v._parse_due("bugun 18:00").startswith("2026-08-17T18:00")
    assert v._parse_due("ertaga").startswith("2026-08-18T18:00")
    assert v._parse_due("3 kun").startswith("2026-08-20")


def test_muddat_sana_bilan(env, monkeypatch):
    v = env["v"]
    _freeze(env, monkeypatch, dt.datetime(2026, 8, 17, 10, 0, tzinfo=TZ))
    assert v._parse_due("2026-09-01 09:30").startswith("2026-09-01T09:30")


def test_muddatsiz(env, monkeypatch):
    v = env["v"]
    _freeze(env, monkeypatch, dt.datetime(2026, 8, 17, tzinfo=TZ))
    assert v._parse_due("yo'q") is None
    assert v._parse_due("") is None


def test_tushunarsiz_muddat_xato(env, monkeypatch):
    v = env["v"]
    _freeze(env, monkeypatch, dt.datetime(2026, 8, 17, tzinfo=TZ))
    with pytest.raises(env["errors"].BotError):
        v._parse_due("qachondir")


# --- yaratish ---

def test_qisqa_vazifa_rad_etiladi(env):
    v = env["v"]
    with pytest.raises(env["errors"].BotError):
        v.create("ok", created_by=30)


def test_vazifa_yaratiladi(env):
    v = env["v"]
    task_id = v.create("Javonlarni tozalash", created_by=30, assigned_to=20)
    task = v.get(task_id)
    assert task["status"] == "yangi"
    assert task["assigned_to"] == 20
    assert task["points"] == 1


# --- oqim ---

def test_toliq_oqim_ball_beradi(env):
    v, x = env["v"], env["x"]
    task_id = v.create("Tozalash", created_by=30, assigned_to=20, points=5)
    v.take(task_id, 20)
    assert v.get(task_id)["status"] == "bajarilmoqda"
    v.report(task_id, 20, text="Tayyor")
    assert v.get(task_id)["status"] == "tekshiruvda"
    assert x.points_total(20) == 0          # hali ball yo'q
    v.approve(task_id, 30)
    assert v.get(task_id)["status"] == "bajarildi"
    assert x.points_total(20) == 5


def test_tasdiqlanmaguncha_ball_yoq(env):
    """Xodim o'zi «bajardim» desa ball berilmaydi."""
    v, x = env["v"], env["x"]
    task_id = v.create("Tozalash", created_by=30, assigned_to=20, points=3)
    v.report(task_id, 20)
    assert x.points_total(20) == 0


def test_qaytarilgan_vazifa_qayta_bajariladi(env):
    v, x = env["v"], env["x"]
    task_id = v.create("Tozalash", created_by=30, assigned_to=20, points=2)
    v.report(task_id, 20)
    v.reject(task_id, 30, "Yaxshi tozalanmagan")
    task = v.get(task_id)
    assert task["status"] == "qaytarildi"
    assert task["done_at"] is None
    assert x.points_total(20) == 0
    v.report(task_id, 20, text="Qaytadan qildim")
    v.approve(task_id, 30)
    assert x.points_total(20) == 2


def test_ikki_marta_tasdiqlanmaydi(env):
    v, x = env["v"], env["x"]
    task_id = v.create("Tozalash", created_by=30, assigned_to=20, points=4)
    v.report(task_id, 20)
    v.approve(task_id, 30)
    with pytest.raises(env["errors"].BotError):
        v.approve(task_id, 30)
    assert x.points_total(20) == 4          # ikki marta berilmadi


def test_yopilgan_vazifaga_hisobot_berilmaydi(env):
    v = env["v"]
    task_id = v.create("Tozalash", created_by=30, assigned_to=20)
    v.report(task_id, 20)
    v.approve(task_id, 30)
    with pytest.raises(env["errors"].BotError):
        v.report(task_id, 20)


# --- hammaga berilgan vazifa ---

def test_hammaga_berilgan_vazifa_hammada_korinadi(env):
    v = env["v"]
    task_id = v.create("Umumiy ish", created_by=30)
    assert task_id in [t["id"] for t in v.for_user(20)]
    assert task_id in [t["id"] for t in v.for_user(21)]


def test_qabul_qilgan_odamga_biriktiriladi(env):
    v = env["v"]
    task_id = v.create("Umumiy ish", created_by=30)
    v.take(task_id, 21)
    assert v.get(task_id)["assigned_to"] == 21
    assert task_id not in [t["id"] for t in v.for_user(20)]


# --- muddat ---

def test_muddati_otgan_ball_ayiradi(env, monkeypatch):
    v, x = env["v"], env["x"]
    _freeze(env, monkeypatch, dt.datetime(2026, 8, 17, 10, 0, tzinfo=TZ))
    task_id = v.create("Kech qolgan", created_by=30, assigned_to=20,
                       due=v._parse_due("bugun 12:00"))
    assert v.overdue() == []

    _freeze(env, monkeypatch, dt.datetime(2026, 8, 17, 13, 0, tzinfo=TZ))
    assert len(v.overdue()) == 1
    v.check_overdue()
    assert x.points_total(20) == -v.LATE_PENALTY


def test_ball_bir_marta_ayiriladi(env, monkeypatch):
    v, x = env["v"], env["x"]
    _freeze(env, monkeypatch, dt.datetime(2026, 8, 17, 10, 0, tzinfo=TZ))
    v.create("Kech", created_by=30, assigned_to=20,
             due=v._parse_due("bugun 09:00"))
    _freeze(env, monkeypatch, dt.datetime(2026, 8, 17, 13, 0, tzinfo=TZ))
    v.check_overdue()
    v.check_overdue()
    v.check_overdue()
    assert x.points_total(20) == -v.LATE_PENALTY


def test_bajarilgan_vazifa_kechikkan_hisoblanmaydi(env, monkeypatch):
    v, x = env["v"], env["x"]
    _freeze(env, monkeypatch, dt.datetime(2026, 8, 17, 10, 0, tzinfo=TZ))
    task_id = v.create("Vaqtida", created_by=30, assigned_to=20,
                       due=v._parse_due("bugun 12:00"))
    v.report(task_id, 20)
    v.approve(task_id, 30)
    _freeze(env, monkeypatch, dt.datetime(2026, 8, 17, 15, 0, tzinfo=TZ))
    assert v.overdue() == []


def test_muddatsiz_vazifa_kechikmaydi(env, monkeypatch):
    v = env["v"]
    _freeze(env, monkeypatch, dt.datetime(2026, 8, 17, 10, 0, tzinfo=TZ))
    v.create("Muddatsiz", created_by=30, assigned_to=20)
    _freeze(env, monkeypatch, dt.datetime(2027, 1, 1, tzinfo=TZ))
    assert v.overdue() == []


# --- hisobot ---

def test_statistika(env, monkeypatch):
    v = env["v"]
    _freeze(env, monkeypatch, dt.datetime(2026, 8, 17, 10, 0, tzinfo=TZ))
    a = v.create("Bir", created_by=30, assigned_to=20)
    v.create("Ikki", created_by=30, assigned_to=20)
    v.report(a, 20)
    v.approve(a, 30)
    numbers = v.stats(20, period=f"{dt.date.today():%Y-%m}")
    assert numbers["jami"] == 2
    assert numbers["bajarildi"] == 1
    assert numbers["ochiq"] == 1


def test_boshqa_biznes_vazifasi_korinmaydi(env):
    v, ctx = env["v"], env["ctx"]
    tenants = importlib.import_module("bot.tenants")
    v.create("Bizniki", created_by=30, assigned_to=20)
    other = tenants.create(50)
    with ctx.scope(other):
        assert v.for_user(20) == []


def test_modul_reyestrda_bitosiz(env):
    registry = importlib.import_module("bot.modules.registry")
    registry.load()
    modules = importlib.import_module("bot.modules")
    assert registry.BY_KEY["vazifalar"].ready
    assert not modules.needs_bito("vazifalar")


# --- ishga kelganda yetkazish (market-bot 1ac6fd9 saboqi) ---

def test_ochiq_vazifalar_yetkazish_uchun(env):
    """Ish vaqtidan tashqarida berilgan vazifa ko'rinmay qolmasin."""
    v = env["v"]
    a = v.create("Ertalabki ish", created_by=30, assigned_to=20)
    v.create("Umumiy ish", created_by=30)
    done = v.create("Bajarilgan", created_by=30, assigned_to=20)
    v.report(done, 20)
    v.approve(done, 30)

    rows = v.pending_for(20)
    titles = [r["title"] for r in rows]
    assert "Ertalabki ish" in titles
    assert "Umumiy ish" in titles          # hammaga berilgani ham
    assert "Bajarilgan" not in titles
    del a


def test_qaytarilgan_vazifa_ham_yetkaziladi(env):
    v = env["v"]
    task_id = v.create("Qaytarilgan", created_by=30, assigned_to=20)
    v.report(task_id, 20)
    v.reject(task_id, 30, "Qayta qiling")
    assert "Qaytarilgan" in [r["title"] for r in v.pending_for(20)]


def test_boshqa_xodim_vazifasi_yetkazilmaydi(env):
    v = env["v"]
    v.create("Valining ishi", created_by=30, assigned_to=21)
    assert v.pending_for(20) == []
