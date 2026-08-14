"""Telefon + parol bilan kirish."""

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
    return {"a": importlib.import_module("bot.auth"),
            "db": db, "ctx": importlib.import_module("bot.ctx"),
            "users": importlib.import_module("bot.users"),
            "tenant": importlib.import_module("bot.tenant")}


# --- telefon ---

def test_telefon_normallashadi(env):
    a = env["a"]
    assert a.normalize_phone("+998 90 123 45 67") == "+998901234567"
    assert a.normalize_phone("901234567") == "+998901234567"
    assert a.normalize_phone("998901234567") == "+998901234567"
    assert a.normalize_phone("abc") is None
    assert a.normalize_phone("") is None


# --- parol xeshi ---

def test_parol_ochiq_saqlanmaydi(env):
    a = env["a"]
    stored = a.hash_password("maxfiy123")
    assert "maxfiy123" not in stored
    assert stored.startswith("pbkdf2$")


def test_bir_xil_parol_har_safar_boshqa_xesh(env):
    a = env["a"]
    assert a.hash_password("maxfiy123") != a.hash_password("maxfiy123")


def test_parol_tekshiriladi(env):
    a = env["a"]
    stored = a.hash_password("maxfiy123")
    assert a.verify_password("maxfiy123", stored)
    assert not a.verify_password("maxfiy124", stored)
    assert not a.verify_password("", stored)
    assert not a.verify_password("maxfiy123", "buzuq")
    assert not a.verify_password("maxfiy123", None)


def test_qisqa_parol_rad_etiladi(env):
    a = env["a"]
    with pytest.raises(a.AuthError):
        a.hash_password("123")


def test_yaratilgan_parol_chalkash_belgisiz(env):
    a = env["a"]
    for _ in range(20):
        password = a.new_password()
        assert len(password) == 8
        assert not set(password) & set("0O1lI")


# --- hisob ochish ---

def test_hisob_ochiladi(env):
    a = env["a"]
    tenant_id, password = a.create_account("+998901234567", name="Humos Gold")
    assert tenant_id
    assert len(password) == 8
    row = a.account(tenant_id)
    assert row["phone"] == "+998901234567"
    assert row["must_change"] == 1
    with env["ctx"].scope(tenant_id):
        assert env["tenant"].shop_name() == "Humos Gold"


def test_sinov_muddati_ochiladi(env):
    a = env["a"]
    tenant_id, _ = a.create_account("+998901234567")
    license = importlib.import_module("bot.license")
    with env["ctx"].scope(tenant_id):
        assert license.state() == "trial"


def test_takroriy_telefon_rad_etiladi(env):
    a = env["a"]
    a.create_account("+998901234567")
    with pytest.raises(a.AuthError):
        a.create_account("998901234567")      # bir xil raqam


def test_notogri_telefon_rad_etiladi(env):
    a = env["a"]
    with pytest.raises(a.AuthError):
        a.create_account("salom")


# --- kirish ---

def test_togri_parol_bilan_kirish(env):
    a = env["a"]
    tenant_id, password = a.create_account("+998901234567")
    got, must_change = a.login(500, "+998901234567", password)
    assert got == tenant_id
    assert must_change is True


def test_notogri_parol(env):
    a = env["a"]
    a.create_account("+998901234567")
    with pytest.raises(a.AuthError):
        a.login(500, "+998901234567", "yomon")


def test_yoq_telefon(env):
    a = env["a"]
    with pytest.raises(a.AuthError):
        a.login(500, "+998900000000", "x")


def test_besh_urinishdan_keyin_bloklanadi(env):
    a = env["a"]
    a.create_account("+998901234567")
    for _ in range(a.MAX_FAILS - 1):
        with pytest.raises(a.AuthError):
            a.login(500, "+998901234567", "yomon")
    assert a.blocked_minutes(500) == 0
    with pytest.raises(a.AuthError):
        a.login(500, "+998901234567", "yomon")
    assert a.blocked_minutes(500) > 0


def test_blok_paytida_togri_parol_ham_otmaydi(env):
    a = env["a"]
    _, password = a.create_account("+998901234567")
    for _ in range(a.MAX_FAILS):
        with pytest.raises(a.AuthError):
            a.login(500, "+998901234567", "yomon")
    with pytest.raises(a.AuthError) as exc:
        a.login(500, "+998901234567", password)
    assert "daqiqa" in str(exc.value)


def test_togri_kirish_urinishlarni_tozalaydi(env):
    a = env["a"]
    _, password = a.create_account("+998901234567")
    with pytest.raises(a.AuthError):
        a.login(500, "+998901234567", "yomon")
    a.login(500, "+998901234567", password)
    assert a.blocked_minutes(500) == 0


# --- biriktirish ---

def test_egasi_biriktiriladi(env):
    a, users, ctx = env["a"], env["users"], env["ctx"]
    tenant_id, password = a.create_account("+998901234567")
    a.login(500, "+998901234567", password)
    a.bind_owner(tenant_id, 500, name="Ali")
    with ctx.scope(tenant_id):
        assert users.role_of(500) == "owner"


def test_boshqa_biznesdagi_odam_biriktirilmaydi(env):
    a, users, ctx = env["a"], env["users"], env["ctx"]
    first, _ = a.create_account("+998901111111")
    second, _ = a.create_account("+998902222222")
    a.bind_owner(first, 500)
    with pytest.raises(a.AuthError):
        a.bind_owner(second, 500)
    with ctx.scope(first):
        assert users.role_of(500) == "owner"


# --- parol almashtirish ---

def test_parol_ozgartiriladi(env):
    a = env["a"]
    tenant_id, old = a.create_account("+998901234567")
    a.set_password(tenant_id, "yangiparol")
    assert a.account(tenant_id)["must_change"] == 0
    with pytest.raises(a.AuthError):
        a.login(500, "+998901234567", old)
    got, must_change = a.login(501, "+998901234567", "yangiparol")
    assert got == tenant_id
    assert must_change is False


def test_sotuvchi_tiklagan_parol_almashtirishni_talab_qiladi(env):
    a = env["a"]
    tenant_id, _ = a.create_account("+998901234567")
    a.set_password(tenant_id, "mijozparoli")
    new = a.reset_password(tenant_id)
    _, must_change = a.login(500, "+998901234567", new)
    assert must_change is True


def test_ochirilgan_hisobga_kirilmaydi(env):
    a, db = env["a"], env["db"]
    tenant_id, password = a.create_account("+998901234567")
    db.run("UPDATE tenant SET active = 0 WHERE id = ?", (tenant_id,))
    with pytest.raises(a.AuthError):
        a.login(500, "+998901234567", password)
