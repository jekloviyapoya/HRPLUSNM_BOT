"""Moliya: kassa, qarzlar, zakaz limiti.

Har test market-bot'da amalda yuz bergan xatoni qaytarilmasligini
tekshiradi. Batafsil: LESSONS-MARKET-BOT.md
"""

import importlib
import sys

import pytest


class Client:
    def __init__(self, balance=None, debt=None, credit=None, suppliers=None,
                 income=None, purchases=None, boom=()):
        self._balance = balance
        self._debt = debt
        self._credit = credit
        self._suppliers = suppliers or []
        self._income = income
        self._purchases = purchases or []
        self.boom = set(boom)

    def _check(self, name):
        if name in self.boom:
            from bot.errors import BitoError
            raise BitoError("Bito nosozligi")

    def balance(self):
        self._check("balance")
        return self._balance

    def debt_summary(self):
        self._check("debt")
        return self._debt

    def credit_summary(self):
        self._check("credit")
        return self._credit

    def get(self, logical):
        self._check(logical)
        if logical == "income_expense":
            return self._income
        return {}

    def suppliers(self, page=1, limit=200, search=None):
        rows = self._suppliers if page == 1 else []
        return rows, len(rows)

    def purchases(self, page=1, limit=200, **kw):
        rows = self._purchases if page == 1 else []
        return rows, len(rows)


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
    ctx.set(importlib.import_module("bot.tenants").create(10))
    return {"m": importlib.import_module("bot.modules.moliya")}


# --- kassa ---

def test_kassa_royxatdan_yigiladi(env):
    m = env["m"]
    client = Client(balance={"cashboxes": [
        {"name": "Naqd", "amount": 31_200_000},
        {"name": "Karta", "amount": 4_800_000},
    ]})
    total, boxes = m.cash_on_hand(client)
    assert total == 36_000_000
    assert boxes[0]["name"] == "Naqd"      # kamayish tartibida


def test_kassa_royxatsiz_javobda_ham(env):
    m = env["m"]
    total, boxes = m.cash_on_hand(Client(balance={"total": 12_000_000}))
    assert total == 12_000_000
    assert boxes == []


def test_kassa_royxat_korinishida(env):
    m = env["m"]
    total, _ = m.cash_on_hand(Client(balance=[{"name": "Naqd", "amount": 500}]))
    assert total == 500


# --- qarzlar ---

def test_qarzlar_ikki_tomonlama(env):
    m = env["m"]
    client = Client(debt={"total": 5_000_000},
                    suppliers=[{"_id": "s1", "name": "Adler",
                                "balance": -8_000_000}])
    got = m.debts(client)
    assert got["customers"] == 5_000_000
    assert got["suppliers"] == 8_000_000


def test_fantom_qarz_hisoblanmaydi(env):
    """Bito ro'yxatida yo'q firma to'langan hisoblanadi.

    Qarz hisobotida o'chirilgan firmalar qolib ketadi va yo'q qarzni
    ko'rsatadi. Ro'yxat haqiqiy manba.
    """
    m = env["m"]
    client = Client(
        debt={"total": 0},
        credit={"total": 20_000_000},          # fantom qarz bor
        suppliers=[{"_id": "s1", "name": "Adler", "balance": -3_000_000},
                   {"_id": "s2", "name": "Nestle", "balance": 500_000}])
    got = m.debts(client)
    assert got["suppliers"] == 3_000_000       # 20 mln emas
    assert got["phantom"] is False


def test_royxat_olinmasa_hisobot_zaxira(env):
    m = env["m"]
    client = Client(debt={"total": 0}, credit={"total": 7_000_000},
                    boom=["suppliers_boom"])

    def boom(page=1, limit=200, search=None):
        from bot.errors import BitoError
        raise BitoError("nosozlik")

    client.suppliers = boom
    got = m.debts(client)
    assert got["suppliers"] == 7_000_000
    assert got["phantom"] is True


def test_bir_hisobot_yiqilsa_qolgani_ishlaydi(env):
    m = env["m"]
    client = Client(debt=None, boom=["debt"],
                    suppliers=[{"_id": "s1", "name": "A", "balance": -100}])
    got = m.debts(client)
    assert got["customers"] == 0.0
    assert got["suppliers"] == 100


def test_ichma_ich_javobdan_son_topiladi(env):
    m = env["m"]
    got = m.debts(Client(debt={"data": {"summary": {"total": 777}}},
                         credit={"total": 0}))
    assert got["customers"] == 777


# --- firmalar ---

