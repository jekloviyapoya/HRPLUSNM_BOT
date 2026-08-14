"""Marketing: matn, chegirma, holat saqlanishi, poster."""

import importlib
import sys

import pytest


class FakeAI:
    def __init__(self, text=None, boom=False):
        self.text = text
        self.boom = boom
        self.calls = []

    def post(self, url, headers=None, json=None, timeout=None, **kw):
        self.calls.append(json)
        if self.boom:
            raise OSError("tarmoq yo'q")
        return type("R", (), {
            "status_code": 200,
            "json": lambda self: {"content": [{"type": "text",
                                               "text": self_text}],
                                  "stop_reason": "end_turn"},
            "text": "",
        })()


class Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError
        return self._payload


class FakeHTTP:
    def __init__(self, response=None, boom=None):
        self.response, self.boom = response, boom
        self.calls = []

    def post(self, url, headers=None, files=None, data=None, timeout=None,
             json=None):
        self.calls.append({"data": data, "json": json})
        if self.boom:
            raise self.boom
        return self.response


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
    monkeypatch.setenv("SAAS_OWNER_ID", "111")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-img")
    for name in list(sys.modules):
        if name == "bot" or name.startswith("bot."):
            del sys.modules[name]
    db = importlib.import_module("bot.db")
    db.migrate()
    ctx = importlib.import_module("bot.ctx")
    ctx.set(importlib.import_module("bot.tenants").create(10))
    tenant = importlib.import_module("bot.tenant")
    tenant.set("shop_name", "Humos Gold")
    return {"m": importlib.import_module("bot.modules.marketing"),
            "img": importlib.import_module("bot.imagen"),
            "tenant": tenant, "db": db, "ctx": ctx}


def ai_response(text):
    return FakeHTTP(Resp(200, {"content": [{"type": "text", "text": text}],
                               "stop_reason": "end_turn"}))


# --- chegirma ---

def test_chegirma_foizi(env):
    m = env["m"]
    assert m.discount_percent(12000, 9000) == 25
    assert m.discount_percent(10000, 10000) is None
    assert m.discount_percent(None, 9000) is None
    assert m.discount_percent(9000, 12000) is None      # qimmatlashgan


def test_narx_qatori(env):
    m = env["m"]
    assert "12 000" in m.price_line(12000, 9000)
    assert "9 000" in m.price_line(None, 9000)
    assert "aytilmagan" in m.price_line(None, None)


# --- matn ---

def test_ai_matni_ishlatiladi(env):
    m = env["m"]
    text = m.compose("Coca-Cola 1L", 12000, 9000,
                     session=ai_response("🔥 Ajoyib aksiya!\nFaqat bugun."))
    assert "Ajoyib aksiya" in text


def test_ai_yiqilsa_zaxira_matn(env):
    """AI ishlamasa ham post chiqsin."""
    m = env["m"]
    text = m.compose("Coca-Cola 1L", 12000, 9000,
                     session=FakeHTTP(boom=OSError("yo'q")))
    assert "Coca-Cola 1L" in text
    assert "9 000" in text
    assert "Humos Gold" in text


def test_juda_qisqa_javob_qabul_qilinmaydi(env):
    m = env["m"]
    text = m.compose("Non", None, 5000, session=ai_response("ok"))
    assert "Non" in text and len(text) > 10


def test_zaxira_matn_narxsiz(env):
    m = env["m"]
    text = m.fallback_text("Non")
    assert "Non" in text
    assert "so'm" not in text


# --- holat qisman yangilanadi ---

def test_narx_matn_yozilganda_yoqolmaydi(env):
    """2026-08-08 xatosi: to'liq qayta yozish narxni o'chirardi."""
    m = env["m"]
    promo_id = m.create(10)
    m.update(promo_id, old_price=12000, new_price=9000)
    m.update(promo_id, post_text="Aksiya!")
    row = m.get(promo_id)
    assert row["old_price"] == 12000
    assert row["new_price"] == 9000
    assert row["post_text"] == "Aksiya!"


def test_rasm_qoshilganda_matn_yoqolmaydi(env):
    m = env["m"]
    promo_id = m.create(10)
    m.update(promo_id, post_text="Matn", new_price=5000)
    m.update(promo_id, photo_id="file123")
    row = m.get(promo_id)
    assert row["post_text"] == "Matn"
    assert row["new_price"] == 5000
    assert row["photo_id"] == "file123"


def test_bosh_yangilash_ozgartirmaydi(env):
    m = env["m"]
    promo_id = m.create(10)
    m.update(promo_id, post_text="Matn")
    assert m.update(promo_id)["post_text"] == "Matn"


# --- qoralama ---

def test_tugallanmagan_post_topiladi(env):
    m = env["m"]
    promo_id = m.create(10)
    assert m.last_draft(10)["id"] == promo_id
    m.update(promo_id, status="yuborildi")
    assert m.last_draft(10) is None


def test_yuborilganlar_sanaladi(env):
    m = env["m"]
    assert m.sent_count() == 0
    m.update(m.create(10), status="yuborildi")
    assert m.sent_count() == 1


def test_post_biznesga_xos(env):
    m, ctx = env["m"], env["ctx"]
    tenants = importlib.import_module("bot.tenants")
    m.update(m.create(10), status="yuborildi")
    with ctx.scope(tenants.create(50)):
        assert m.sent_count() == 0
        assert m.last_draft(10) is None


# --- poster ---

def test_poster_yasaladi(env):
    img = env["img"]
    import base64
    payload = {"data": [{"b64_json": base64.b64encode(b"rasm").decode()}]}
    got = img.make_poster(b"kirish", session=FakeHTTP(Resp(200, payload)))
    assert got == b"rasm"


def test_poster_matn_soramaydi(env):
    """AI rasmda matnni buzadi — promptda matn qo'shmaslik aytiladi."""
    img = env["img"]
    assert "Do not add any text" in img.SCENE


def test_poster_xatosi_tushunarli(env):
    img = env["img"]
    http = FakeHTTP(Resp(400, {"error": {"message": "bad image"}}))
    with pytest.raises(img.ImageError) as exc:
        img.make_poster(b"x", session=http)
    assert "bad image" in str(exc.value)


def test_poster_tarmoq_xatosi(env):
    img = env["img"]
    with pytest.raises(img.ImageError):
        img.make_poster(b"x", session=FakeHTTP(boom=OSError("yo'q")))


def test_poster_kalitsiz_ochiq_aytadi(env, monkeypatch):
    for name in list(sys.modules):
        if name == "bot" or name.startswith("bot."):
            del sys.modules[name]
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    img = importlib.import_module("bot.imagen")
    assert not img.enabled()
    with pytest.raises(img.ImageError):
        img.make_poster(b"x")


def test_modul_reyestrda_bitosiz(env):
    registry = importlib.import_module("bot.modules.registry")
    registry.load()
    modules = importlib.import_module("bot.modules")
    assert registry.BY_KEY["marketing"].ready
    # Erkin matnli post Bito'siz ham yoziladi
    assert not modules.needs_bito("marketing")
