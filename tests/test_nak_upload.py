"""Bito'ga kirim: invariant yakuni, uzilish, partiyalash.

Har test market-bot'da amalda yuz bergan xatoni qaytarilmasligini
tekshiradi. Batafsil: LESSONS-MARKET-BOT.md
"""

import importlib
import sys

import pytest


class Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text or str(payload)

    def json(self):
        if self._payload is None:
            raise ValueError
        return self._payload


class Client:
    """Bito o'rniga."""

    def __init__(self, responses, purchases=None):
        self.responses = list(responses)
        self.purchases = purchases or []
        self.sent = []

    def create_purchase(self, body, timeout=None):
        self.sent.append({"body": body, "timeout": timeout})
        return self.responses.pop(0) if self.responses else Resp(200, {
            "data": {"number": f"P{len(self.sent)}"}})

    def paged(self, logical, page=1, limit=200, **kw):
        return self.purchases, len(self.purchases)


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
    tid = importlib.import_module("bot.tenants").create(10)
    ctx.set(tid)
    tenant = importlib.import_module("bot.tenant")
    for key, value in [("bito_org_id", "o1"), ("warehouse_id", "w1"),
                       ("currency_id", "c1"), ("bito_api_key", "k"),
                       ("price_id", "p1")]:
        tenant.set(key, value)
    up = importlib.import_module("bot.nak_upload")
    monkeypatch.setattr(up, "BATCH_PAUSE", 0)
    monkeypatch.setattr(up, "VERIFY_DELAY", 0)
    return {"up": up, "tenant": tenant, "db": db, "ctx": ctx}


def item(pid="p1", qty=5, block=6, price=4500, name="Cola"):
    return {"product_id": pid, "qty": qty, "block_size": block,
            "price": price, "raw_name": name, "product_name": name}


# --- INVARIANT yakuni ---

def test_blok_donaga_faqat_shu_yerda_aylanadi(env):
    """5 blok × 6 dona = 30 dona, narx o'zgarmaydi."""
    up = env["up"]
    products = up.build_products([item(qty=5, block=6, price=4500)])
    assert products[0]["amount"] == 30
    assert products[0]["cost"] == 4500
    assert up.total_of(products) == 135000


def test_bloksiz_qator(env):
    up = env["up"]
    products = up.build_products([item(qty=4, block=1, price=5000)])
    assert products[0]["amount"] == 4
    assert up.total_of(products) == 20000


def test_moslashtirilmagan_qator_yuborilmaydi(env):
    up = env["up"]
    products = up.build_products([
        item(), {"qty": 3, "price": 100, "block_size": 1},   # product_id yo'q
    ])
    assert len(products) == 1


def test_nol_miqdor_yuborilmaydi(env):
    up = env["up"]
    assert up.build_products([item(qty=0)]) == []


def test_bosh_royxat_xato_beradi(env):
    up = env["up"]
    errors = importlib.import_module("bot.errors")
    with pytest.raises(errors.BitoError):
        up.upload([], "sup1", client=Client([]))


# --- uzilish ---

def test_504_da_qayta_yuborilmaydi(env):
    """Eng muhim: 504 «yaratilmadi» degani emas — ikki marta kirim xavfi."""
    up = env["up"]
    client = Client([Resp(504, text="gateway timeout")])
    result = up.upload([item()], "sup1", client=client)
    assert len(client.sent) == 1          # QAYTA YUBORILMADI
    assert result["ok"] is False
    assert "yaratilmagan" in result["failed"][0]["error"]


def test_504_dan_keyin_yaratilgani_topiladi(env):
    up = env["up"]
    holder = {}

    class C(Client):
        def create_purchase(self, body, timeout=None):
            holder["tag"] = body["note"]
            self.sent.append(body)
            return Resp(504)

        def paged(self, logical, page=1, limit=200, **kw):
            return [{"number": "P-77", "note": holder["tag"]}], 1

    result = up.upload([item()], "sup1", client=C([]))
    assert result["ok"] is True
    assert result["numbers"] == ["P-77"]


def test_betakror_belgi_izohda(env):
    up = env["up"]
    client = Client([])
    result = up.upload([item()], "sup1", client=client)
    assert result["tag"] in client.sent[0]["body"]["note"]
    assert result["tag"].startswith("bot-")


