"""CONTRACT.md ga muvofiqlik.

Namunaviy javob shartnomadan **aynan** ko'chirilgan. Shartnoma o'zgarsa
shu test yiqiladi — bu maqsad.

Manba: jekloviyapoya/BMP_BOT/CONTRACT.md (2026-08-13)
"""

import importlib
import sys

import pytest

# CONTRACT.md §1 dagi javob namunasi
SAMPLE = {
    "status": "active",
    "expires": "2026-09-27",
    "expires_at": "2026-09-27",
    "days_left": 44,
    "grace_days": 7,
    "price": 500000.0,
    "business_name": "Humos Gold",
    "title": "Humos Gold",
    "modules": ["xodimlar", "ombor"],
    "modules_detail": {
        "post": {"limit": 3, "used": 1, "left": 2, "enabled": True}
    },
    "message": "Obuna tugashiga 3 kun qoldi",
    "notice": {
        "id": "exp-2026-09-27-d3",
        "level": "warning",
        "text": "Obuna tugashiga 3 kun qoldi. Uzaytirish: @ulugbekbekbergenovbmp",
    },
    "reset": None,
}


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError
        return self._payload


class FakeHTTP:
    def __init__(self, response=None, boom=None):
        self.response, self.boom = response, boom
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {}), timeout))
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
    tid = importlib.import_module("bot.tenants").create(900)
    ctx.set(tid)
    return {
        "licsrv": importlib.import_module("bot.licsrv"),
        "license": importlib.import_module("bot.license"),
        "modules": importlib.import_module("bot.modules"),
        "tid": tid,
    }


def test_namunaviy_javob_toliq_oqiladi(mod):
    lic, licsrv, modules = mod["license"], mod["licsrv"], mod["modules"]
    lic.set_key("GB-XXXX")
    state, notice = lic.sync(session=FakeHTTP(FakeResponse(200, SAMPLE)))

    assert state == "active"
    assert lic.record()["expires_at"] == "2026-09-27"
    assert lic.record()["price"] == 500000.0
    assert lic.record()["grace_days"] == 7
    assert modules.list_enabled() == ["xodimlar", "ombor"]
    assert notice["id"] == "exp-2026-09-27-d3"
    assert notice["level"] == "warning"
    del licsrv


def test_uzilish_shartnomadagi_12_soniya(mod):
    """§1.3: mijoz boti 12 soniyada uzadi."""
    assert mod["licsrv"].TIMEOUT == 12
    lic = mod["license"]
    lic.set_key("GB-XXXX")
    http = FakeHTTP(FakeResponse(200, SAMPLE))
    lic.sync(session=http)
    assert http.calls[0][2] == 12


def test_sorov_parametrlari(mod):
    """§1: ?key=...&bot=..."""
    lic = mod["license"]
    lic.set_key("GB-XXXX")
    http = FakeHTTP(FakeResponse(200, SAMPLE))
    lic.sync(session=http)
    url, params, _ = http.calls[0]
    assert url.endswith("/api/check")
    assert params["key"] == "GB-XXXX"


def test_notogri_kalit_200_bilan_keladi(mod):
    """§1.1: noto'g'ri kalitda ham HTTP 200 + status=invalid."""
    lic = mod["license"]
    lic.set_key("GB-YOMON")
    payload = dict(SAMPLE, status="invalid", modules=[], modules_detail={})
    state, _ = lic.sync(session=FakeHTTP(FakeResponse(200, payload)))
    assert state == "locked"
    assert lic.record()["remote_status"] == "invalid"


def test_503_offline_deb_qabul_qilinadi(mod):
    """§1.1: baza yiqilgan -> 503 -> mijoz oxirgi holatda ishlaydi."""
    lic, modules = mod["license"], mod["modules"]
    lic.set_key("GB-XXXX")
    lic.sync(session=FakeHTTP(FakeResponse(200, SAMPLE)))
    assert modules.list_enabled() == ["xodimlar", "ombor"]

    state, _ = lic.sync(session=FakeHTTP(FakeResponse(503)))
    assert state == "active"
    assert lic.is_locked() is False
    assert modules.list_enabled() == ["xodimlar", "ombor"]  # o'chib ketmadi


def test_bosh_modullar_royxati_hurmat_qilinadi(mod):
    """§1.2: bo'sh [] = «modul yo'q», maydon yo'qligi = «eskisini saqla»."""
    lic, modules, licsrv = mod["license"], mod["modules"], mod["licsrv"]
    lic.set_key("GB-XXXX")
    lic.sync(session=FakeHTTP(FakeResponse(200, SAMPLE)))

    empty = dict(SAMPLE, modules=[])
    lic.sync(session=FakeHTTP(FakeResponse(200, empty)))
    assert modules.list_enabled() == []

    lic.sync(session=FakeHTTP(FakeResponse(200, SAMPLE)))
    without = {k: v for k, v in SAMPLE.items() if k != "modules"}
    assert licsrv.modules_of(without) is None
    lic.sync(session=FakeHTTP(FakeResponse(200, without)))
    assert modules.list_enabled() == ["xodimlar", "ombor"]  # saqlandi


def test_notice_id_barqaror_bir_marta(mod):
    """§1.6: bir xil id — bir marta ko'rsatiladi."""
    lic = mod["license"]
    lic.set_key("GB-XXXX")
    _, first = lic.sync(session=FakeHTTP(FakeResponse(200, SAMPLE)))
    assert first is not None
    _, second = lic.sync(session=FakeHTTP(FakeResponse(200, SAMPLE)))
    assert second is None


