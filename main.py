"""HRPLUSNM_BOT — ishga tushirish.

Ikki thread: Flask (webapp, Railway health uchun) va telebot polling.
Ikkisi ham yiqilsa jarayon tugaydi va Railway qayta ishga tushiradi.
"""

import logging
import sys
import threading

import telebot
from waitress import serve

from bot import config, db, handlers, jobs
from bot.webapp import create_app

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
log = logging.getLogger("main")


def _serve_web():
    app = create_app()
    log.info("Webapp: 0.0.0.0:%s", config.PORT)
    serve(app, host="0.0.0.0", port=config.PORT, threads=8)


def main():
    log.info("BUILD sha=%s", config.BUILD_SHA)

    missing = config.missing_required()
    if missing:
        log.error("Env o'zgaruvchilar yetishmayapti: %s", ", ".join(missing))
        sys.exit(1)

    applied = db.migrate()
    log.info("Migratsiyalar: %s", applied or "yangisi yo'q")
    threading.Thread(target=_serve_web, daemon=True, name="web").start()

    telebot.apihelper.RETRY_ON_ERROR = True
    bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN, threaded=True)
    handlers.register(bot)
    jobs.start(bot)

    log.info("Polling boshlandi")
    bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30)


if __name__ == "__main__":
    main()
