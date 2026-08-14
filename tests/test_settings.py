"""Sozlamalar: kiritishlarni tekshirish va saqlash."""

import importlib
import sys

import pytest


class FakeBot:
    def __init__(self):
        self.sent = []

    def send_message(self, chat_id, text, **kw):
        self.sent.append(text)
        return type("M", (), {"message_id": len(self.sent)})()

    def delete_message(self, *a, **k):
        pass


class Msg:
    def __init__(self, tg_id, text=None, location=None, chat_id=1):
        self.from_user = type("U", (), {"id": tg_id, "first_name": "T",
                                        "username": None})()
        self.chat = type("C", (), {"id": chat_id})()
        self.text = text
        self.location = location


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
    return {"s": importlib.import_module("bot.settings_ui"),
            "t": importlib.import_module("bot.tenant"),
            "x": importlib.import_module("bot.modules.xodimlar"),
            "users": users, "db": db, "ctx": ctx, "tid": tid,
            "errors": importlib.import_module("bot.errors")}


def _apply(env, tg_id, state, text=None, location=None):
    bot = FakeBot()
    env["s"]._apply(bot, Msg(tg_id, text=text, location=location), state, {})
    return bot


# --- do'kon ---

def test_dokon_nomi_saqlanadi(env):
    _apply(env, 10, "set:dokon:shop_name", "Humos Gold")
    assert env["t"].get("shop_name") == "Humos Gold"


def test_qisqa_nom_qabul_qilinmaydi(env):
    bot = _apply(env, 10, "set:dokon:shop_name", "X")
    assert env["t"].get("shop_name") is None
    assert "qisqa" in bot.sent[0].lower()


def test_raqamli_maydonga_matn_yozilmaydi(env):
    with pytest.raises(env["errors"].BotError):
        _apply(env, 10, "set:dokon:work_radius_m", "juda uzoq")


def test_radius_saqlanadi(env):
    _apply(env, 10, "set:dokon:work_radius_m", "300")
    assert env["t"].get("work_radius_m") == "300"


def test_ish_joyi_belgilanadi_va_radius_standart(env):
    loc = type("L", (), {"latitude": 41.31, "longitude": 69.28})()
    _apply(env, 10, "set:dokon:joy", location=loc)
    place = env["t"].get_json("work_place")
    assert round(place["lat"], 2) == 41.31
    assert env["t"].get("work_radius_m") == "200"


def test_joylashuvsiz_xabar_saqlamaydi(env):
    bot = _apply(env, 10, "set:dokon:joy", text="mana shu yer")
    assert env["t"].get_json("work_place") is None
    assert "yuborilmadi" in bot.sent[0]


# --- xodimlar ---

def test_haftalik_jadval_qoyiladi(env):
    _apply(env, 10, "set:xod:20:jadval", "09:00 18:00")
    shifts = env["x"].shifts_of(20)
    assert len(shifts) == 6            # dushanba–shanba
    assert shifts[0]["starts_at"] == "09:00"


def test_jadval_defis_bilan_ham(env):
    _apply(env, 10, "set:xod:20:jadval", "9:00-18:00")
    assert len(env["x"].shifts_of(20)) == 6


def test_notogri_jadval_formati(env):
    bot = _apply(env, 10, "set:xod:20:jadval", "ertalabdan kechgacha")
    assert env["x"].shifts_of(20) == []
    assert "Format" in bot.sent[0]


def test_teskari_vaqt_rad_etiladi(env):
    with pytest.raises(env["errors"].BotError):
        _apply(env, 10, "set:xod:20:jadval", "18:00 09:00")


def test_oylik_va_kunlik_stavka(env):
    _apply(env, 10, "set:xod:20:oylik", "5 000 000")
    assert env["x"].salary_of(20)["base"] == 5_000_000
    _apply(env, 10, "set:xod:20:kunlik", "200000")
    salary = env["x"].salary_of(20)
    assert salary["per_day"] == 200_000
    assert salary["base"] == 0          # eskisi almashdi


def test_stavkaga_matn_yozilmaydi(env):
    with pytest.raises(env["errors"].BotError):
        _apply(env, 10, "set:xod:20:kunlik", "ko'p")


# --- ombor ---

def test_chegara_saqlanadi(env):
    _apply(env, 10, "set:ombor:chegara", "10")
    assert env["t"].get("low_stock_default") == "10"


def test_manfiy_chegara_rad_etiladi(env):
    bot = _apply(env, 10, "set:ombor:chegara", "0")
    assert env["t"].get("low_stock_default") is None
    assert "katta" in bot.sent[0]


def test_chegara_omborga_tasir_qiladi(env):
    """Sozlama darrov kuchga kirsin."""
    ombor = importlib.import_module("bot.modules.ombor")
    env["t"].set("bito_org_id", "o1")
    env["t"].set("warehouse_id", "w1")
    item = {"_id": "p1", "name": "Non",
            "organizations": [{"organization_id": "o1", "amount": 5,
                               "red_line": 0, "yellow_line": 0}],
            "_warehouses": {"w1": {"amount": 5}}}
    assert ombor.status_of(item) is None
    _apply(env, 10, "set:ombor:chegara", "10")
    assert ombor.status_of(item) == "kam"


# --- rollar ---

def test_bosh_rol_ozgartirish_egasiga_xos(env):
    """Menejer rol o'zgartira olmaydi."""
    users = env["users"]
    users.upsert(30, name="Menejer", role="manager")
    with pytest.raises(env["errors"].AccessError):
        users.require_role(30, "owner")


def test_ishdan_boshatilgan_royxatda_yoq(env):
    db, users, ctx = env["db"], env["users"], env["ctx"]
    assert len(users.listing()) == 2
    db.run("UPDATE users SET active = 0 WHERE tenant_id = ? AND tg_id = 20",
           (ctx.require(),))
    assert len(users.listing()) == 1


def test_bolimlar_royxati_toliq(env):
    keys = {key for key, _, _ in env["s"].SECTIONS}
    assert keys == {"dokon", "bito", "xodimlar", "ombor"}
