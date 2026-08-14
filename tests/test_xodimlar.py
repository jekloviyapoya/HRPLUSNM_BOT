"""Xodimlar moduli: davomat, ballar, ish haqi."""

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
    tenants = importlib.import_module("bot.tenants")
    tid = tenants.create(500, name="Egasi")
    ctx.set(tid)
    users = importlib.import_module("bot.users")
    users.upsert(501, name="Ali", role="staff")
    users.upsert(502, name="Vali", role="staff")
    x = importlib.import_module("bot.modules.xodimlar")
    return {"x": x, "db": db, "ctx": ctx, "tid": tid, "tenants": tenants,
            "tenant": importlib.import_module("bot.tenant"),
            "errors": importlib.import_module("bot.errors")}


def _freeze(x, monkeypatch, hour, minute=0, weekday=None):
    """now_local() ni belgilangan vaqtga qotiradi."""
    base = dt.datetime(2026, 8, 17, hour, minute,  # 2026-08-17 = dushanba
                       tzinfo=dt.timezone(dt.timedelta(hours=5)))
    if weekday is not None:
        base += dt.timedelta(days=weekday)
    monkeypatch.setattr(x, "now_local", lambda: base)
    return base


# --- vaqt formati ---

def test_vaqt_formati_turli_korinishlarda(env):
    h = env["x"]._hhmm
    assert h("9:5") == "09:05"
    assert h("09:05") == "09:05"
    assert h("9.30") == "09:30"
    assert h("0900") == "09:00"
    assert h("930") == "9:30".rjust(5, "0")
    assert h("25:00") is None
    assert h("salom") is None


def test_masofa_hisobi(env):
    d = env["x"].distance_m
    assert d(41.3111, 69.2797, 41.3111, 69.2797) == 0
    # Toshkentda ~1 km
    assert 900 < d(41.3111, 69.2797, 41.3201, 69.2797) < 1100


# --- jadval ---

def test_jadval_qoyiladi_va_almashadi(env):
    x = env["x"]
    x.set_shift(501, 0, "9:00", "18:00")
    assert x.shift_for(501, 0)["starts_at"] == "09:00"
    x.set_shift(501, 0, "10:00", "19:00")
    assert x.shift_for(501, 0)["starts_at"] == "10:00"
    assert len(x.shifts_of(501)) == 1        # eskisi active=0


def test_tugash_boshlanishdan_oldin_bolmaydi(env):
    x, errors = env["x"], env["errors"]
    with pytest.raises(errors.BotError):
        x.set_shift(501, 0, "18:00", "09:00")


# --- davomat ---

def test_oz_vaqtida_kelish_ball_beradi(env, monkeypatch):
    x = env["x"]
    x.set_shift(501, 0, "09:00", "18:00")
    _freeze(x, monkeypatch, 8, 58)
    row, text = x.check_in(501)
    assert row["status"] == "keldi"
    assert row["late_minutes"] == 0
    assert x.points_total(501) == 1
    assert "o'z vaqtida" in text


def test_kechikish_ball_ayiradi(env, monkeypatch):
    x = env["x"]
    x.set_shift(501, 0, "09:00", "18:00")
    _freeze(x, monkeypatch, 9, 25)
    row, text = x.check_in(501)
    assert row["status"] == "kechikdi"
    assert row["late_minutes"] == 25
    assert x.points_total(501) == -1
    assert "25 daqiqa" in text


def test_besh_daqiqagacha_kechikish_hisoblanmaydi(env, monkeypatch):
    x = env["x"]
    x.set_shift(501, 0, "09:00", "18:00")
    _freeze(x, monkeypatch, 9, 4)
    row, _ = x.check_in(501)
    assert row["status"] == "keldi"
    assert row["late_minutes"] == 0


def test_ikki_marta_kelish_qayd_qilinmaydi(env, monkeypatch):
    x, errors = env["x"], env["errors"]
    _freeze(x, monkeypatch, 9)
    x.check_in(501)
    with pytest.raises(errors.BotError):
        x.check_in(501)


def test_kelmasdan_ketish_mumkin_emas(env, monkeypatch):
    x, errors = env["x"], env["errors"]
    _freeze(x, monkeypatch, 18)
    with pytest.raises(errors.BotError):
        x.check_out(501)


def test_ketish_ishlagan_vaqtni_korsatadi(env, monkeypatch):
    x = env["x"]
    x.set_shift(501, 0, "09:00", "18:00")
    _freeze(x, monkeypatch, 9)
    x.check_in(501)
    _freeze(x, monkeypatch, 18, 0)
    text = x.check_out(501)
    assert "9 soat" in text


def test_erta_ketish_belgilanadi(env, monkeypatch):
    x = env["x"]
    x.set_shift(501, 0, "09:00", "18:00")
    _freeze(x, monkeypatch, 9)
    x.check_in(501)
    _freeze(x, monkeypatch, 16, 0)
    text = x.check_out(501)
    assert "erta" in text


def test_uzoqdan_kelish_rad_etiladi(env, monkeypatch):
    x, tenant, errors = env["x"], env["tenant"], env["errors"]
    tenant.set_json("work_place", {"lat": 41.3111, "lon": 69.2797})
    tenant.set("work_radius_m", 200)
    _freeze(x, monkeypatch, 9)
    with pytest.raises(errors.BotError) as exc:
        x.check_in(501, lat=41.3300, lon=69.2797)   # ~2 km
    assert "uzoqdasiz" in str(exc.value)
    assert x.record_of(501) is None                  # yozuv qoldirilmadi