def test_expired_grace_va_qulf(mod):
    lic = mod["license"]
    lic.set_key("GB-XXXX")
    grace = dict(SAMPLE, status="expired", days_left=-3, grace_days=7)
    assert lic.sync(session=FakeHTTP(FakeResponse(200, grace)))[0] == "grace"
    over = dict(SAMPLE, status="expired", days_left=-9, grace_days=7)
    assert lic.sync(session=FakeHTTP(FakeResponse(200, over)))[0] == "locked"


def test_suspended_qulflaydi(mod):
    """§1.5: suspended -> keyingi tekshiruvda to'xtaydi."""
    lic = mod["license"]
    lic.set_key("GB-XXXX")
    payload = dict(SAMPLE, status="suspended")
    assert lic.sync(session=FakeHTTP(FakeResponse(200, payload)))[0] == "locked"


def test_modul_kalitlari_shartnomaga_mos(mod):
    """§3: HRPLUSNM modul kalitlari ro'yxati."""
    expected = {
        "xodimlar", "vazifalar", "hr", "ombor", "ombor_ai",
        "nakladnoy", "inventarizatsiya", "moliya", "marketing", "mijoz",
    }
    assert set(mod["modules"].KEYS) == expected


def test_boglikliklar_shartnomaga_mos(mod):
    """§3: ombor_ai va inventarizatsiya uchun ombor shart."""
    registry = importlib.import_module("bot.modules.registry")
    assert registry.BY_KEY["ombor_ai"].depends == ("ombor",)
    assert registry.BY_KEY["inventarizatsiya"].depends == ("ombor",)
    assert registry.resolve_depends(["ombor_ai"]) == ["ombor", "ombor_ai"]


def test_kalit_niqoblanadi(mod):
    """§1.4: kalit logga tushmasin."""
    licsrv = mod["licsrv"]
    key = "GB-MAXFIY99"
    boom = OSError(f"connection failed url: /api/check?key={key}&bot=X")
    with pytest.raises(licsrv.Unreachable) as exc:
        licsrv.check(key, session=FakeHTTP(boom=boom))
    assert key not in str(exc.value)


# --- §1.6 Offline qoidasi ---

def _sample(days_from_today, grace=7, status="active"):
    import datetime as dt
    date = (dt.date.today() + dt.timedelta(days=days_from_today)).isoformat()
    return dict(SAMPLE, status=status, expires=date, expires_at=date,
                days_left=days_from_today, grace_days=grace)


def test_aloqa_yoqligi_qulflash_sababi_emas(mod):
    """§1.6: to'lagan mijoz markaz yiqilsa ham ishlayveradi."""
    lic = mod["license"]
    lic.set_key("GB-XXXX")
    lic.sync(session=FakeHTTP(FakeResponse(200, _sample(+30))))
    assert lic.state() == "active"

    for _ in range(5):                      # uzoq uzilish
        lic.sync(session=FakeHTTP(boom=OSError("tarmoq yo'q")))
    assert lic.state() == "active"
    assert lic.is_locked() is False


def test_mahalliy_muddat_tugasa_aloqasiz_ham_cheklanadi(mod):
    """§1.6: yo'lni to'sib cheksiz litsenziya ishlamaydi."""
    lic = mod["license"]
    lic.set_key("GB-XXXX")
    # server oxirgi marta «active» degan, lekin muddat kecha tugagan
    lic.sync(session=FakeHTTP(FakeResponse(200, _sample(-1, grace=7))))
    assert lic.state() == "grace"           # imtiyoz kunlari ichida

    lic.sync(session=FakeHTTP(boom=OSError("aloqa yo'q")))
    assert lic.state() == "grace"           # aloqa yo'q, lekin sana hukmron


def test_imtiyoz_kunlaridan_chiqsa_aloqasiz_qulflanadi(mod):
    lic = mod["license"]
    lic.set_key("GB-XXXX")
    lic.sync(session=FakeHTTP(FakeResponse(200, _sample(-20, grace=7))))
    lic.sync(session=FakeHTTP(boom=OSError("aloqa yo'q")))
    assert lic.state() == "locked"
    assert lic.is_locked()


def test_server_suspended_desa_sana_kelajakda_bolsa_ham_qulf(mod):
    """Ikki manbadan qat'iyrog'i olinadi."""
    lic = mod["license"]
    lic.set_key("GB-XXXX")
    lic.sync(session=FakeHTTP(FakeResponse(200, _sample(+30, status="suspended"))))
    assert lic.state() == "locked"
    lic.sync(session=FakeHTTP(boom=OSError("aloqa yo'q")))
    assert lic.state() == "locked"          # aloqa uzilsa ham ochilmaydi


def test_tolov_kelgach_aloqa_tiklanib_ochiladi(mod):
    lic = mod["license"]
    lic.set_key("GB-XXXX")
    lic.sync(session=FakeHTTP(FakeResponse(200, _sample(-20, grace=7))))
    assert lic.is_locked()
    lic.sync(session=FakeHTTP(FakeResponse(200, _sample(+30))))
    assert lic.state() == "active"


def test_grace_days_kelmasa_standart_ishlatiladi(mod):
    lic = mod["license"]
    lic.set_key("GB-XXXX")
    payload = _sample(-2)
    payload.pop("grace_days")
    lic.sync(session=FakeHTTP(FakeResponse(200, payload)))
    lic.sync(session=FakeHTTP(boom=OSError("aloqa yo'q")))
    assert lic.state() in ("grace", "locked")   # standart GRACE_DAYS=3
