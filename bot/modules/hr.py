"""Ishga qabul moduli: vakansiya, AI suhbat, nomzod baholash.

Nomzod botga vakansiya havolasi orqali kiradi, AI bilan suhbatlashadi,
oxirida menejerlarga ball va xulosa boradi.

Uchta saboq market-bot'dan:

- **Bir vaqtda bitta savol.** AI ikkitasini birlashtirsa, nomzod
  faqat oxirgisiga javob beradi va ma'lumot yo'qoladi.
- **Suhbat oxiri maxsus belgi bilan.** `[TUGADI]` — foydalanuvchi
  ko'rmaydi, kod uni javobdan olib tashlaydi.
- **Rasm izohi 1024 belgidan oshsa Telegram jimgina rad etadi.**
  Rasm va to'liq xulosa alohida yuboriladi.

Nomzod `users` jadvaliga yozilmaydi: u boshqa do'konga ham ariza bera
olsin va «bir odam bitta biznesda» qoidasi buzilmasin.
"""

import json
import logging
import math

from . import base, registry
from .. import ai, ctx, db, sessions, tenant, ui, users
from ..errors import BotError

log = logging.getLogger(__name__)

END_MARK = "[TUGADI]"
MAX_TURNS = 30

DEFAULT_QUESTIONS = [
    "Ismingiz va yoshingiz?",
    "Qayerda yashaysiz?",
    "Oldingi ish tajribangiz haqida gapiring.",
    "Nima uchun aynan shu ishni tanladingiz?",
    "Qaysi kunlar va soatlarda ishlay olasiz?",
    "Kutayotgan oylik maoshingiz qancha?",
]


# ------------------------------------------------------------------ vakansiya


def create_job(title, created_by, requirements=None, questions=None,
               salary=None):
    if len(str(title).strip()) < 3:
        raise BotError("Lavozim nomi juda qisqa.")
    cur = db.run(
        "INSERT INTO job (tenant_id, title, requirements, questions, salary, "
        "  created_by) VALUES (?, ?, ?, ?, ?, ?)",
        (ctx.require(), str(title).strip(), requirements,
         json.dumps(questions or DEFAULT_QUESTIONS, ensure_ascii=False),
         salary, created_by),
    )
    return cur.lastrowid


def get_job(job_id):
    row = db.row("SELECT * FROM job WHERE tenant_id = ? AND id = ?",
                 (ctx.require(), job_id))
    return _job_dict(row)


def find_job(job_id):
    """Tenant konteksti yo'q holatda — nomzod havola orqali kirganda."""
    row = db.row("SELECT * FROM job WHERE id = ? AND status = 'ochiq'",
                 (job_id,))
    return (row["tenant_id"], _job_dict(row)) if row else (None, None)


def _job_dict(row):
    if not row:
        return None
    data = dict(row)
    try:
        data["questions"] = json.loads(row["questions"] or "[]")
    except (ValueError, TypeError):
        data["questions"] = DEFAULT_QUESTIONS
    return data


def jobs(only_open=True):
    sql = "SELECT * FROM job WHERE tenant_id = ?"
    if only_open:
        sql += " AND status = 'ochiq'"
    sql += " ORDER BY created_at DESC"
    return [_job_dict(row) for row in db.rows(sql, (ctx.require(),))]


def close_job(job_id):
    db.run("UPDATE job SET status = 'yopiq' WHERE tenant_id = ? AND id = ?",
           (ctx.require(), job_id))


def set_place(job_id, lat, lon, max_km=None):
    db.run("UPDATE job SET place_lat = ?, place_lon = ?, max_km = ? "
           "WHERE tenant_id = ? AND id = ?",
           (lat, lon, max_km, ctx.require(), job_id))


# ------------------------------------------------------------------- nomzod


def applicant(job_id, tg_id):
    return db.row(
        "SELECT * FROM applicant WHERE tenant_id = ? AND job_id = ? "
        "AND tg_id = ?", (ctx.require(), job_id, tg_id))