def test_yaqindan_kelish_qabul_qilinadi(env, monkeypatch):
    x, tenant = env["x"], env["tenant"]
    tenant.set_json("work_place", {"lat": 41.3111, "lon": 69.2797})
    _freeze(x, monkeypatch, 9)
    row, text = x.check_in(501, lat=41.3113, lon=69.2799)
    assert row is not None
    assert "m." in text


def test_jadvalsiz_kun_kechikish_hisoblanmaydi(env, monkeypatch):
    x = env["x"]
    _freeze(x, monkeypatch, 14)          # jadval yo'q
    row, text = x.check_in(501)
    assert row["status"] == "keldi"
    assert x.points_total(501) == 0
    assert "jadval qo'yilmagan" in text


def test_kelmagan_deb_belgilash(env, monkeypatch):
    x = env["x"]
    x.mark_absent(501, "2026-08-17")
    assert x.record_of(501, "2026-08-17")["status"] == "kelmadi"
    assert x.points_total(501) == -3
    x.mark_absent(501, "2026-08-17", reason="Kasal")
    assert x.record_of(501, "2026-08-17")["status"] == "sababli"


# --- ballar va reyting ---

def test_ball_yigindisi_har_safar_hisoblanadi(env):
    x = env["x"]
    x.add_points(501, 5, "Yaxshi ish")
    x.add_points(501, -2, "Xato")
    x.add_points(501, 3, "Tuzatdi")
    assert x.points_total(501) == 6


def test_reyting_kamayish_tartibida(env):
    x = env["x"]
    x.add_points(501, 3, "a")
    x.add_points(502, 7, "b")
    rows = x.rating()
    assert rows[0]["tg_id"] == 502
    assert rows[0]["total"] == 7
    assert rows[1]["tg_id"] == 501


def test_reyting_boshqa_biznesni_qoshmaydi(env):
    x, tenants, ctx = env["x"], env["tenants"], env["ctx"]
    other = tenants.create(600, name="Boshqa")
    with ctx.scope(other):
        users = importlib.import_module("bot.users")
        users.upsert(601, name="Begona", role="staff")
        x.add_points(601, 99, "juda ko'p")
    names = [r["name"] for r in x.rating()]
    assert "Begona" not in names


# --- ish haqi ---

def test_oylik_stavka_hisobi(env, monkeypatch):
    x = env["x"]
    _freeze(x, monkeypatch, 9)
    x.set_salary(501, base=5_000_000)
    calc = x.payroll(501, period="2026-08")
    assert calc["earned"] == 5_000_000
    assert calc["balance"] == 5_000_000


def test_kunbay_hisob_ishlagan_kunga_qarab(env, monkeypatch):
    x = env["x"]
    x.set_salary(501, per_day=200_000)
    x.set_shift(501, 0, "09:00", "18:00")
    for day in range(3):
        _freeze(x, monkeypatch, 9, weekday=day)
        x.set_shift(501, day, "09:00", "18:00")
        x.check_in(501)
    calc = x.payroll(501, period="2026-08")
    assert calc["attendance"]["ishlagan_kun"] == 3
    assert calc["earned"] == 600_000


def test_tolov_va_ushlab_qolish_qoldiqni_kamaytiradi(env, monkeypatch):
    x = env["x"]
    _freeze(x, monkeypatch, 9)
    x.set_salary(501, base=5_000_000)
    x.add_payout(501, 2_000_000, kind="avans", period="2026-08")
    x.add_payout(501, 300_000, kind="ushlab_qolish", period="2026-08")
    x.add_payout(501, 500_000, kind="mukofot", period="2026-08")
    calc = x.payroll(501, period="2026-08")
    assert calc["paid"] == 2_000_000
    assert calc["held"] == 300_000
    assert calc["bonus"] == 500_000
    assert calc["balance"] == 5_000_000 + 500_000 - 300_000 - 2_000_000


def test_stavkasiz_xodim_yiqilmaydi(env, monkeypatch):
    x = env["x"]
    _freeze(x, monkeypatch, 9)
    calc = x.payroll(501, period="2026-08")
    assert calc["earned"] == 0
    assert "qo'yilmagan" in calc["basis"]


def test_stavka_almashsa_eskisi_ochadi(env):
    x = env["x"]
    x.set_salary(501, base=1000)
    x.set_salary(501, base=2000)
    assert x.salary_of(501)["base"] == 2000


# --- modul ro'yxatdan o'tishi ---

def test_modul_reyestrda(env):
    registry = importlib.import_module("bot.modules.registry")
    registry.load()
    assert registry.BY_KEY["xodimlar"].ready
    modules = importlib.import_module("bot.modules")
    modules.set_enabled(["xodimlar"])
    assert [s.key for s in modules.available()] == ["xodimlar"]


def test_menyu_rolga_qarab(env):
    registry = importlib.import_module("bot.modules.registry")
    registry.load()
    impl = registry.BY_KEY["xodimlar"].impl
    assert len(impl.menu("owner")) == 2
    assert len(impl.menu("staff")) == 1
