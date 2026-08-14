"""Telegram handlerlari.

Har xabarda birinchi ish — foydalanuvchi qaysi biznesga tegishli ekanini
aniqlab, ctx ga qo'yish. Busiz hech bir so'rov bajarilmaydi.
"""

import functools
import logging

from . import (auth, config, ctx, db, license, licsrv, modules, onboarding,
               sessions, settings_ui, tenant, tenants, ui, users)
from .modules import registry
from .errors import BotError

log = logging.getLogger(__name__)

JOIN_PROMPT = (
    "Taklif kodini yuboring (6 ta belgi).\n"
    "Kodni do'kon egasi <b>Xodimlar</b> bo'limidan oladi."
)


def _chat_id(obj):
    msg = getattr(obj, "message", None) or obj
    return msg.chat.id


def _payload(message):
    """/start ABC123 dagi kodni ajratadi."""
    parts = (message.text or "").split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else None


def register(bot):
    def _tell(obj, text):
        try:
            bot.send_message(_chat_id(obj), text)
        except Exception:  # noqa: BLE001
            log.error("Xato xabarini yuborib bo'lmadi", exc_info=True)

    def safe(fn):
        @functools.wraps(fn)
        def wrapper(obj, *args, **kwargs):
            tg_id = obj.from_user.id
            ctx.set(tenants.find_by_user(tg_id))
            try:
                return fn(obj, *args, **kwargs)
            except BotError as e:
                log.warning("%s: %s", fn.__name__, e, exc_info=True)
                _tell(obj, f"⚠️ {e.user_message}")
            except Exception:  # noqa: BLE001 — hech nima jim yiqilmasin
                log.exception("%s da kutilmagan xato (tenant=%s)",
                              fn.__name__, ctx.current())
                _tell(obj, "⚠️ Kutilmagan xato. Log yozildi.\n"
                           f"BUILD sha={config.BUILD_SHA}")
            finally:
                ctx.clear()

        return wrapper

    def _seen(message):
        return db.seen_update(f"msg:{message.chat.id}:{message.message_id}")

    def _greet(message):
        """Biznesi bor foydalanuvchiga menyu."""
        users.touch(message.from_user.id)
        note = ""
        if users.role_of(message.from_user.id) == "owner":
            pending = onboarding.pending_summary()
            if pending:
                note = "\n\n⚙️ Sozlanmagan: " + ", ".join(pending)
        bot.send_message(
            message.chat.id,
            f"<b>{ui.escape(tenant.shop_name())}</b>\n"
            f"{ui.escape(license.summary())}{ui.escape(note)}",
            parse_mode="HTML",
            reply_markup=ui.main_menu(message.from_user.id),
        )

    # ------------------------------------------------------------------ start

    @bot.message_handler(commands=["start"])
    @safe
    def _start(message):
        if _seen(message):
            return
        tg_id = message.from_user.id

        payload = _payload(message)

        # Vakansiya havolasi — nomzod tenant foydalanuvchisi emas.
        # Bu tekshiruv birinchi: xodim ham boshqa do'konga ariza bera oladi.
        if payload and payload.startswith("job_"):
            _apply_to_job(message, payload[4:])
            return

        # QR kod orqali baho — mijoz ham tenant foydalanuvchisi emas
        if payload and payload.startswith("baho_"):
            _start_feedback(message, payload[5:])
            return

        # Yangi odam
        if ctx.current() is None:
            if payload:
                _do_join(message, payload)
                return
            bot.send_message(
                message.chat.id,
                "Salom! Bu — do'kon boshqaruv boti.\n\n"
                "Do'kon egasi bo'lsangiz — sotuvchi bergan telefon va parol "
                "bilan kiring.\nXodim bo'lsangiz — egangiz bergan taklif "
                "kodini yuboring.",
                reply_markup=ui.buttons(
                    [
                        ("🔑 Kirish (telefon + parol)", "join:login"),
                        ("👥 Taklif kodi bilan", "join:code"),
                    ],
                    row_width=1,
                ),
            )
            return

        # Sehrgar o'rtasida
        step = onboarding.current_step(tg_id)
        if step:
            onboarding.resume(bot, message, step)
            return

        _greet(message)

    def _start_feedback(message, raw_id):
        """Mijoz QR kod orqali kirdi."""
        try:
            tenant_id = int(raw_id)
        except ValueError:
            bot.send_message(message.chat.id, "Havola noto'g'ri.")
            return
        if not db.row("SELECT id FROM tenant WHERE id = ? AND active = 1",
                      (tenant_id,)):
            bot.send_message(message.chat.id, "Do'kon topilmadi.")
            return

        ctx.set(tenant_id)
        if not modules.enabled("mijoz"):
            bot.send_message(message.chat.id, "Baho qabul qilish hozir "
                                              "faol emas.")
            return
        shop = tenant.shop_name()
        sessions.set(message.from_user.id, "baho:yulduz",
                     {"tenant_id": tenant_id}, tenant_id=tenant_id)
        bot.send_message(
            message.chat.id,
            f"<b>{ui.escape(shop)}</b>\n\nXizmatimizni baholang:",
            parse_mode="HTML",
            reply_markup=ui.buttons(
                [(f"{star}⭐", f"baho:{tenant_id}:{star}")
                 for star in range(1, 6)], row_width=5))

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("baho:"))
    @safe
    def _feedback_stars(call):
        ui.ack(bot, call, "Rahmat!")
        from .modules import mijoz

        _, raw_tenant, raw_star = call.data.split(":")
        tenant_id, star = int(raw_tenant), int(raw_star)
        tg_id = call.from_user.id

        with ctx.scope(tenant_id):
            feedback_id = mijoz.add(tg_id=tg_id, stars=star)
            low = star < mijoz.ALERT_BELOW
            targets = [u["tg_id"] for u in users.listing()
                       if u["role"] in ("owner", "manager")] if low else []
            shop = tenant.shop_name()

        sessions.set(tg_id, "baho:izoh",
                     {"tenant_id": tenant_id, "feedback_id": feedback_id},
                     tenant_id=tenant_id)
        ask = ("Nima yoqmadi? Yozib qoldiring — tuzatamiz."
               if low else "Rahmat! Taklif yoki izohingiz bo'lsa yozing.")
        bot.send_message(call.message.chat.id,
                         f"{mijoz.STARS.get(star, '')} {'⭐' * star}\n\n{ask}")

        for target in targets:
            try:
                bot.send_message(
                    target,
                    f"😞 {shop}: mijoz {star}⭐ qo'ydi. Izohini kutmoqdamiz.")
            except Exception:  # noqa: BLE001
                log.warning("Past baho xabari ketmadi: %s", target,
                            exc_info=True)

    def _do_login(message, phone):
        tg_id = message.from_user.id
        sessions.clear(tg_id)
        tenant_id, must_change = auth.login(tg_id, phone, message.text or "")
        auth.bind_owner(
            tenant_id, tg_id,
            name=(message.from_user.first_name or "").strip() or None,
            username=message.from_user.username)
        ctx.set(tenant_id)

        bot.send_message(
            message.chat.id,
            f"✅ Kirdingiz: <b>{ui.escape(tenant.shop_name())}</b>\n\n"
            "Parol yozilgan xabarni o'chirib tashlashni unutmang.",
            parse_mode="HTML")

        if must_change:
            sessions.set(tg_id, "auth:yangi_parol", {})
            bot.send_message(
                message.chat.id,
                "Xavfsizlik uchun yangi parol o'ylang va yuboring "
                f"(kamida {auth.MIN_LENGTH} ta belgi).")
            return
        _greet(message)

    def _change_password(message):
        tg_id = message.from_user.id
        sessions.clear(tg_id)
        users.require_role(tg_id, "owner")
        auth.set_password(ctx.require(), (message.text or "").strip())
        bot.send_message(
            message.chat.id,
            "✅ Parol o'zgartirildi. Eski parol endi ishlamaydi.\n"
            "Bu xabarni ham o'chirib tashlang.",
            reply_markup=ui.main_menu(tg_id))

    def _apply_to_job(message, raw_id):
        """Nomzod vakansiya havolasi orqali kirdi."""
        from .modules import hr

        try:
            job_id = int(raw_id)
        except ValueError:
            bot.send_message(message.chat.id, "Havola noto'g'ri.")
            return
        tenant_id, job = hr.find_job(job_id)
        if not job:
            bot.send_message(message.chat.id,
                             "Bu vakansiya yopilgan yoki topilmadi.")
            return

        ctx.set(tenant_id)
        if not modules.enabled("hr"):
            bot.send_message(message.chat.id, "Vakansiya hozir faol emas.")
            return

        tg_id = message.from_user.id
        name = (message.from_user.first_name or "").strip() or None
        hr.start_application(job_id, tg_id, full_name=name)
        sessions.set(tg_id, "hr:suhbat", {"job_id": job_id},
                     tenant_id=tenant_id)
        bot.send_message(
            message.chat.id,
            f"Assalomu alaykum! <b>{ui.escape(tenant.shop_name())}</b> "
            f"«{ui.escape(job['title'])}» lavozimiga nomzodlarni "
            "qabul qilmoqda.\n\nBir necha savol beraman — bemalol javob "
            "bering.",
            parse_mode="HTML")
        _interview_step(message.chat.id, tg_id, tenant_id, job_id, None)

    def _interview_step(chat_id, tg_id, tenant_id, job_id, answer,
                        extra=None):
        """Suhbatning bir qadami."""
        from .modules import hr

        with ctx.scope(tenant_id):
            job = hr.get_job(job_id)
            row = hr.applicant(job_id, tg_id)
            if not job or not row or row["status"] != "suhbatda":
                sessions.clear(tg_id)
                return
            history = hr.history_of(row)
            if answer:
                history.append({"role": "user", "content": answer})
            if extra:
                history.append({"role": "user", "content": extra})

            text, done = hr.next_reply(job, history)
            history.append({"role": "assistant", "content": text})
            hr.save_history(job_id, tg_id, history)

        bot.send_message(chat_id, text)

        if done:
            with ctx.scope(tenant_id):
                result = hr.finish(job_id, tg_id, job)
                targets = [u["tg_id"] for u in users.listing()
                           if u["role"] in ("owner", "manager")]
                card = hr.applicant(job_id, tg_id)
                shop_job = job["title"]
            sessions.clear(tg_id)
            bot.send_message(
                chat_id,
                "Suhbat yakunlandi. Rahmat! Natija haqida xabar beramiz.")
            _notify_hr(targets, card, shop_job, result)
        else:
            sessions.set(tg_id, "hr:suhbat", {"job_id": job_id,
                                              "tenant_id": tenant_id},
                         tenant_id=tenant_id)

    def _notify_hr(targets, row, job_title, result):
        """Rasm va matn ALOHIDA: izoh 1024 dan oshsa Telegram jim rad etadi."""
        score = result["score"]
        lines = [
            f"🆕 <b>Yangi nomzod</b> — {ui.escape(job_title)}",
            f"👤 {ui.escape(row['full_name'] or '—')}",
        ]
        if score is not None:
            lines.append(f"⭐ Ball: <b>{score}/100</b>")
        if row["distance_km"] is not None:
            lines.append(f"📍 Masofa: {row['distance_km']:.1f} km")
        if result["summary"]:
            lines += ["", ui.escape(result["summary"])]
        if result["strengths"]:
            lines.append(f"\n✅ {ui.escape(result['strengths'])}")
        if result["concerns"]:
            lines.append(f"⚠️ {ui.escape(result['concerns'])}")
        text = "\n".join(lines)

        for target in targets:
            try:
                if row["photo_id"]:
                    bot.send_photo(target, row["photo_id"],
                                   caption=ui.escape(row["full_name"] or "—"))
                bot.send_message(target, text, parse_mode="HTML")
            except Exception:  # noqa: BLE001
                log.warning("HR xabari yetkazilmadi: %s", target,
                            exc_info=True)

    def _do_join(message, code):
        tg_id = message.from_user.id
        tenant_id = tenants.join(
            tg_id,
            code,
            name=(message.from_user.first_name or "").strip() or None,
            username=message.from_user.username,
        )
        ctx.set(tenant_id)
        sessions.clear(tg_id)
        bot.send_message(
            message.chat.id,
            f"✅ Qo'shildingiz: <b>{ui.escape(tenant.shop_name())}</b>\n"
            "Rolingiz — xodim. Egasi kerak bo'lsa rolingizni ko'taradi.",
            parse_mode="HTML",
            reply_markup=ui.main_menu(tg_id),
        )

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("join:"))
    @safe
    def _join_click(call):
        ui.ack(bot, call)
        tg_id = call.from_user.id
        if ctx.current() is not None:
            bot.send_message(call.message.chat.id,
                             "Siz allaqachon bir biznesdasiz.")
            return

        if call.data == "join:login":
            sessions.set(tg_id, "auth:telefon", {})
            bot.send_message(
                call.message.chat.id,
                "Telefon raqamingizni pastdagi tugma orqali yuboring — "
                "birinchi marta kirayotgan bo'lsangiz hisob avtomatik "
                "ochiladi.\n\n"
                "Yoki raqamni yozing: <code>+998901234567</code>",
                parse_mode="HTML",
                reply_markup=ui.contact_kb())
            return

        if call.data == "join:code":
            sessions.set(tg_id, "join:code", {})
            bot.send_message(call.message.chat.id, JOIN_PROMPT, parse_mode="HTML")

    @bot.message_handler(commands=["menu"])
    @safe
    def _menu(message):
        ctx.require()
        bot.send_message(
            message.chat.id,
            f"<b>{ui.escape(tenant.shop_name())}</b>",
            parse_mode="HTML",
            reply_markup=ui.main_menu(message.from_user.id),
        )

    @bot.message_handler(commands=["build"])
    @safe
    def _build(message):
        bot.send_message(message.chat.id, f"BUILD sha={config.BUILD_SHA}")

    # -------------------------------------------------------- sotuvchi paneli

    @bot.message_handler(commands=["saas"])
    @safe
    def _saas(message):
        if not users.is_seller(message.from_user.id):
            return
        rows = tenants.listing()
        if not rows:
            bot.send_message(message.chat.id, "Hali biznes yo'q.")
            return
        lines = [f"Jami biznes: {len(rows)}", ""]
        for r in rows[:30]:
            lines.append(
                f"#{r['id']} {r['shop_name'] or '(nomsiz)'} — "
                f"{r['state'] or '—'}/{r['plan'] or '—'} "
                f"gacha {r['expires_at'] or '—'}, {r['staff_count']} xodim"
            )
        lines.append("")
        lines.append(f"BUILD sha={config.BUILD_SHA}")
        for chunk in ui.chunks("\n".join(lines)):
            bot.send_message(message.chat.id, chunk)

    @bot.message_handler(commands=["set_license"])
    @safe
    def _set_license(message):
        if not users.is_seller(message.from_user.id):
            return
        parts = (message.text or "").split()
        if len(parts) < 3:
            bot.send_message(
                message.chat.id,
                "Ishlatilishi: /set_license <biznes_id> YYYY-MM-DD\n"
                "Biznes ro'yxati: /saas",
            )
            return
        try:
            tenant_id = int(parts[1])
        except ValueError:
            bot.send_message(message.chat.id, "Biznes ID raqam bo'lishi kerak.")
            return
        try:
            with ctx.scope(tenant_id):
                date = license.extend(parts[2])
                name = tenant.shop_name()
        except ValueError:
            bot.send_message(message.chat.id, "Sana formati: YYYY-MM-DD")
            return
        bot.send_message(
            message.chat.id, f"#{tenant_id} {name}: muddat {date} gacha."
        )
        for owner in tenants.owners_of(tenant_id):
            try:
                bot.send_message(owner, f"✅ Obuna {date} gacha uzaytirildi.")
            except Exception:  # noqa: BLE001
                log.warning("Egaga xabar ketmadi: %s", owner, exc_info=True)

    @bot.message_handler(commands=["new_client"])
    @safe
    def _new_client(message):
        if not users.is_seller(message.from_user.id):
            return
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) < 2:
            bot.send_message(
                message.chat.id,
                "Ishlatilishi: /new_client +998901234567 [do'kon nomi]")
            return
        name = parts[2] if len(parts) > 2 else None
        tenant_id, password = auth.create_account(parts[1], name=name)
        bot.send_message(
            message.chat.id,
            f"✅ Hisob ochildi — #{tenant_id}\n\n"
            f"Telefon: <code>{ui.escape(auth.normalize_phone(parts[1]))}</code>\n"
            f"Parol: <code>{ui.escape(password)}</code>\n\n"
            "Shu ikkisini mijozga bering. U birinchi kirishda parolni "
            "o'zgartirishi so'raladi.\n\n"
            f"Bito kalitini kiritish: <code>/set_bito {tenant_id} KALIT</code>",
            parse_mode="HTML")

    @bot.message_handler(commands=["reset_password"])
    @safe
    def _reset_password(message):
        if not users.is_seller(message.from_user.id):
            return
        parts = (message.text or "").split()
        if len(parts) < 2:
            bot.send_message(message.chat.id,
                             "Ishlatilishi: /reset_password <biznes_id>")
            return
        tenant_id = int(parts[1])
        password = auth.reset_password(tenant_id)
        bot.send_message(
            message.chat.id,
            f"#{tenant_id} uchun yangi parol: <code>{ui.escape(password)}</code>\n"
            "Mijoz birinchi kirishda uni o'zgartirishi so'raladi.",
            parse_mode="HTML")

    @bot.message_handler(commands=["set_key"])
    @safe
    def _set_key(message):
        """Litsenziya kalitini sotuvchi qo'yadi — mijoz kalitni ko'rmaydi."""
        if not users.is_seller(message.from_user.id):
            return
        parts = (message.text or "").split()
        if len(parts) < 3:
            bot.send_message(
                message.chat.id,
                "Ishlatilishi: /set_key <biznes_id> <kalit>\n\n"
                "O'chirish: /set_key <biznes_id> -")
            return
        try:
            tenant_id = int(parts[1])
        except ValueError:
            bot.send_message(message.chat.id, "Biznes ID raqam bo'lishi kerak.")
            return
        if not db.row("SELECT id FROM tenant WHERE id = ?", (tenant_id,)):
            bot.send_message(message.chat.id, f"#{tenant_id} topilmadi.")
            return

        key = parts[2]
        with ctx.scope(tenant_id):
            previous = license.record()["license_key"]
            if key == "-":
                license.clear_key()
                bot.send_message(
                    message.chat.id,
                    f"#{tenant_id}: kalit olib tashlandi, mahalliy hisobga "
                    "qaytdi.")
                return

            license.set_key(key)
            try:
                license.sync()
            except Exception:  # noqa: BLE001 — eski holatni tiklab, xatoni bermiz
                license.clear_key()
                if previous:
                    license.set_key(previous)
                raise

            if license.record()["remote_status"] == "invalid":
                license.clear_key()
                if previous:
                    license.set_key(previous)
                bot.send_message(
                    message.chat.id,
                    "⚠️ Server bu kalitni tanimadi. BMP'da tekshiring.")
                return

            summary = license.summary()
            enabled_keys = modules.list_enabled()
            name = tenant.shop_name()

        titles = [registry.BY_KEY[k].title for k in enabled_keys
                  if k in registry.BY_KEY]
        bot.send_message(
            message.chat.id,
            f"✅ #{tenant_id} {ui.escape(name)} — kalit o'rnatildi\n\n"
            f"{summary}\n\n"
            f"Modullar ({len(titles)}): "
            + (", ".join(titles) if titles else "yo'q"),
            parse_mode="HTML")
        bot.send_message(message.chat.id,
                         "Kalit yozilgan xabaringizni o'chirib tashlang.")

    @bot.message_handler(commands=["set_bito"])
    @safe
    def _set_bito(message):
        if not users.is_seller(message.from_user.id):
            return
        parts = (message.text or "").split()
        if len(parts) < 3:
            bot.send_message(message.chat.id,
                             "Ishlatilishi: /set_bito <biznes_id> <kalit>")
            return
        tenant_id, key = int(parts[1]), parts[2]
        bot.send_message(message.chat.id, "Kalit tekshirilmoqda…")
        from . import bito

        probe = bito.Bito(api_key=key)
        profile, scheme = probe.verify()
        with ctx.scope(tenant_id):
            tenant.set("bito_api_key", key)
            tenant.set("bito_auth_scheme", scheme)
            client = bito.client()
            orgs = client.organizations()
            if len(orgs) == 1:
                tenant.set("bito_org_id", orgs[0]["id"])
                tenant.set("bito_org_name", orgs[0].get("name"))
                warehouses = client.warehouses(organization_id=orgs[0]["id"])
                if len(warehouses) == 1:
                    tenant.set("warehouse_id", warehouses[0]["id"])
                    tenant.set("warehouse_name", warehouses[0].get("name"))
                prices = client.prices()
                chosen = bito.pick_default(prices, "is_main", "is_default")
                if chosen:
                    tenant.set("price_id", chosen["id"])
                    tenant.set("price_name", chosen.get("name"))
                    if chosen.get("currency_id"):
                        tenant.set("currency_id", chosen["currency_id"])
            missing = tenant.missing(modules.BITO_KEYS)
            shop = tenant.shop_name()

        company = profile.get("company_name") or profile.get("full_name") or ""
        text = (f"✅ #{tenant_id} {ui.escape(shop)} — Bito ulandi\n"
                f"Hisob: {ui.escape(str(company))}")
        if missing:
            text += ("\n\n⚠️ To'ldirilmagan: " + ", ".join(missing)
                     + "\nMijoz Sozlamalar → Bito ulanishi dan tanlaydi.")
        bot.send_message(message.chat.id, text, parse_mode="HTML")
        bot.send_message(
            message.chat.id,
            "Kalit yozilgan xabaringizni o'chirib tashlang.")

    @bot.message_handler(commands=["set_modules"])
    @safe
    def _set_modules(message):
        if not users.is_seller(message.from_user.id):
            return
        parts = (message.text or "").split()
        if len(parts) < 2:
            bot.send_message(
                message.chat.id,
                "Ishlatilishi: /set_modules <biznes_id> kalit,kalit,...\n\n"
                "Mavjud kalitlar:\n"
                + "\n".join(f"  {s.key} — {s.title}" for s in registry.CATALOG)
                + "\n\nHammasini o'chirish: /set_modules <biznes_id> -",
            )
            return
        try:
            tenant_id = int(parts[1])
        except ValueError:
            bot.send_message(message.chat.id, "Biznes ID raqam bo'lishi kerak.")
            return

        raw = parts[2] if len(parts) > 2 else "-"
        keys = [] if raw == "-" else [
            k.strip() for k in raw.replace(" ", ",").split(",") if k.strip()
        ]
        unknown = [k for k in keys if k not in registry.BY_KEY]
        if unknown:
            bot.send_message(
                message.chat.id, f"Noma'lum kalit: {', '.join(unknown)}"
            )
            return

        with ctx.scope(tenant_id):
            resolved = modules.set_enabled(keys)
            name = tenant.shop_name()
        added = [k for k in resolved if k not in keys]
        text = f"#{tenant_id} {name}: {len(resolved)} ta modul"
        if added:
            text += f"\nBog'liqligi uchun qo'shildi: {', '.join(added)}"
        text += "\n" + (", ".join(resolved) if resolved else "(bo'sh)")
        bot.send_message(message.chat.id, text)

        for owner in tenants.owners_of(tenant_id):
            try:
                bot.send_message(owner, "🔄 Modullaringiz yangilandi. /menu")
            except Exception:  # noqa: BLE001
                log.warning("Egaga xabar ketmadi: %s", owner, exc_info=True)

    @bot.message_handler(commands=["saas_msg"])
    @safe
    def _saas_msg(message):
        if not users.is_seller(message.from_user.id):
            return
        parts = (message.text or "").split(" ", 1)
        if len(parts) < 2:
            bot.send_message(message.chat.id, "Ishlatilishi: /saas_msg <matn>")
            return
        sent = 0
        for tenant_id in tenants.all_ids():
            for owner in tenants.owners_of(tenant_id):
                try:
                    bot.send_message(owner, f"📢 {parts[1]}")
                    sent += 1
                except Exception:  # noqa: BLE001
                    log.warning("E'lon yuborilmadi: %s", owner, exc_info=True)
        bot.send_message(message.chat.id, f"Yuborildi: {sent} ta egaga")

    # -------------------------------------------------------- sehrgar tugmasi

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("setup:"))
    @safe
    def _setup_click(call):
        ui.ack(bot, call)
        ctx.require()
        onboarding.handle_callback(bot, call)

    # ---------------------------------------------------------- menyu tugmasi

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("menu:"))
    @safe
    def _menu_click(call):
        ui.ack(bot, call)
        ctx.require()
        section = call.data.split(":", 1)[1]
        license.require_active(section)

        if section == "obuna":
            _subscription(call)
            return
        if section == "yordam":
            bot.send_message(
                call.message.chat.id,
                "Savol bo'lsa do'kon egasiga yoki sotuvchiga yozing.",
            )
            return
        if section == "sozlamalar":
            settings_ui.panel(bot, call.message.chat.id, call.from_user.id)
            return
        if section == "jamoa":
            _staff_panel(call)
            return

        bot.send_message(
            call.message.chat.id,
            f"«{section}» bo'limi keyingi bosqichda ochiladi.",
            reply_markup=ui.main_menu(call.from_user.id),
        )

    # Modul handlerlari: `mod:<kalit>:...` — har biri guard orqali o'tadi
    def guard(module_key):
        """Modul handlerini o'raydi: yoqilganini tekshiradi."""

        def decorator(fn):
            @functools.wraps(fn)
            def wrapper(obj, *args, **kwargs):
                modules.require(module_key)
                return fn(obj, *args, **kwargs)

            return safe(wrapper)

        return decorator

    settings_ui.register(bot, safe)

    for _spec in registry.implemented():
        try:
            _spec.impl.register(bot, guard(_spec.key))
        except Exception:  # noqa: BLE001
            log.exception("Modul handlerlari biriktirilmadi: %s", _spec.key)

    def _subscription(call):
        rec = license.record()
        lines = [license.summary()]
        if rec["license_key"]:
            lines.append("")
            lines.append("Manba: markaziy litsenziya")
            if rec["checked_at"]:
                lines.append(f"Oxirgi tekshiruv: {rec['checked_at']} UTC")
            if rec["offline_since"]:
                lines.append("⚠️ Markaz bilan aloqa yo'q — oxirgi ma'lum "
                             "holat bo'yicha ishlayapti.")
        else:
            lines.append("")
            lines.append("Litsenziya kaliti kiritilmagan — sinov muddati.")

        lines.append("")
        lines.append("<b>Modullar</b>")
        waiting_bito = False
        for spec, on, ready, waits in modules.catalog_status():
            if waits:
                mark = "⚠️"      # to'langan, lekin Bito ulanmagan
                waiting_bito = True
            elif on and ready:
                mark = "✅"
            elif on:
                mark = "🔧"      # yoqilgan, lekin hali yozilmagan
            else:
                mark = "▫️"
            lines.append(f"{mark} {spec.title} — {ui.escape(spec.summary)}")
        if waiting_bito:
            lines.append("")
            lines.append("⚠️ — modul to'langan, lekin Bito hisobi ulanmagan. "
                         "Sozlamalardan kalitni kiriting.")
        lines.append("")
        lines.append("Qo'shimcha modul kerak bo'lsa: @ulugbekbekbergenovbmp")

        buttons = []
        if users.role_of(call.from_user.id) == "owner":
            buttons.append(
                ("🔑 Kalitni kiritish" if not rec["license_key"]
                 else "🔑 Kalitni almashtirish", "lic:key")
            )
            if rec["license_key"]:
                buttons.append(("🔄 Hozir tekshirish", "lic:sync"))
        for chunk in ui.chunks("\n".join(lines)):
            bot.send_message(
                call.message.chat.id, chunk, parse_mode="HTML",
                reply_markup=ui.buttons(buttons, row_width=1, back="menu:root")
                if buttons else None,
            )

    @bot.callback_query_handler(func=lambda c: (c.data or "").startswith("lic:"))
    @safe
    def _license_click(call):
        ui.ack(bot, call)
        users.require_role(call.from_user.id, "owner")

        if call.data == "lic:key":
            sessions.set(call.from_user.id, "lic:key", {})
            bot.send_message(
                call.message.chat.id,
                "Litsenziya kalitini yuboring.\n"
                "Kalitni sotuvchi beradi — <code>GB-</code> bilan boshlanadi.",
                parse_mode="HTML",
            )
            return

        if call.data == "lic:sync":
            state, notice = license.sync()
            text = f"Tekshirildi.\n\n{license.summary()}"
            if notice:
                text += f"\n\nℹ️ {notice['text']}"
            bot.send_message(call.message.chat.id, text)

    def _staff_panel(call):
        users.require_role(call.from_user.id, "manager")
        rows = users.listing()
        me = bot.get_me()
        code = tenants.invite_code()
        link = f"https://t.me/{me.username}?start={code}"
        lines = [f"<b>Jamoa</b> — {len(rows)} kishi", ""]
        role_names = {"owner": "egasi", "manager": "menejer", "staff": "xodim"}
        for u in rows:
            lines.append(
                f"• {ui.escape(u['name'] or '—')} — {role_names.get(u['role'], u['role'])}"
            )
        lines += [
            "",
            f"Taklif kodi: <code>{code}</code>",
            f"Havola: {link}",
            "",
            "Kod tarqab ketsa yangilang — eskisi ishlamay qoladi.",
        ]
        bot.send_message(
            call.message.chat.id,
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=ui.buttons(
                [("🔄 Kodni yangilash", "staff:rotate")], back="menu:root"
            ),
        )

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "staff:rotate")
    @safe
    def _rotate(call):
        ui.ack(bot, call)
        users.require_role(call.from_user.id, "owner")
        code = tenants.rotate_code()
        bot.send_message(
            call.message.chat.id,
            f"Yangi taklif kodi: <code>{code}</code>\nEski kod bekor qilindi.",
            parse_mode="HTML",
        )

    @bot.callback_query_handler(func=lambda c: (c.data or "") == "menu:root")
    @safe
    def _root(call):
        ui.ack(bot, call)
        bot.send_message(
            call.message.chat.id,
            f"<b>{ui.escape(tenant.shop_name())}</b>",
            parse_mode="HTML",
            reply_markup=ui.main_menu(call.from_user.id),
        )

    # ------------------------------------------------------------- erkin matn

    @bot.message_handler(content_types=["text"])
    @safe
    def _text(message):
        if _seen(message):
            return
        tg_id = message.from_user.id
        state, _ = sessions.get_global(tg_id)

        if state == "auth:telefon":
            sessions.set(tg_id, "auth:parol", {"phone": message.text or ""})
            bot.send_message(
                message.chat.id,
                "Endi parolni yuboring.\n\n"
                "⚠️ Yuborgach xabaringizni o'chirib tashlang — parol "
                "Telegram tarixida qolib ketmasin.")
            return

        if state == "auth:parol":
            _do_login(message, sessions.get_global(tg_id)[1].get("phone"))
            return

        if state == "auth:yangi_parol":
            _change_password(message)
            return

        if state == "join:code":
            _do_join(message, message.text or "")
            return

        if state == "lic:key":
            _save_license_key(message)
            return

        if state == "baho:izoh":
            _save_feedback(message)
            return

        if state == "hr:suhbat":
            data = sessions.get_global(tg_id)[1]
            _interview_step(message.chat.id, tg_id,
                            data.get("tenant_id") or ctx.current(),
                            data["job_id"], message.text)
            return

        if ctx.current() is None:
            bot.send_message(message.chat.id, "Boshlash uchun /start bosing.")
            return

        if onboarding.handle_text(bot, message):
            return
        if state:
            return
        bot.send_message(
            message.chat.id,
            "Menyudan tanlang:",
            reply_markup=ui.main_menu(tg_id),
        )

    def _save_feedback(message):
        from .modules import mijoz

        tg_id = message.from_user.id
        data = sessions.get_global(tg_id)[1]
        tenant_id = data.get("tenant_id")
        text = (message.text or message.caption or "").strip()
        photo = (message.photo[-1].file_id
                 if message.content_type == "photo" else None)
        sessions.clear(tg_id)

        with ctx.scope(tenant_id):
            row = mijoz.get(data["feedback_id"])
            kind = "shikoyat" if (row and row["stars"]
                                  and row["stars"] < mijoz.ALERT_BELOW) \
                else "taklif"
            mijoz.update(data["feedback_id"], text=text or None,
                         photo_id=photo, kind=kind if text or photo else "baho")
            targets = [u["tg_id"] for u in users.listing()
                       if u["role"] in ("owner", "manager")]
            shop = tenant.shop_name()
            summary = mijoz.summary_text(mijoz.get(data["feedback_id"]))

        bot.send_message(message.chat.id,
                         "Rahmat! Fikringiz do'kon egasiga yetkazildi.")
        for target in targets:
            try:
                bot.send_message(target, f"💬 {ui.escape(shop)} — yangi fikr:\n\n"
                                         f"{summary}", parse_mode="HTML")
            except Exception:  # noqa: BLE001
                log.warning("Fikr yetkazilmadi: %s", target, exc_info=True)

    def _save_license_key(message):
        users.require_role(message.from_user.id, "owner")
        key = (message.text or "").strip()
        if len(key) < 6:
            bot.send_message(message.chat.id, "Bu kalitga o'xshamaydi. Qaytadan yuboring.")
            return
        previous = license.record()["license_key"]
        license.set_key(key)
        try:
            state, notice = license.sync()
        except Exception:  # noqa: BLE001
            license.clear_key()
            if previous:
                license.set_key(previous)
            raise

        if license.record()["remote_status"] == "invalid":
            license.clear_key()
            if previous:
                license.set_key(previous)
            bot.send_message(
                message.chat.id,
                "⚠️ Bunday kalit topilmadi. Sotuvchidan qayta so'rang.",
            )
            return

        sessions.clear(message.from_user.id)
        text = f"✅ Kalit qabul qilindi.\n\n{license.summary()}"
        if notice:
            text += f"\n\nℹ️ {notice['text']}"
        bot.send_message(message.chat.id, text,
                         reply_markup=ui.main_menu(message.from_user.id))

    @bot.message_handler(content_types=["contact"])
    @safe
    def _contact(message):
        """Kontakt — kirish yoki BMP orqali avto ochish.

        Telegram kontaktdagi user_id ni o'zi tasdiqlaydi, shuning uchun
        faqat shu yo'l bilan kelgan raqamga ishonamiz. Yozilgan raqam
        bilan avto ochish yo'q — birovning raqamini bilish kifoya bo'lardi.
        """
        if _seen(message):
            return
        tg_id = message.from_user.id
        if ctx.current() is not None:
            bot.send_message(message.chat.id, "Siz allaqachon bir biznesdasiz.",
                             reply_markup=ui.kb_remove())
            return

        contact = message.contact
        if not contact or (contact.user_id or 0) != tg_id:
            bot.send_message(
                message.chat.id,
                "Faqat o'z raqamingiz qabul qilinadi — pastdagi tugma orqali "
                "yuboring.",
                reply_markup=ui.contact_kb())
            return

        phone = contact.phone_number or ""
        account = auth.by_phone(phone)
        if account:
            # Hisob bor — odatdagidek parol bilan kiradi
            sessions.set(tg_id, "auth:parol", {"phone": phone})
            bot.send_message(
                message.chat.id,
                "Raqam tasdiqlandi. Endi parolni yuboring.\n\n"
                "⚠️ Yuborgach xabaringizni o'chirib tashlang — parol "
                "Telegram tarixida qolib ketmasin.",
                reply_markup=ui.kb_remove())
            return

        if not licsrv.provision_enabled():
            bot.send_message(
                message.chat.id,
                "Bu raqam uchun hisob topilmadi.\n"
                "Sotuvchi bilan bog'laning: @ulugbekbekbergenovbmp",
                reply_markup=ui.kb_remove())
            return

        bot.send_message(message.chat.id, "Tekshirilmoqda…",
                         reply_markup=ui.kb_remove())
        try:
            got = auth.provision_from_bmp(phone, tg_id)
        except licsrv.Unreachable:
            log.warning("Provision: markaz javob bermadi", exc_info=True)
            bot.send_message(
                message.chat.id,
                "Markaz bilan hozircha aloqa yo'q. Birozdan keyin qayta "
                "urining yoki sotuvchiga yozing: @ulugbekbekbergenovbmp")
            return

        if not got:
            bot.send_message(
                message.chat.id,
                "Bu raqamga obuna topilmadi.\n"
                "Ro'yxatdan o'tish uchun sotuvchiga yozing: "
                "@ulugbekbekbergenovbmp")
            return

        tenant_id, name = got
        ctx.set(tenant_id)
        sessions.set(tg_id, "auth:yangi_parol", {})
        bot.send_message(
            message.chat.id,
            f"✅ Xush kelibsiz: <b>{ui.escape(name or tenant.shop_name())}</b>\n"
            "Hisobingiz tayyor.\n\n"
            f"Endi o'zingizga parol o'ylang va yuboring (kamida "
            f"{auth.MIN_LENGTH} ta belgi) — keyingi safar shu parol bilan "
            "kirasiz.",
            parse_mode="HTML")

    @bot.message_handler(content_types=["photo", "document", "sticker"])
    @safe
    def _media(message):
        if _seen(message):
            return
        if sessions.get_global(message.from_user.id)[0] == "baho:izoh":
            _save_feedback(message)
            return
        ctx.require()
        bot.send_message(
            message.chat.id,
            "Rasm va hujjat qabul qilish nakladnoy bosqichida ishga tushadi.",
        )
