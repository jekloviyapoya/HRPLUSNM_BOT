"""Fon ishlari: obuna eslatmalari va tozalash.

Har thread try/except ichida — biri yiqilsa qolganlari ishlashda davom etadi.
"""

import logging
import threading
import time

from . import config, db, license, users

log = logging.getLogger(__name__)

CHECK_INTERVAL = 60 * 60  # soatiga bir marta


def _owners():
    return [u["tg_id"] for u in users.listing() if u["role"] == "owner"]


def _tick(bot):
    text = license.due_reminder()
    if text:
        for tg_id in _owners():
            try:
                bot.send_message(tg_id, text)
            except Exception:  # noqa: BLE001
                log.warning("Eslatma yuborilmadi: %s", tg_id, exc_info=True)

        if config.SAAS_OWNER_ID and license.days_left() <= 3:
            try:
                bot.send_message(
                    config.SAAS_OWNER_ID,
                    f"Mijoz obunasi: {license.summary()}",
                )
            except Exception:  # noqa: BLE001
                log.warning("Sotuvchiga xabar ketmadi", exc_info=True)

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
