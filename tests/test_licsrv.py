"""Markaziy litsenziya: xaritalash va aloqa uzilishiga chidamlilik."""

import importlib
import sys

import pytest


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("json emas")
        return self._payload


class FakeHTTP:
    def __init__(self, response=None, boom=None):
        self.response = response
        self.boom = boom
        self.calls = []

    def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append((url, dict(params or {}), dict(headers or {})))
        if self.boom:
            raise self.boom
        return self.response


@pytest.fixture()
def mod(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
    monkeypatch.setenv("SAAS_OWNER_ID", "111")
    monkeypatch.setenv("LICENSE_SERVER_URL", "https://example.invalid")
    for name in list(sys.modules):
        if name == "bot" or name.startswith("bot."):
            del sys.modules[name]
    db = importlib.import_module("bot.db")
    db.migrate()
    ctx = importlib.import_module("bot.ctx")
    tenants = importlib.import_module("bot.tenants")
    tid = tenants.create(4242)
    ctx.set(tid)
    return {
        "db": db, "ctx": ctx, "tid": tid,
        "licsrv": importlib.import_module("bot.licsrv"),
        "license": importlib.import_module("bot.license"),
    }


def test_holat_xaritasi(mod):
    m = mod["licsrv"].map_status
    assert m({"status": "active"}) == "active"
    assert m({"status": "suspended"}) == "locked"
    assert m({"status": "invalid"}) == "locked"
    # muddat tugagan, imtiyoz kunlari ichida
    assert m({"status": "expired", "days_left": -2, "grace_days": 7}) == "grace"
    # imtiyoz kunlaridan chiqqan
    assert m({"status": "expired", "days_left": -9, "grace_days": 7}) == "locked"
    # grace_days yo'q bo'lsa darhol qulf
    assert m({"status": "expired", "days_left": -1}) == "locked"


def test_faol_kalit_saqlanadi(mod):
    lic = mod["license"]
    lic.set_key("GB-XXXX")
    http = FakeHTTP(FakeResponse(200, {
        "status": "active", "title": "Test", "expires_at": "2026-12-31",
        "days_left": 100, "grace_days": 7, "price": 500000.0,
    }))
    got, notice = lic.sync(session=http)
    assert got == "active"
    assert notice is None
    rec = lic.record()
    assert rec["expires_at"] == "2026-12-31"
    assert rec["source"] == "bmp"
    assert rec["remote_status"] == "active"
    assert http.calls[0][1]["key"] == "GB-XXXX"


def test_server_yiqilsa_mijoz_ishlashda_davom_etadi(mod):
    """Eng muhim: markaz yo'qligi mijozni qulflab qo'ymasin."""
    lic = mod["license"]
    lic.set_key("GB-XXXX")
    lic.sync(session=FakeHTTP(FakeResponse(200, {
        "status": "active", "expires_at": "2026-12-31",
        "days_left": 100, "grace_days": 7,
    })))
    assert lic.state() == "active"

    # server yiqildi
    got, _ = lic.sync(session=FakeHTTP(boom=OSError("tarmoq yo'q")))
    assert got == "active"
    assert lic.is_locked() is False
    assert lic.record()["offline_since"] is not None

    # 503 ham xuddi shunday
    got, _ = lic.sync(session=FakeHTTP(FakeResponse(503)))
    assert got == "active"
    assert lic.is_locked() is False


def test_aloqa_tiklangach_offline_belgisi_ochadi(mod):
    lic = mod["license"]
    lic.set_key("GB-XXXX")
    lic.sync(session=FakeHTTP(boom=OSError("yo'q")))
    assert lic.record()["offline_since"] is not None
    lic.sync(session=FakeHTTP(FakeResponse(200, {
        "status": "active", "expires_at": "2026-12-31", "days_left": 9,
    })))
    assert lic.record()["offline_since"] is None


def test_suspended_qulflaydi(mod):
    lic = mod["license"]
    lic.set_key("GB-XXXX")
    got, _ = lic.sync(session=FakeHTTP(FakeResponse(200, {
        "status": "suspended", "expires_at": "2026-12-31", "days_left": 5,
    })))
    assert got == "locked"
    assert lic.is_locked()


def test_xabar_bir_marta_korsatiladi(mod):
    lic = mod["license"]
    lic.set_key("GB-XXXX")
    payload = {
        "status": "active", "expires_at": "2026-09-01", "days_left": 3,
        "notice": {"id": "exp-2026-09-01", "level": "warning",
                   "text": "Obuna tugashiga 3 kun qoldi."},
    }
    _, first = lic.sync(session=FakeHTTP(FakeResponse(200, payload)))
    assert first["text"].startswith("Obuna")
    _, second = lic.sync(session=FakeHTTP(FakeResponse(200, payload)))
    assert second is None          # takrorlanmaydi

    payload["notice"]["id"] = "exp-2026-09-02"
    _, third = lic.sync(session=FakeHTTP(FakeResponse(200, payload)))
    assert third is not None       # yangi xabar ko'rsatiladi


def test_kalitsiz_mahalliy_sinov_ishlaydi(mod):
    lic = mod["license"]
    assert lic.record()["license_key"] is None
    assert lic.state() == "trial"
    got, notice = lic.sync(session=FakeHTTP(boom=OSError("chaqirilmasligi kerak")))
    assert got == "trial"
    assert notice is None


def test_tushunarsiz_javob_qabul_qilinmaydi(mod):
    licsrv = mod["licsrv"]
    with pytest.raises(licsrv.Unreachable):
        licsrv.check("k", session=FakeHTTP(FakeResponse(200, {"status": "???"})))
    with pytest.raises(licsrv.Unreachable):
        licsrv.check("k", session=FakeHTTP(FakeResponse(200, ["a"])))


def test_kalit_logga_tushmaydi(mod):
    """TZ §4.1: license_key hech qachon logga yozilmasin."""
    licsrv = mod["licsrv"]
    key = "GB-SECRET123"
    boom = OSError(
        f"HTTPSConnectionPool: Max retries exceeded with url: /api/check?key={key}"
    )
    with pytest.raises(licsrv.Unreachable) as exc:
        licsrv.check(key, session=FakeHTTP(boom=boom))
    assert key not in str(exc.value)
    assert "***" in str(exc.value)


def test_scrub_boshqa_shakllarni_ham_tozalaydi(mod):
    scrub = mod["licsrv"].scrub
    assert "abc" not in scrub("url?key=abc&bot=x", "abc")
    assert scrub("key=zzz", None) == "key=***"


# ------------------------------------------------- env nomlari va bootstrap


def _reload(monkeypatch, tmp_path, **env):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "b.db"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
    monkeypatch.setenv("SAAS_OWNER_ID", "111")
    for name in ("LICENSE_SERVER_URL", "LICENSE_API", "LICENSE_KEY",
                 "LICENSE_PROVISION_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    for name in list(sys.modules):
        if name == "bot" or name.startswith("bot."):
            del sys.modules[name]
    return importlib.import_module("bot.config")


def test_license_api_aliasi_qabul_qilinadi(monkeypatch, tmp_path):
    """BMP `LICENSE_API=.../api/check` beradi. Yo'l ikki marta qo'shilmasin."""
    config = _reload(monkeypatch, tmp_path,
                     LICENSE_API="https://web.up.railway.app/api/check")
    assert config.LICENSE_SERVER_URL == "https://web.up.railway.app"

    licsrv = importlib.import_module("bot.licsrv")
    lic = importlib.import_module("bot.license")
    db = importlib.import_module("bot.db")
    db.migrate()
    ctx = importlib.import_module("bot.ctx")
    tenants = importlib.import_module("bot.tenants")
    ctx.set(tenants.create(7))
    lic.set_key("GB-1")

    http = FakeHTTP(FakeResponse(200, {
        "status": "active", "expires_at": "2026-12-31", "days_left": 100,
    }))
    lic.sync(session=http)
    assert http.calls[0][0] == "https://web.up.railway.app/api/check"
    assert licsrv.base_url() == "https://web.up.railway.app"


def test_server_url_ustunroq(monkeypatch, tmp_path):
    config = _reload(monkeypatch, tmp_path,
                     LICENSE_SERVER_URL="https://aniq.example",
                     LICENSE_API="https://eski.example/api/check")
    assert config.LICENSE_SERVER_URL == "https://aniq.example"


def test_bootstrap_yagona_bizneega_qoyadi(monkeypatch, tmp_path):
    _reload(monkeypatch, tmp_path, LICENSE_API="https://x.invalid",
            LICENSE_KEY="GB-ENV")
    db = importlib.import_module("bot.db")
    db.migrate()
    ctx = importlib.import_module("bot.ctx")
    tenants = importlib.import_module("bot.tenants")
    lic = importlib.import_module("bot.license")
    tid = tenants.create(7)

    assert lic.bootstrap_key() == tid
    with ctx.scope(tid):
        assert lic.record()["license_key"] == "GB-ENV"


def test_bootstrap_kop_biznesda_tegmaydi(monkeypatch, tmp_path):
    """Kalit qaysi biznesniki ekani noma'lum — taxmin qilinmaydi."""
    _reload(monkeypatch, tmp_path, LICENSE_API="https://x.invalid",
            LICENSE_KEY="GB-ENV")
    db = importlib.import_module("bot.db")
    db.migrate()
    ctx = importlib.import_module("bot.ctx")
    tenants = importlib.import_module("bot.tenants")
    lic = importlib.import_module("bot.license")
    first, second = tenants.create(7), tenants.create(8)

    assert lic.bootstrap_key() is None
    for tid in (first, second):
        with ctx.scope(tid):
            assert lic.record()["license_key"] is None


def test_bootstrap_mavjud_kalitni_bosmaydi(monkeypatch, tmp_path):
    _reload(monkeypatch, tmp_path, LICENSE_API="https://x.invalid",
            LICENSE_KEY="GB-ENV")
    db = importlib.import_module("bot.db")
    db.migrate()
    ctx = importlib.import_module("bot.ctx")
    tenants = importlib.import_module("bot.tenants")
    lic = importlib.import_module("bot.license")
    tid = tenants.create(7)
    with ctx.scope(tid):
        lic.set_key("GB-QOLDA")

    assert lic.bootstrap_key() is None
    with ctx.scope(tid):
        assert lic.record()["license_key"] == "GB-QOLDA"


# ------------------------------------------------- avto ochish (provision)


class SeqHTTP:
    """URL oxiriga qarab javob beradigan soxta HTTP."""

    def __init__(self, routes):
        self.routes = routes            # {"/api/provision": FakeResponse, ...}
        self.calls = []

    def get(self, url, params=None, timeout=None, headers=None):
        self.calls.append((url, dict(params or {}), dict(headers or {})))
        for suffix, resp in self.routes.items():
            if url.endswith(suffix):
                if isinstance(resp, Exception):
                    raise resp
                return resp
        raise AssertionError(f"kutilmagan url: {url}")


def _prov_env(monkeypatch, tmp_path):
    _reload(monkeypatch, tmp_path,
            LICENSE_API="https://bmp.example/api/check",
            LICENSE_PROVISION_TOKEN="sinov-maxfiy")
    db = importlib.import_module("bot.db")
    db.migrate()
    return {
        "db": db,
        "ctx": importlib.import_module("bot.ctx"),
        "auth": importlib.import_module("bot.auth"),
        "license": importlib.import_module("bot.license"),
        "licsrv": importlib.import_module("bot.licsrv"),
    }


def test_provision_soroviga_token_va_telefon_ketadi(monkeypatch, tmp_path):
    m = _prov_env(monkeypatch, tmp_path)
    http = SeqHTTP({"/api/provision": FakeResponse(200, {
        "found": True, "key": "GB-YANGI", "business_name": "Test Market",
        "status": "active", "expires": "2026-09-14",
    })})
    got = m["licsrv"].provision("+998501097027", session=http)
    assert got["key"] == "GB-YANGI"
    url, params, headers = http.calls[0]
    assert url == "https://bmp.example/api/provision"
    assert params["phone"] == "+998501097027"
    assert headers["X-Provision-Token"] == "sinov-maxfiy"


def test_provision_topilmasa_none(monkeypatch, tmp_path):
    m = _prov_env(monkeypatch, tmp_path)
    http = SeqHTTP({"/api/provision": FakeResponse(200, {"found": False})})
    assert m["licsrv"].provision("+998501097027", session=http) is None


def test_provision_tokensiz_ochiq_emas(monkeypatch, tmp_path):
    _reload(monkeypatch, tmp_path, LICENSE_API="https://bmp.example/api/check")
    licsrv = importlib.import_module("bot.licsrv")
    assert licsrv.provision_enabled() is False
    # Chaqirilsa ham so'rov ketmaydi
    assert licsrv.provision("+998501097027", session=None) is None


def test_provision_403_unreachable(monkeypatch, tmp_path):
    """403 «topilmadi» emas — sozlama xatosi. Mijoz adashtirilmasin."""
    m = _prov_env(monkeypatch, tmp_path)
    http = SeqHTTP({"/api/provision": FakeResponse(403, {"found": False})})
    with pytest.raises(m["licsrv"].Unreachable):
        m["licsrv"].provision("+998501097027", session=http)


def test_provision_from_bmp_hisob_ochadi(monkeypatch, tmp_path):
    m = _prov_env(monkeypatch, tmp_path)
    http = SeqHTTP({
        "/api/provision": FakeResponse(200, {
            "found": True, "key": "GB-YANGI", "business_name": "Test Market",
            "status": "active", "expires": "2026-09-14",
        }),
        "/api/check": FakeResponse(200, {
            "status": "active", "expires_at": "2026-09-14", "days_left": 31,
            "grace_days": 7, "modules": ["xodimlar", "ombor"],
        }),
    })
    got = m["auth"].provision_from_bmp("+998501097027", tg_id=777, session=http)
    assert got is not None
    tenant_id, name = got
    assert name == "Test Market"

    with m["ctx"].scope(tenant_id):
        rec = m["license"].record()
        assert rec["license_key"] == "GB-YANGI"
        assert rec["source"] == "bmp"
        modules = importlib.import_module("bot.modules")
        assert modules.list_enabled() == ["xodimlar", "ombor"]

    row = m["db"].row("SELECT * FROM tenant WHERE id = ?", (tenant_id,))
    assert row["phone"] == "+998501097027"
    assert row["must_change"] == 1          # parolni o'zi o'rnatadi
    assert m["db"].value(
        "SELECT role FROM users WHERE tenant_id = ? AND tg_id = 777",
        (tenant_id,)) == "owner"


def test_provision_from_bmp_topilmasa_hisob_ochilmaydi(monkeypatch, tmp_path):
    m = _prov_env(monkeypatch, tmp_path)
    http = SeqHTTP({"/api/provision": FakeResponse(200, {"found": False})})
    assert m["auth"].provision_from_bmp("+998501097027", tg_id=777,
                                        session=http) is None
    assert m["db"].value("SELECT COUNT(*) FROM tenant") == 0


def test_provision_from_bmp_sync_yiqilsa_ham_hisob_qoladi(monkeypatch, tmp_path):
    """provision o'tdi, check o'tmadi — kalit turadi, fon ishi tuzatadi."""
    m = _prov_env(monkeypatch, tmp_path)
    http = SeqHTTP({
        "/api/provision": FakeResponse(200, {
            "found": True, "key": "GB-YANGI", "business_name": "T",
            "status": "active", "expires": "2026-09-14",
        }),
        "/api/check": OSError("tarmoq uzildi"),
    })
    got = m["auth"].provision_from_bmp("+998501097027", tg_id=777, session=http)
    assert got is not None
    with m["ctx"].scope(got[0]):
        assert m["license"].record()["license_key"] == "GB-YANGI"
