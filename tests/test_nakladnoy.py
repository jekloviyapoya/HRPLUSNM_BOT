"""Nakladnoy: normallash, blok invarianti, ekstraksiya.

Bu testlar market-bot'da amalda yuz bergan xatolarni qaytarilmasligini
tekshiradi. Batafsil: LESSONS-MARKET-BOT.md
"""

import importlib
import json
import sys

import pytest


class FakeAI:
    def __init__(self, payload, stop=None, fail_times=0):
        self.payload = payload
        self.stop = stop
        self.fail_times = fail_times
        self.calls = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"headers": dict(headers or {}), "body": json})
        if len(self.calls) <= self.fail_times:
            return FakeResp(529, {"error": {"message": "overloaded"}})
        text = self.payload if isinstance(self.payload, str) else _dump(self.payload)
        stop = self.stop if len(self.calls) == 1 else "end_turn"
        return FakeResp(200, {"content": [{"type": "text", "text": text}],
                              "stop_reason": stop})


def _dump(obj):
    return json.dumps(obj, ensure_ascii=False)


class FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
    monkeypatch.setenv("SAAS_OWNER_ID", "111")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    for name in list(sys.modules):
        if name == "bot" or name.startswith("bot."):
            del sys.modules[name]
    db = importlib.import_module("bot.db")
    db.migrate()
    ctx = importlib.import_module("bot.ctx")
    tid = importlib.import_module("bot.tenants").create(900, name="Egasi")
    ctx.set(tid)
    return {"n": importlib.import_module("bot.modules.nakladnoy"),
            "ai": importlib.import_module("bot.ai"),
            "db": db, "ctx": ctx, "tid": tid}


# --- INVARIANT: qty = blok, price = dona ---

def test_blok_aniqlanadi_hujjat_jamisidan(env):
    """5 blok × 6 dona × 4500 = 135 000"""
    n = env["n"]
    assert n.detect_block(qty=5, price=4500, doc_total=135000) == 6


def test_blok_yoq_bolsa_bir(env):
    n = env["n"]
    assert n.detect_block(qty=10, price=5000, doc_total=50000) == 1


def test_qty_hech_qachon_donaga_aylantirilmaydi(env):
    """market-bot 2026-08-02: qty donaga aylanib, keyin YANA ×6 bo'lgan."""
    n = env["n"]
    doc = n.normalize({"items": [
        {"name": "Coca-Cola", "qty": 5, "price": 4500, "total": 135000},
    ]})
    item = doc["items"][0]
    assert item["qty"] == 5           # blok soni, 30 EMAS
    assert item["block_size"] == 6
    assert item["price"] == 4500      # dona narxi
    assert n.line_total(item) == 135000


def test_jami_bir_joyda_hisoblanadi(env):
    n = env["n"]
    item = {"qty": 3, "block_size": 12, "price": 1000}
    assert n.line_total(item) == 36000


def test_nomaqbul_nisbat_blok_deb_qabul_qilinmaydi(env):
    n = env["n"]
    assert n.detect_block(qty=7, price=1000, doc_total=10500) == 1   # 1.5
    assert n.detect_block(qty=1, price=100, doc_total=100000) == 1   # 1000, juda katta
    assert n.detect_block(qty=2, price=500, doc_total=999) == 1      # kamayish


def test_jami_yoq_bolsa_blok_bir(env):
    n = env["n"]
    doc = n.normalize({"items": [{"name": "Non", "qty": 4, "price": 3000}]})
    assert doc["items"][0]["block_size"] == 1
    assert n.line_total(doc["items"][0]) == 12000


# --- shtrix-kod ---

def test_shtrix_kod_tozalanadi(env):
    n = env["n"]
    assert n.clean_barcode("4780016 350018") == "4780016350018"
    assert n.clean_barcode("ART-123") == ""          # 3 raqam, qisqa
    assert n.clean_barcode("12345678901234567") == ""  # uzun
    assert n.clean_barcode(None) == ""


# --- normallash ---

def test_nomsiz_va_nol_miqdorli_qatorlar_tashlanadi(env):
    n = env["n"]
    doc = n.normalize({"items": [
        {"name": "Non", "qty": 2, "price": 100},
        {"name": "", "qty": 5, "price": 100},
        {"name": "Sut", "qty": 0, "price": 100},
    ]})
    assert [i["raw_name"] for i in doc["items"]] == ["Non"]