def start_application(job_id, tg_id, full_name=None):
    existing = applicant(job_id, tg_id)
    if existing and existing["status"] != "suhbatda":
        raise BotError("Siz bu vakansiyaga allaqachon ariza bergansiz.")
    if existing:
        return existing
    db.run(
        "INSERT INTO applicant (tenant_id, job_id, tg_id, full_name, history) "
        "VALUES (?, ?, ?, ?, '[]')",
        (ctx.require(), job_id, tg_id, full_name),
    )
    return applicant(job_id, tg_id)


def history_of(row):
    try:
        return json.loads(row["history"] or "[]")
    except (ValueError, TypeError):
        return []


def save_history(job_id, tg_id, history):
    db.run("UPDATE applicant SET history = ? WHERE tenant_id = ? "
           "AND job_id = ? AND tg_id = ?",
           (json.dumps(history[-MAX_TURNS:], ensure_ascii=False),
            ctx.require(), job_id, tg_id))


def applicants(job_id):
    return db.rows(
        "SELECT * FROM applicant WHERE tenant_id = ? AND job_id = ? "
        "ORDER BY score IS NULL, score DESC, created_at",
        (ctx.require(), job_id))


def set_status(job_id, tg_id, status):
    db.run("UPDATE applicant SET status = ? WHERE tenant_id = ? "
           "AND job_id = ? AND tg_id = ?",
           (status, ctx.require(), job_id, tg_id))


def distance_km(lat1, lon1, lat2, lon2):
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------------- AI suhbat


def system_prompt(job, shop):
    lines = [
        f'Sen "{job["title"]}" lavozimiga ishga qabul qiluvchi samimiy va '
        f'diqqatli HR-suhbatdoshsan. Do\'kon nomi: {shop}.',
        "",
    ]
    if job.get("requirements"):
        lines += ["TALABLAR:", job["requirements"], ""]
    if job.get("salary"):
        lines += [f"MAOSH: {job['salary']}", ""]
    lines.append("SO'RASH KERAK BO'LGAN SAVOLLAR (birma-bir, birortasini "
                 "tashlab ketmang):")
    lines += [f"- {question}" for question in job["questions"]]
    if job.get("place_lat"):
        lines += [
            "",
            "MANZIL: suhbat davomida nomzoddan yashash joyi lokatsiyasini "
            "bir marta so'rang (Telegram 📎 tugmasi orqali). Tizim masofani "
            "o'zi hisoblab sizga aytadi. Lokatsiya kelgach qayta so'ramang.",
        ]
    lines += [
        "",
        "QOIDALAR:",
        "1. Bir xabarda FAQAT bitta savol. Ikkitasini birlashtirmang — "
        "nomzod faqat oxirgisiga javob beradi.",
        "2. Oldingi ish tajribasi haqida albatta so'rang.",
        "3. Javobga qarab qisqa aniqlashtiruvchi savol berish mumkin, "
        "lekin suhbatni cho'zmang.",
        "4. Tizim «[Nomzod rasm yubordi]» yoki «[Nomzod lokatsiya yubordi]» "
        "desa — bu allaqachon qabul qilingan, qayta so'ramang.",
        "5. O'zbek tilida, lotin alifbosida, iliq va hurmat bilan yozing.",
        "6. Barcha savollarga javob olingach rahmat ayting va suhbatni "
        f"yakunlang. Yakuniy xabaringizni {END_MARK} bilan tugating "
        "(nomzod buni ko'rmaydi).",
    ]
    return "\n".join(lines)