def test_har_yuklashda_yangi_belgi(env):
    up = env["up"]
    assert up.new_tag() != up.new_tag()


# --- partiyalash ---

def test_katta_hujjat_partiyalarga_bolinadi(env):
    up = env["up"]
    items = [item(pid=f"p{i}") for i in range(130)]
    result = up.upload(items, "sup1", client=Client([]))
    assert len(result["numbers"]) == 3      # 60 + 60 + 10
    assert result["uploaded_count"] == 130


def test_bir_partiya_yiqilsa_qolgani_yuklanadi(env):
    up = env["up"]
    items = [item(pid=f"p{i}") for i in range(130)]
    client = Client([Resp(200, {"data": {"number": "A"}}),
                     Resp(400, {"message": "xato"}),
                     Resp(200, {"data": {"number": "C"}})])
    result = up.upload(items, "sup1", client=client)
    assert result["ok"] is True
    assert result["numbers"] == ["A", "C"]
    assert len(result["failed"]) == 1
    assert result["failed"][0]["count"] == 60
    assert result["uploaded_count"] == 70


def test_partiya_raqami_izohda(env):
    up = env["up"]
    items = [item(pid=f"p{i}") for i in range(70)]
    client = Client([])
    up.upload(items, "sup1", client=client)
    assert "(1/2)" in client.sent[0]["body"]["note"]
    assert "(2/2)" in client.sent[1]["body"]["note"]


def test_bitta_partiyada_raqam_yozilmaydi(env):
    up = env["up"]
    client = Client([])
    up.upload([item()], "sup1", client=client)
    assert "(1/1)" not in client.sent[0]["body"]["note"]


def test_katta_partiyaga_uzoqroq_kutish(env):
    up = env["up"]
    assert up._timeout_for(10) == 60
    assert up._timeout_for(60) == 60
    assert up._timeout_for(120) == 90


# --- xatolar ---

def test_ochirilgan_mahsulot_nomi_bilan_aytiladi(env):
    up = env["up"]
    client = Client([Resp(400, {"code": 26000, "data": "a" * 24})])
    items = [dict(item(pid="a" * 24), product_name="Coca-Cola 1L")]
    result = up.upload(items, "sup1", client=client)
    assert "Coca-Cola 1L" in result["failed"][0]["error"]
    assert "o'chirilgan" in result["failed"][0]["error"]


def test_ichma_ich_xato_kodi_topiladi(env):
    up = env["up"]
    payload = {"status": 400, "upstream": {"code": 26000, "data": "b" * 24}}
    assert up._missing_product_id(payload) == "b" * 24


def test_boshqa_xato_matni_korsatiladi(env):
    up = env["up"]
    client = Client([Resp(422, {"message": "narx noto'g'ri"})])
    result = up.upload([item()], "sup1", client=client)
    assert "422" in result["failed"][0]["error"]


# --- tanasi ---

def test_kirim_tanasi_toliq(env):
    up = env["up"]
    client = Client([])
    up.upload([item()], "sup-9", client=client)
    body = client.sent[0]["body"]
    assert body["organization_id"] == "o1"
    assert body["warehouse_id"] == "w1"
    assert body["currency_id"] == "c1"
    assert body["supplier_id"] == "sup-9"
    assert body["is_auto_income"] is True
    assert body["orders"][0]["products"][0]["amount"] == 30


def test_holat_bazaga_yoziladi(env):
    up = env["up"]
    nak = importlib.import_module("bot.modules.nakladnoy")
    doc_id = nak.create_doc(10, "photo")
    result = up.upload([item()], "sup1", client=Client([]))
    up.mark_uploaded(doc_id, result)
    assert nak.get_doc(doc_id)["status"] == "yuklandi"


def test_qisman_yuklanish_xato_deb_belgilanadi(env):
    up = env["up"]
    nak = importlib.import_module("bot.modules.nakladnoy")
    doc_id = nak.create_doc(10, "photo")
    items = [item(pid=f"p{i}") for i in range(70)]
    client = Client([Resp(200, {"data": {"number": "A"}}), Resp(400, {})])
    result = up.upload(items, "sup1", client=client)
    up.mark_uploaded(doc_id, result)
    assert nak.get_doc(doc_id)["status"] == "xato"