def test_vergulli_va_boshliqli_sonlar(env):
    n = env["n"]
    doc = n.normalize({"items": [
        {"name": "Yog'", "qty": "2,5", "price": "12 000"},
    ]})
    assert doc["items"][0]["qty"] == 2.5
    assert doc["items"][0]["price"] == 12000


def test_birlik_saqlanadi(env):
    n = env["n"]
    doc = n.normalize({"items": [
        {"name": "Suv", "qty": 3, "qty_unit": "бл", "price": 5000},
    ]})
    assert doc["items"][0]["qty_unit"] == "бл"


# --- jami tekshiruvi ---

def test_jami_mos_kelsa(env):
    n = env["n"]
    doc = n.normalize({"total": 135000, "items": [
        {"name": "Cola", "qty": 5, "price": 4500, "total": 135000}]})
    computed, stated, diff = n.check_totals(doc)
    assert computed == 135000
    assert stated == 135000
    assert diff == 0


def test_jami_mos_kelmasa_farq_qaytadi(env):
    n = env["n"]
    doc = n.normalize({"total": 200000, "items": [
        {"name": "Cola", "qty": 5, "price": 4500}]})
    computed, stated, diff = n.check_totals(doc)
    assert computed == 22500
    assert diff > 50


# --- AI javobini o'qish ---

def test_markdown_ramkasi_ichidagi_json(env):
    ai = env["ai"]
    got = ai.parse_json('```json\n{"items": []}\n```')
    assert got == {"items": []}


def test_atrofida_matn_bolsa_ham_oqiladi(env):
    ai = env["ai"]
    got = ai.parse_json('Mana natija:\n{"a": 1}\nTayyor.')
    assert got == {"a": 1}


def test_buzuq_javob_tushunarli_xato(env):
    ai = env["ai"]
    with pytest.raises(ai.AIError) as exc:
        ai.parse_json("umuman json emas")
    assert "aniqroq" in str(exc.value).lower()


def test_kesilgan_javob_kattaroq_limit_bilan_qayta(env):
    """Kesilganda YUQORIGA qarab urinamiz — pastga urinish battar kesadi."""
    ai = env["ai"]
    fake = FakeAI({"items": [{"name": "Non", "qty": 1, "price": 100}]},
                  stop="max_tokens")
    got, stop = ai.ask_json([{"type": "text", "text": "x"}], session=fake)
    assert len(fake.calls) == 2
    assert fake.calls[0]["body"]["max_tokens"] == ai.SAFE_TOKENS
    assert fake.calls[1]["body"]["max_tokens"] == ai.BIG_TOKENS
    assert fake.calls[1]["headers"]["anthropic-beta"] == ai.BIG_HEADER
    assert got["items"][0]["name"] == "Non"


def test_server_bandligida_qayta_urinadi(env):
    ai = env["ai"]
    fake = FakeAI({"items": []}, fail_times=2)
    text, _ = ai.ask([{"type": "text", "text": "x"}], session=fake)
    assert len(fake.calls) == 3


# --- to'liq oqim ---

def test_ekstraksiya_va_saqlash(env):
    n, ctx = env["n"], env["ctx"]
    payload = {
        "supplier": "Adler", "number": "A-15", "date": "2026-08-14",
        "total": 155000,
        "items": [
            {"name": "Coca-Cola 1L", "qty": 5, "qty_unit": "бл",
             "price": 4500, "total": 135000, "barcode": "5449000000996"},
            {"name": "Non", "qty": 4, "price": 5000, "total": 20000},
        ],
    }
    fake = FakeAI(payload)
    parsed = n.extract(text="jadval matni", session=fake)
    assert parsed["supplier"] == "Adler"
    assert len(parsed["items"]) == 2
    assert parsed["items"][0]["block_size"] == 6

    doc_id = n.create_doc(900, "text")
    n.save_doc(doc_id, parsed)
    doc = n.get_doc(doc_id)
    assert doc["status"] == "tekshirilmoqda"
    assert doc["supplier_name"] == "Adler"
    items = n.get_items(doc_id)
    assert items[0]["qty"] == 5
    assert items[0]["block_size"] == 6
    assert items[0]["barcode"] == "5449000000996"
    computed = sum(i["qty"] * i["block_size"] * i["price"] for i in items)
    assert computed == 155000


def test_bosh_natija_xato_beradi(env):
    n = env["n"]
    errors = importlib.import_module("bot.errors")
    with pytest.raises(errors.BotError):
        n.extract(text="x", session=FakeAI({"items": []}))