def next_reply(job, history, shop=None, session=None):
    """AI navbatdagi savolni yozadi. Qaytadi: (matn, tugadimi)."""
    content = [{"type": "text", "text": system_prompt(job, shop
                                                      or tenant.shop_name())}]
    for entry in history:
        who = "Nomzod" if entry["role"] == "user" else "Siz"
        content.append({"type": "text", "text": f"{who}: {entry['content']}"})
    content.append({"type": "text",
                    "text": "Navbatdagi xabaringizni yozing."})

    text, _ = ai.ask(content, max_tokens=800, session=session)
    text = (text or "").strip()
    done = END_MARK in text
    text = text.replace(END_MARK, "").strip()
    if text.lower().startswith("siz:"):
        text = text[4:].strip()
    return text or "Rahmat!", done


SCORE_PROMPT = """Quyidagi ishga qabul suhbatini baholang.

Lavozim: {title}
Talablar: {requirements}

SUHBAT:
{transcript}

Javobni FAQAT JSON qaytaring:
{{
  "score": 0 dan 100 gacha butun son,
  "summary": "bir-ikki jumlada umumiy xulosa",
  "strengths": "kuchli tomonlari",
  "concerns": "xavotirli joylari yoki yetishmayotgan ma'lumot"
}}

Ball mezoni: talablarga moslik, tajriba, javoblarning aniqligi,
ish vaqtiga tayyorligi. Ma'lumot yetishmasa ballni pasaytiring va
buni «concerns» da yozing."""


def score_candidate(job, history, session=None):
    transcript = "\n".join(
        f"{'Nomzod' if e['role'] == 'user' else 'HR'}: {e['content']}"
        for e in history)
    prompt = SCORE_PROMPT.format(
        title=job["title"], requirements=job.get("requirements") or "—",
        transcript=transcript[:12000])
    try:
        data, _ = ai.ask_json([{"type": "text", "text": prompt}],
                              session=session)
    except BotError:
        log.warning("Nomzod baholanmadi", exc_info=True)
        return {"score": None, "summary": "Baholab bo'lmadi.",
                "strengths": "", "concerns": "AI javob bermadi."}
    try:
        score = int(float(data.get("score")))
        score = max(0, min(100, score))
    except (TypeError, ValueError):
        score = None
    return {
        "score": score,
        "summary": str(data.get("summary") or "")[:500],
        "strengths": str(data.get("strengths") or "")[:500],
        "concerns": str(data.get("concerns") or "")[:500],
    }


def finish(job_id, tg_id, job, session=None):
    row = applicant(job_id, tg_id)
    if not row:
        raise BotError("Ariza topilmadi.")
    result = score_candidate(job, history_of(row), session=session)
    db.run(
        "UPDATE applicant SET score = ?, summary = ?, strengths = ?, "
        "  concerns = ?, status = 'baholandi', finished_at = datetime('now') "
        "WHERE tenant_id = ? AND job_id = ? AND tg_id = ?",
        (result["score"], result["summary"], result["strengths"],
         result["concerns"], ctx.require(), job_id, tg_id),
    )
    return result


# -------------------------------------------------------------------- modul


@registry.implement("hr")
class HR(base.Module):
    def menu(self, role):
        if role == "staff":
            return []
        return [("🧑‍💼 Ishga qabul", "mod:hr:panel")]

    def register(self, bot, guard):
        _register(bot, guard)


def apply_link(bot, job_id):
    try:
        me = bot.get_me()
        return f"https://t.me/{me.username}?start=job_{job_id}"
    except Exception:  # noqa: BLE001
        return f"?start=job_{job_id}"


