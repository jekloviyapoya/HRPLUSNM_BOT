"""Fon ishlari: obuna eslatmalari va tozalash.

Har thread try/except ichida — biri yiqilsa qolganlari ishlashda davom etadi.
"""

import logging
import threading
import time

from . import config, ctx, db, license, tenant, tenants

log = logging.getLogger(__name__)

CHECK_INTERVAL = 60 * 60  # soatiga bir marta


def _tick(bot):
    """Har biznes uchun obuna holatini tekshiradi."""
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
