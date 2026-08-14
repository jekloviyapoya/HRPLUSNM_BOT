"""Ishga qabul: vakansiya, suhbat, baholash."""

import importlib
import json
import sys

import pytest


class Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload
        self.text = str(payload)

    def json(self):
        if self._payload is None:
            raise ValueError
        return self._payload


class FakeAI:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append(json)
        text = self.replies.pop(0) if self.replies else "..."
        return Resp(200, {"content": [{"type": "text", "text": text}],
                          "stop_reason": "end_turn"})


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
    tid = importlib.import_module("bot.tenants").create(10, name="Egasi")
    ctx.set(tid)
    importlib.import_module("bot.tenant").set("shop_name", "Humos Gold")
    return {"h": importlib.import_module("bot.modules.hr"),
            "db": db, "ctx": ctx, "tid": tid,
            "errors": importlib.import_module("bot.errors")}


# --- vakansiya ---

def test_vakansiya_yaratiladi(env):
    h = env["h"]
    job_id = h.create_job("Sotuvchi-konsultant", created_by=10)
    job = h.get_job(job_id)
    assert job["status"] == "ochiq"
    assert len(job["questions"]) == len(h.DEFAULT_QUESTIONS)


def test_qisqa_lavozim_rad_etiladi(env):
    h = env["h"]
    with pytest.raises(env["errors"].BotError):
        h.create_job("ok", created_by=10)


def test_yopilgan_vakansiya_royxatda_yoq(env):
    h = env["h"]
    job_id = h.create_job("Sotuvchi", created_by=10)
    assert len(h.jobs()) == 1
    h.close_job(job_id)
    assert h.jobs() == []
    assert len(h.jobs(only_open=False)) == 1


def test_yopilgan_vakansiyaga_havola_ishlamaydi(env):
    h = env["h"]
    job_id = h.create_job("Sotuvchi", created_by=10)
    assert h.find_job(job_id)[0] == env["tid"]
    h.close_job(job_id)
    assert h.find_job(job_id) == (None, None)


# --- nomzod ---

def test_ariza_ochiladi(env):
    h = env["h"]
    job_id = h.create_job("Sotuvchi", created_by=10)
    row = h.start_application(job_id, 200, full_name="Ali")
    assert row["status"] == "suhbatda"
    assert h.history_of(row) == []


def test_takroriy_ariza_suhbat_davom_etadi(env):
    h = env["h"]
    job_id = h.create_job("Sotuvchi", created_by=10)
    h.start_application(job_id, 200)
    h.save_history(job_id, 200, [{"role": "assistant", "content": "Salom"}])
    row = h.start_application(job_id, 200)
    assert len(h.history_of(row)) == 1


def test_baholangach_qayta_ariza_berilmaydi(env):
    h = env["h"]
    job_id = h.create_job("Sotuvchi", created_by=10)
    h.start_application(job_id, 200)
    h.finish(job_id, 200, h.get_job(job_id),
             session=FakeAI(['{"score": 80, "summary": "yaxshi"}']))
    with pytest.raises(env["errors"].BotError):
        h.start_application(job_id, 200)


def test_nomzod_users_jadvaliga_yozilmaydi(env):
    """Nomzod boshqa do'konga ham ariza bera olsin."""
    h = env["h"]
    users = importlib.import_module("bot.users")
    job_id = h.create_job("Sotuvchi", created_by=10)
    h.start_application(job_id, 200)
    assert users.get(200) is None


def test_tarix_saqlanadi_va_cheklanadi(env):
    h = env["h"]
    job_id = h.create_job("Sotuvchi", created_by=10)
    h.start_application(job_id, 200)
    long_history = [{"role": "user", "content": str(i)} for i in range(50)]
    h.save_history(job_id, 200, long_history)
    assert len(h.history_of(h.applicant(job_id, 200))) == h.MAX_TURNS


# --- masofa ---

def test_masofa_hisobi(env):
    h = env["h"]
    assert h.distance_km(41.31, 69.28, 41.31, 69.28) == 0
    assert 1.0 < h.distance_km(41.31, 69.28, 41.32, 69.28) < 1.3


# --- AI suhbat ---