def _register(bot, guard):
    @bot.callback_query_handler(
        func=lambda c: (c.data or "").startswith("mod:hr:"))
    @guard
    def _click(call):
        ui.ack(bot, call)
        action = call.data.split(":", 2)[2]
        chat_id, tg_id = call.message.chat.id, call.from_user.id
        users.require_role(tg_id, "manager")

        if action == "panel":
            _panel(bot, chat_id, tg_id)
        elif action == "yangi":
            sessions.set(tg_id, "hr:lavozim", {})
            bot.send_message(chat_id, "Lavozim nomini yozing. Masalan: "
                                      "«Sotuvchi-konsultant».")
        elif action.startswith("kor_"):
            _job_card(bot, chat_id, tg_id, int(action.split("_")[1]))
        elif action.startswith("nomzod_"):
            _, job_id, applicant_tg = action.split("_")
            _applicant_card(bot, chat_id, tg_id, int(job_id),
                            int(applicant_tg))
        elif action.startswith("yop_"):
            close_job(int(action.split("_")[1]))
            bot.send_message(chat_id, "Vakansiya yopildi.")
            _panel(bot, chat_id, tg_id)
        elif action.startswith("qabul_") or action.startswith("rad_"):
            kind, job_id, applicant_tg = action.split("_")
            set_status(int(job_id), int(applicant_tg),
                       "qabul" if kind == "qabul" else "rad")
            bot.send_message(chat_id, "Belgilandi.")
            _job_card(bot, chat_id, tg_id, int(job_id))

    # `hr:suhbat` bu yerda ushlanmaydi — u nomzodga tegishli va
    # handlers.py da, modul tekshiruvisiz ishlanadi (nomzod tenant
    # foydalanuvchisi emas)
    @bot.message_handler(
        func=lambda m: (sessions.get_global(m.from_user.id)[0] or "")
        .startswith("hr:")
        and sessions.get_global(m.from_user.id)[0] != "hr:suhbat",
        content_types=["text"])
    @guard
    def _input(message):
        state, data = sessions.get_global(message.from_user.id)
        sessions.clear(message.from_user.id)
        _apply(bot, message, state, data)


def _apply(bot, message, state, data):
    chat_id, tg_id = message.chat.id, message.from_user.id
    text = (message.text or "").strip()

    if state == "hr:lavozim":
        job_id = create_job(text, created_by=tg_id)
        sessions.set(tg_id, "hr:talab", {"job_id": job_id})
        bot.send_message(
            chat_id,
            "Talablarni yozing: tajriba, yosh, ish vaqti va h.k.\n"
            "O'tkazib yuborish uchun «yo'q» deb yozing.")
        return

    if state == "hr:talab":
        job_id = data["job_id"]
        if text.lower() not in ("yo'q", "yoq", "-"):
            db.run("UPDATE job SET requirements = ? WHERE tenant_id = ? "
                   "AND id = ?", (text, ctx.require(), job_id))
        sessions.set(tg_id, "hr:savol", {"job_id": job_id})
        job = get_job(job_id)
        bot.send_message(
            chat_id,
            "Qo'shimcha savollar bo'lsa, har birini yangi qatordan yozing.\n\n"
            "Standart savollar allaqachon bor:\n"
            + "\n".join(f"• {q}" for q in job["questions"])
            + "\n\nQo'shimcha kerak bo'lmasa «yo'q» deb yozing.")
        return

    if state == "hr:savol":
        job_id = data["job_id"]
        if text.lower() not in ("yo'q", "yoq", "-"):
            extra = [line.strip(" -•") for line in text.splitlines()
                     if line.strip()]
            if extra:
                job = get_job(job_id)
                db.run("UPDATE job SET questions = ? WHERE tenant_id = ? "
                       "AND id = ?",
                       (json.dumps(job["questions"] + extra,
                                   ensure_ascii=False),
                        ctx.require(), job_id))
        _job_card(bot, chat_id, tg_id, job_id, fresh=True)


