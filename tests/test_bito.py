"""Bito klienti testlari — soxta transport bilan, tarmoqqa chiqmaydi."""

import importlib
import sys

import pytest


class FakeResponse:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("json emas")
        return self._payload


class FakeSession:
    """routes: (path_suffix, header_name) -> FakeResponse yoki path -> resp"""

    def __init__(self, routes, accept_scheme=None):
        self.routes = routes
        self.accept_scheme = accept_scheme
        self.calls = []

    def request(self, method, url, headers=None, timeout=None, **kw):
        path = url.split("/")[-1] if "/" not in url else url
        self.calls.append((method, url, dict(headers or {})))
        if self.accept_scheme:
            got = self.accept_scheme
            ok = (
                headers.get(got)
                or (got == "bearer" and headers.get("Authorization", "").startswith("Bearer "))
            )
            if not ok:
                return FakeResponse(401, {"message": "no"})
        for suffix, resp in self.routes.items():
            if url.endswith(suffix):
                return resp
        return FakeResponse(404, {"message": "not found"})


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
    tid = importlib.import_module("bot.tenants").create(555)
    importlib.import_module("bot.ctx").set(tid)
    return importlib.import_module("bot.bito")


def test_javobni_ochish(env):
    assert env.unwrap([1, 2]) == [1, 2]
    assert env.unwrap({"data": [1]}) == [1]
    assert env.unwrap({"data": {"data": [1, 2]}}) == [1, 2]


def test_kalit_tekshiruvi_sxemani_topadi(env):
    ses = FakeSession(
        {"profile/get-me": FakeResponse(200, {"id": "u1", "company_name": "X"})},
        accept_scheme="x-api-key",
    )
    client = env.Bito(api_key="k", session=ses)
    profile, scheme = client.verify()
    assert profile["company_name"] == "X"
    assert scheme == "x-api-key"


def test_notogri_kalit_tushunarli_xato(env):
    errors = importlib.import_module("bot.errors")
    ses = FakeSession({}, accept_scheme="x-api-key")
    ses.accept_scheme = "hech-qachon"
    client = env.Bito(api_key="yomon", session=ses)
    with pytest.raises(errors.BitoError) as exc:
        client.verify()
    assert "kalit" in str(exc.value).lower() or "Kalit" in str(exc.value)


def test_yol_keshlanadi(env):
    ses = FakeSession({"organization/get-all": FakeResponse(200, {"data": []})})
    client = env.Bito(api_key="k", scheme="x-api-key", session=ses)
    assert client.resolve("organizations") == "organization/get-all"
    before = len(ses.calls)
    assert client.resolve("organizations") == "organization/get-all"
    assert len(ses.calls) == before  # ikkinchi marta so'rov yo'q


def test_omborlar_tashkilot_boyicha_filtrlanadi(env):
    payload = {"data": [
        {"id": "w1", "organization_id": "o1", "status": "active"},
        {"id": "w2", "organization_id": "o2", "status": "active"},
        {"id": "w3", "organization_id": "o1", "status": "inactive"},
    ]}
    ses = FakeSession({"warehouse/get-all": FakeResponse(200, payload)})
    client = env.Bito(api_key="k", scheme="x-api-key", session=ses)
    got = client.warehouses(organization_id="o1")
    assert [w["id"] for w in got] == ["w1"]


def test_narx_royxati_sotuvni_tanlaydi(env):
    payload = {"data": [
        {"id": "p1", "type": "income", "status": "active"},
        {"id": "p2", "type": "sale", "status": "active", "is_main": True},
    ]}
    ses = FakeSession({"price/get-all": FakeResponse(200, payload)})
    client = env.Bito(api_key="k", scheme="x-api-key", session=ses)
    got = client.prices()
    assert [p["id"] for p in got] == ["p2"]
    assert env.pick_default(got, "is_main")["id"] == "p2"


def test_olchov_birligi_system_code_orqali(env):
    uoms = [
        {"id": "u1", "system_code": "kilogram", "name": "Kilogram"},
        {"id": "u2", "system_code": "piece", "name": "Dona"},
        {"id": "u3", "name": "Blok"},
    ]
    assert env.pick_uom(uoms, "piece")["id"] == "u2"
    assert env.pick_uom(uoms, "kilogram")["id"] == "u1"
    assert env.pick_uom(uoms, "litre", ("blok",))["id"] == "u3"
    assert env.pick_uom(uoms, "litre") is None


def test_server_xatosi_tushunarli_matn(env):
    errors = importlib.import_module("bot.errors")
    ses = FakeSession({"organization/get-all": FakeResponse(500, {"m": "x"})})
    client = env.Bito(api_key="k", scheme="x-api-key", session=ses)
    with pytest.raises(errors.BitoError) as exc:
        client.get("organizations")
    assert "Bito" in str(exc.value)