def test_firmalar_supplier_endpointidan(env):
    """Qarz hisobotidan emas: u yerdagi id mahsulot bilan mos kelmaydi."""
    m = env["m"]
    client = Client(suppliers=[
        {"_id": "s1", "name": "Adler", "balance": -3_000_000},
        {"_id": "s2", "name": "Nestle", "balance": 500_000},
        {"_id": "s3", "name": "Bosh", "balance": 0},
    ])
    rows = m.suppliers_with_balance(client)
    assert [r["name"] for r in rows] == ["Adler", "Bosh", "Nestle"]
    assert rows[0]["id"] == "s1"


# --- zakaz limiti ---

def test_limit_ufq_kuniga_bolinadi(env):
    """Bo'linmasa haftalik byudjet bir kunga ruxsat berilgan bo'lardi."""
    m = env["m"]
    limit = m.order_limit(cash=20_000_000, daily_income=0, obligations=0,
                          horizon=7, reserve=0)
    assert limit["available"] == 20_000_000
    assert limit["daily_limit"] == pytest.approx(20_000_000 / 7)


def test_kutilayotgan_tushum_ufqga_kopaytiriladi(env):
    m = env["m"]
    limit = m.order_limit(cash=0, daily_income=1_000_000, obligations=0,
                          horizon=7, reserve=0)
    assert limit["expected_in"] == 7_000_000


def test_zaxira_uch_kunlik_majburiyat(env):
    m = env["m"]
    limit = m.order_limit(cash=10_000_000, daily_income=0,
                          obligations=7_000_000, horizon=7)
    assert limit["reserve"] == pytest.approx(7_000_000 / 7 * 3)


def test_sozlangan_zaxira_ustun(env):
    m = env["m"]
    limit = m.order_limit(cash=10_000_000, daily_income=0,
                          obligations=7_000_000, horizon=7,
                          reserve=2_000_000)
    assert limit["reserve"] == 2_000_000


def test_ufq_nol_bolsa_yiqilmaydi(env):
    m = env["m"]
    limit = m.order_limit(cash=1000, daily_income=0, obligations=0, horizon=0)
    assert limit["horizon"] == 1
    assert limit["daily_limit"] == 1000


def test_qarz_kassadan_ortiq_bolsa_manfiy(env):
    m = env["m"]
    limit = m.order_limit(cash=1_000_000, daily_income=0,
                          obligations=5_000_000, horizon=7, reserve=0)
    assert limit["daily_limit"] < 0


# --- tavsiya ---

def test_bosh_pul_yoq_tavsiyasi(env):
    m = env["m"]
    limit = m.order_limit(cash=0, daily_income=0, obligations=1_000_000,
                          horizon=7, reserve=0)
    assert "zakaz bermang" in m.advice(limit, 500_000)


def test_odatdagidan_kam_tavsiyasi(env):
    m = env["m"]
    limit = m.order_limit(cash=7_000_000, daily_income=0, obligations=0,
                          horizon=7, reserve=0)          # kunlik 1 mln
    assert "qisqartiring" in m.advice(limit, 2_000_000)


def test_odatdagidan_kop_tavsiyasi(env):
    m = env["m"]
    limit = m.order_limit(cash=21_000_000, daily_income=0, obligations=0,
                          horizon=7, reserve=0)          # kunlik 3 mln
    assert "oshirish" in m.advice(limit, 1_000_000)


def test_odatdagi_surat_tavsiyasi(env):
    m = env["m"]
    limit = m.order_limit(cash=7_000_000, daily_income=0, obligations=0,
                          horizon=7, reserve=0)
    assert "Odatdagi" in m.advice(limit, 1_000_000)


def test_surat_nomalum_bolsa(env):
    m = env["m"]
    limit = m.order_limit(cash=7_000_000, daily_income=0, obligations=0,
                          horizon=7, reserve=0)
    assert "bo'sh pul bor" in m.advice(limit, 0)


# --- o'rtacha xarid ---

def test_ortacha_kunlik_xarid(env):
    m = env["m"]
    client = Client(purchases=[{"total": 30_000_000}, {"total": 30_000_000}])
    assert m.avg_daily_purchase(client, days=30) == 2_000_000


def test_xaridlar_olinmasa_nol(env):
    m = env["m"]
    assert m.avg_daily_purchase(Client(boom=["purchases"])) == 0.0


def test_modul_reyestrda_bito_talab_qiladi(env):
    registry = importlib.import_module("bot.modules.registry")
    registry.load()
    modules = importlib.import_module("bot.modules")
    assert registry.BY_KEY["moliya"].ready
    assert modules.needs_bito("moliya")