def test_bitta_savol_qoidasi_promptda(env):
    h = env["h"]
    job = {"title": "Sotuvchi", "questions": ["Ismingiz?"],
           "requirements": None, "salary": None}
    text = h.system_prompt(job, "Humos Gold")
    assert "FAQAT bitta savol" in text
    assert h.END_MARK in text
    assert "Ismingiz?" in text


def test_tugash_belgisi_javobdan_olinadi(env):
    h = env["h"]
    job = {"title": "Sotuvchi", "questions": [], "requirements": None,
           "salary": None}
    text, done = h.next_reply(job, [], session=FakeAI(
        [f"Rahmat, siz bilan bog'lanamiz. {h.END_MARK}"]))
    assert done is True
    assert h.END_MARK not in text
    assert "Rahmat" in text


def test_suhbat_davom_etsa_tugamaydi(env):
    h = env["h"]
    job = {"title": "Sotuvchi", "questions": [], "requirements": None,
           "salary": None}
    text, done = h.next_reply(job, [], session=FakeAI(["Ismingiz nima?"]))
    assert done is False
    assert text == "Ismingiz nima?"


def test_lokatsiya_soralishi_promptga_qoshiladi(env):
    h = env["h"]
    job = {"title": "S", "questions": [], "requirements": None,
           "salary": None, "place_lat": 41.3, "place_lon": 69.2}
    assert "lokatsiya" in h.system_prompt(job, "X").lower()


# --- baholash ---

def test_nomzod_baholanadi(env):
    h = env["h"]
    job_id = h.create_job("Sotuvchi", created_by=10)
    h.start_application(job_id, 200, full_name="Ali")
    h.save_history(job_id, 200, [{"role": "user", "content": "3 yil tajriba"}])
    result = h.finish(job_id, 200, h.get_job(job_id), session=FakeAI([
        json.dumps({"score": 78, "summary": "Tajribali",
                    "strengths": "Sotuvda tajriba", "concerns": "Yo'q"})]))
    assert result["score"] == 78
    row = h.applicant(job_id, 200)
    assert row["status"] == "baholandi"
    assert row["summary"] == "Tajribali"


def test_ball_chegaradan_chiqmaydi(env):
    h = env["h"]
    job = {"title": "S", "requirements": None}
    high = h.score_candidate(job, [], session=FakeAI(['{"score": 500}']))
    low = h.score_candidate(job, [], session=FakeAI(['{"score": -20}']))
    assert high["score"] == 100
    assert low["score"] == 0


def test_ai_yiqilsa_ariza_yoqolmaydi(env):
    h = env["h"]
    job_id = h.create_job("Sotuvchi", created_by=10)
    h.start_application(job_id, 200)

    class Boom:
        def post(self, *a, **k):
            raise OSError("tarmoq yo'q")

    result = h.finish(job_id, 200, h.get_job(job_id), session=Boom())
    assert result["score"] is None
    assert h.applicant(job_id, 200)["status"] == "baholandi"


def test_notogri_ball_none_boladi(env):
    h = env["h"]
    result = h.score_candidate({"title": "S", "requirements": None}, [],
                               session=FakeAI(['{"score": "yaxshi"}']))
    assert result["score"] is None


# --- ro'yxat ---

def test_nomzodlar_ball_boyicha_tartiblanadi(env):
    h = env["h"]
    job_id = h.create_job("Sotuvchi", created_by=10)
    for tg, score in [(201, 50), (202, 90), (203, 70)]:
        h.start_application(job_id, tg)
        env["db"].run("UPDATE applicant SET score = ? WHERE tenant_id = ? "
                      "AND job_id = ? AND tg_id = ?",
                      (score, env["tid"], job_id, tg))
    assert [r["tg_id"] for r in h.applicants(job_id)] == [202, 203, 201]


def test_vakansiya_biznesga_xos(env):
    h, ctx = env["h"], env["ctx"]
    tenants = importlib.import_module("bot.tenants")
    h.create_job("Sotuvchi", created_by=10)
    with ctx.scope(tenants.create(50)):
        assert h.jobs() == []


def test_modul_bitosiz(env):
    registry = importlib.import_module("bot.modules.registry")
    registry.load()
    modules = importlib.import_module("bot.modules")
    assert registry.BY_KEY["hr"].ready
    assert not modules.needs_bito("hr")
