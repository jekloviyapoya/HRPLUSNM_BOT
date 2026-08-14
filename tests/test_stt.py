"""Ovoz → matn (bot/stt.py)."""

import importlib
import sys

import pytest


def _reload(monkeypatch, tmp_path, **env):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "s.db"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test")
    monkeypatch.setenv("SAAS_OWNER_ID", "111")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    for name in list(sys.modules):
        if name == "bot" or name.startswith("bot."):
            del sys.modules[name]
    return importlib.import_module("bot.stt")


class FakeResp:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class FakeHTTP:
    def __init__(self, resp):
        self.resp = resp
        self.calls = []

    def post(self, url, headers=None, data=None, files=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "data": data,
                           "files": files})
        if isinstance(self.resp, Exception):
            raise self.resp
        return self.resp


def test_muvaffaqiyat(monkeypatch, tmp_path):
    stt = _reload(monkeypatch, tmp_path, GROQ_API_KEY="gsk-test")
    http = FakeHTTP(FakeResp(200, {"text": "  Pol yuvish kerak  "}))
    assert stt.transcribe(b"ogg-bytes", session=http) == "Pol yuvish kerak"
    call = http.calls[0]
    assert call["headers"]["Authorization"] == "Bearer gsk-test"
    assert call["data"]["model"] == stt.MODEL
    assert call["files"]["file"][0] == "voice.ogg"


def test_kalit_yoq_ochiq_emas(monkeypatch, tmp_path):
    stt = _reload(monkeypatch, tmp_path)
    from bot.errors import BotError
    assert stt.enabled() is False
    with pytest.raises(BotError):
        stt.transcribe(b"x", session=FakeHTTP(FakeResp(200, {"text": "a"})))


def test_http_xato_tushunarli_xabar(monkeypatch, tmp_path):
    stt = _reload(monkeypatch, tmp_path, GROQ_API_KEY="gsk-test")
    from bot.errors import BotError
    with pytest.raises(BotError) as e:
        stt.transcribe(b"x", session=FakeHTTP(FakeResp(429, text="quota")))
    assert "matn" in str(e.value).lower()


def test_bosh_matn_xato(monkeypatch, tmp_path):
    stt = _reload(monkeypatch, tmp_path, GROQ_API_KEY="gsk-test")
    from bot.errors import BotError
    with pytest.raises(BotError):
        stt.transcribe(b"x", session=FakeHTTP(FakeResp(200, {"text": "  "})))


def test_tarmoq_uzilishi(monkeypatch, tmp_path):
    stt = _reload(monkeypatch, tmp_path, GROQ_API_KEY="gsk-test")
    from bot.errors import BotError
    with pytest.raises(BotError):
        stt.transcribe(b"x", session=FakeHTTP(OSError("uzildi")))
