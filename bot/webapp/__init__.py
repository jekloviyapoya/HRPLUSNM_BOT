"""Flask webapp.

Muhim: HTML/CSS/JS hech qachon Python satri ichida bo'lmaydi. Hammasi
templates/ va static/ ichida alohida fayl. Eski botda satr ichidagi HTML
`\\'` va `\\n` sabab siniq JavaScript berardi va bu faqat foydalanuvchi
ekranida ko'rinardi.
"""

import logging

from flask import Flask, jsonify, render_template

from .. import config, db, license, tenant

log = logging.getLogger(__name__)


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["SECRET_KEY"] = config.WEBAPP_SECRET

    @app.get("/health")
    def health():
        try:
            db.value("SELECT 1")
            ok = True
        except Exception:  # noqa: BLE001
            log.exception("Health: baza javob bermadi")
            ok = False
        return jsonify(ok=ok, build=config.BUILD_SHA), (200 if ok else 503)

    @app.get("/")
    def status():
        return render_template(
            "status.html",
            build=config.BUILD_SHA,
            shop=tenant.shop_name(),
            setup_done=tenant.setup_done(),
            plan=license.plan(),
            state=license.state(),
            expires=license.record()["expires_at"],
        )

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", code=404,
                               message="Bunday sahifa yo'q."), 404

    @app.errorhandler(500)
    def server_error(_e):
        log.exception("Webapp 500")
        return render_template("error.html", code=500,
                               message="Server xatosi. Log yozildi."), 500

    return app
