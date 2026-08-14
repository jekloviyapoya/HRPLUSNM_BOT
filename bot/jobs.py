"""Fon ishlari: obuna eslatmalari va tozalash.

Har thread try/except ichida — biri yiqilsa qolganlari ishlashda davom etadi.
"""

import logging
import threading
import time

from . import config, ctx, db, license, modules, tenant, tenants
from .modules import registry

log = logging.getLogger(__name__)

CHECK_INTERVAL = max(60, config.LICENSE_CHECK_MINUTES * 60)


def _sync_remote(bot, tenant_id):
    """Markazdan holatni oladi va mijozga xabarni yetkazadi."""
    with ctx.scope(tenant_id):
        if not license.key():
            return
        was_locked = license.is_locked()
        now, notice = license.sync()
        warning = license.offline_warning()
        name = tenant.shop_name()

    if notice:
        prefix = {"critical": "🔴", "warning": "⚠️", "info": "ℹ️"}.get(
            notice["level"], "ℹ️")
        for owner in tenants.owners_of(tenant_id):
            try:
                bot.send_message(owner, f"{prefix} {notice['text']}")
            except Exception:  # noqa: BLE001
                log.warning("Xabar yetkazilmadi: %s", owner, exc_info=True)

    if now == "locked" and not was_locked:
        for owner in tenants.owners_of(tenant_id):
            try:
                bot.send_message(
                    owner,
                    "Obuna to'xtatildi. Ma'lumotlaringiz saqlanib turibdi — "
                    "to'lovdan keyin hammasi joyida qoladi.",
                )
            except Exception:  # noqa: BLE001
                log.warning("Qulflash xabari ketmadi: %s", owner, exc_info=True)

    if warning and config.SAAS_OWNER_ID:
        try:
            bot.send_message(config.SAAS_OWNER_ID, f"#{tenant_id} {name}\n{warning}")
        except Exception:  # noqa: BLE001
            log.warning("Sotuvchiga ogohlantirish ketmadi", exc_info=True)


_last_run = {}


def _module_jobs(bot):
    """Modullarning fon ishlari — faqat yoqilgan biznesda."""
    now = time.time()
    for spec in registry.implemented():
        try:
            declared = spec.impl.jobs() or []
        except Exception:  # noqa: BLE001
            log.exception("Modul ishlari o'qilmadi: %s", spec.key)
            continue
        for name, fn, interval in declared:
            for tenant_id in modules.tenants_with(spec.key):
                key = (name, tenant_id)
                if now - _last_run.get(key, 0) < interval:
                    continue
                _last_run[key] = now
                try:
                    with ctx.scope(tenant_id):
                        if "bito" in spec.requires and not modules.bito_ready():
                            continue
                        fn()
                    log.info("Fon ishi bajarildi: %s tenant=%s", name, tenant_id)
                except Exception:  # noqa: BLE001 — bittasi qolganini to'xtatmasin
                    log.exception("Fon ishi yiqildi: %s tenant=%s",
                                  name, tenant_id)


def _tick(bot):
    """Har biznes uchun obuna holatini tekshiradi."""
    for tenant_id in tenants.all_ids():
        try:
            _sync_remote(bot, tenant_id)
        except Exception:  # noqa: BLE001
            log.exception("Markaziy tekshiruv yiqildi: tenant=%s", tenant_id)

    for tenant_id in tenants.all_ids():
        try:
            with ctx.scope(tenant_id):
                text = license.due_reminder()
                if not text:
                    continue
                name = tenant.shop_name()
                left = license.days_left()
                summary = license.summary()
            for owner in tenants.owners_of(tenant_id):
                try:
                    bot.send_message(owner, text)
                except Exception:  # noqa: BLE001
                    log.warning("Eslatma yuborilmadi: %s", owner, exc_info=True)
            if config.SAAS_OWNER_ID and left <= 3:
                try:
                    bot.send_message(
                        config.SAAS_OWNER_ID,
                        f"#{tenant_id} {name}\n{summary}",
                    )
                except Exception:  # noqa: BLE001
                    log.warning("Sotuvchiga xabar ketmadi", exc_info=True)
        except Exception:  # noqa: BLE001
            log.exception("Obuna tekshiruvi yiqildi: tenant=%s", tenant_id)

    _module_jobs(bot)
    db.prune()


def _loop(bot):
    while True:
        try:
            _tick(bot)
        except Exception:  # noqa: BLE001
            log.exception("jobs._tick yiqildi")
        time.sleep(CHECK_INTERVAL)


def start(bot):
    t = threading.Thread(target=_loop, args=(bot,), daemon=True, name="jobs")
    t.start()
    log.info("Fon ishlari ishga tushdi")
    return t