def test_xato_qayd_etiladi(env):
    n = env["n"]
    doc_id = n.create_doc(900, "photo")
    n.fail_doc(doc_id, "AI javob bermadi")
    assert n.get_doc(doc_id)["status"] == "xato"


# --- firma xotirasi ---

def test_firma_eslatmasi_promptga_qoshiladi(env):
    n = env["n"]
    nak_prompt = importlib.import_module("bot.modules.nak_prompt")
    n.remember_hint("Adler", "Narx 4-ustunda, chegirmasiz")
    rows = n.hints()
    assert rows[0]["supplier"] == "adler"
    text = nak_prompt.build(rows)
    assert "Narx 4-ustunda" in text
    assert "FIRMA TUZILISH" in text


def test_eslatma_takrorlanmaydi_hisob_oshadi(env):
    n = env["n"]
    n.remember_hint("Adler", "birinchi")
    n.remember_hint("Adler", "ikkinchi")
    rows = n.hints()
    assert len(rows) == 1
    assert rows[0]["hint"] == "ikkinchi"


def test_eslatmasiz_prompt_bosh_blok(env):
    nak_prompt = importlib.import_module("bot.modules.nak_prompt")
    assert nak_prompt.hints_block([]) == ""


# --- promptdagi qoidalar saqlanib turibdimi ---

def test_prompt_qoidalari_joyida(env):
    """Bu qoidalar amalda sinovdan o'tgan — yo'qolib ketmasin."""
    nak_prompt = importlib.import_module("bot.modules.nak_prompt")
    text = nak_prompt.build([])
    for phrase in ("ИТОГО", "AYNAN", "Покупатель", "8–14",
                   "BARCHASINI", "hisob-kitob"):
        assert phrase in text, phrase


# --- modul ---

def test_modul_reyestrda(env):
    registry = importlib.import_module("bot.modules.registry")
    registry.load()
    assert registry.BY_KEY["nakladnoy"].ready
    modules = importlib.import_module("bot.modules")
    assert modules.needs_bito("nakladnoy")


def test_xodimga_menyuda_korinmaydi(env):
    registry = importlib.import_module("bot.modules.registry")
    registry.load()
    impl = registry.BY_KEY["nakladnoy"].impl
    assert impl.menu("staff") == []
    assert len(impl.menu("owner")) == 1


# --- moslashtirish oqimi ---

def test_moslashtirish_saqlanadi(env):
    n = env["n"]
    catalog = importlib.import_module("bot.catalog")
    for pid, name in [("p1", "Coca-Cola 1L"), ("p2", "Non")]:
        catalog.upsert({"_id": pid, "name": name, "barcodes": [],
                        "measure": {"short_name": "Dona"}, "sku": None,
                        "category": {"name": "x"}})
    parsed = n.normalize({"items": [
        {"name": "Coca-Cola 1L", "qty": 2, "price": 5000},
        {"name": "Kartoshka", "qty": 3, "price": 4000},
    ]})
    doc_id = n.create_doc(900, "photo")
    n.save_doc(doc_id, parsed)
    state = n.match_doc(doc_id)
    assert len(state["matched"]) == 1
    assert len(state["pending"]) == 1
    assert state["matched"][0]["product_id"] == "p1"


def test_qolda_tanlash_xotiraga_yoziladi(env):
    n = env["n"]
    catalog = importlib.import_module("bot.catalog")
    catalog.upsert({"_id": "p9", "name": "Maxsus tovar", "barcodes": [],
                    "measure": {"short_name": "Dona"}, "sku": None,
                    "category": {"name": "x"}})
    parsed = n.normalize({"items": [{"name": "MXS-99", "qty": 1, "price": 100}]})
    doc_id = n.create_doc(900, "photo")
    n.save_doc(doc_id, parsed)
    n.match_doc(doc_id)
    item = n.get_items(doc_id)[0]
    n.set_match(item["id"], "p9", "Maxsus tovar")

    assert n.summary(doc_id)["matched"][0]["product_id"] == "p9"
    # Keyingi hujjatda avtomatik
    assert catalog.match("MXS-99")["product_id"] == "p9"


def test_tashlab_ketilgan_yuklanmaydi(env):
    n = env["n"]
    parsed = n.normalize({"items": [{"name": "X", "qty": 1, "price": 100}]})
    doc_id = n.create_doc(900, "photo")
    n.save_doc(doc_id, parsed)
    n.match_doc(doc_id)
    item = n.get_items(doc_id)[0]
    n.skip_item(item["id"])
    state = n.summary(doc_id)
    assert state["matched"] == []
    assert len(state["skipped"]) == 1