def _panel(bot, chat_id, tg_id):
    rows = jobs()
    lines = ["<b>Ishga qabul</b>", ""]
    if not ai.enabled():
        lines.append("⚠️ AI kaliti yo'q — suhbat ishlamaydi.\n")
    if rows:
        for job in rows:
            count = db.value("SELECT COUNT(*) FROM applicant WHERE "
                             "tenant_id = ? AND job_id = ?",
                             (ctx.require(), job["id"]), default=0)
            lines.append(f"• {ui.escape(job['title'])} — {count} nomzod")
    else:
        lines.append("Ochiq vakansiya yo'q.")

    buttons = [("➕ Yangi vakansiya", "mod:hr:yangi")]
    buttons += [(job["title"][:40], f"mod:hr:kor_{job['id']}") for job in rows]
    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML",
                     reply_markup=ui.buttons(buttons, row_width=1,
                                             back="menu:root"))


def _job_card(bot, chat_id, tg_id, job_id, fresh=False):
    job = get_job(job_id)
    if not job:
        bot.send_message(chat_id, "Vakansiya topilmadi.")
        return
    rows = applicants(job_id)
    link = apply_link(bot, job_id)

    lines = [f"<b>{ui.escape(job['title'])}</b>"]
    if job["requirements"]:
        lines.append(ui.escape(job["requirements"]))
    lines += ["", f"Savollar: {len(job['questions'])} ta",
              f"Nomzodlar: {len(rows)} ta", "",
              "Havolani e'lon qiling:", link]
    if fresh:
        lines.append("\nNomzod havolani ochsa, bot u bilan o'zi "
                     "suhbatlashadi va sizga ball bilan xulosa yuboradi.")

    buttons = [(f"{'⭐' * 0}{r['full_name'] or r['tg_id']}"
                + (f" — {r['score']}" if r["score"] is not None else " — suhbatda"),
                f"mod:hr:nomzod_{job_id}_{r['tg_id']}") for r in rows[:15]]
    if job["status"] == "ochiq":
        buttons.append(("🚫 Vakansiyani yopish", f"mod:hr:yop_{job_id}"))
    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML",
                     reply_markup=ui.buttons(buttons, row_width=1,
                                             back="mod:hr:panel"))


def _applicant_card(bot, chat_id, tg_id, job_id, applicant_tg):
    row = applicant(job_id, applicant_tg)
    if not row:
        bot.send_message(chat_id, "Nomzod topilmadi.")
        return
    lines = [f"<b>{ui.escape(row['full_name'] or '—')}</b>"]
    if row["phone"]:
        lines.append(f"Telefon: {ui.escape(row['phone'])}")
    if row["score"] is not None:
        lines.append(f"Ball: <b>{row['score']}/100</b>")
    if row["distance_km"] is not None:
        lines.append(f"Masofa: {row['distance_km']:.1f} km")
    if row["summary"]:
        lines += ["", ui.escape(row["summary"])]
    if row["strengths"]:
        lines.append(f"\n✅ Kuchli: {ui.escape(row['strengths'])}")
    if row["concerns"]:
        lines.append(f"⚠️ Xavotir: {ui.escape(row['concerns'])}")

    # Rasm izohi 1024 belgidan oshsa Telegram jimgina rad etadi —
    # rasm va matn alohida yuboriladi
    if row["photo_id"]:
        try:
            bot.send_photo(chat_id, row["photo_id"],
                           caption=ui.escape(row["full_name"] or "Nomzod"))
        except Exception:  # noqa: BLE001
            log.warning("Nomzod rasmi yuborilmadi", exc_info=True)
    if row["lat"] is not None:
        try:
            bot.send_location(chat_id, row["lat"], row["lon"])
        except Exception:  # noqa: BLE001
            log.warning("Lokatsiya yuborilmadi", exc_info=True)

    for chunk in ui.chunks("\n".join(lines)):
        bot.send_message(chat_id, chunk, parse_mode="HTML")
    bot.send_message(
        chat_id, "—",
        reply_markup=ui.buttons(
            [("✅ Qabul qilish", f"mod:hr:qabul_{job_id}_{applicant_tg}"),
             ("❌ Rad etish", f"mod:hr:rad_{job_id}_{applicant_tg}")],
            row_width=1, back=f"mod:hr:kor_{job_id}"))
