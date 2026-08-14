-- 014_mijoz.sql — mijoz baholari, takliflar va shikoyatlar
--
-- Mijoz — nomzod kabi, tenant foydalanuvchisi EMAS. U QR kod orqali
-- kiradi, baho qoldiradi va ketadi. `users` jadvaliga yozilmaydi.
--
-- Baho anonim: mijoz ismini so'ramaymiz. Faqat aloqa qoldirmoqchi
-- bo'lsa telefonini o'zi yozadi.

CREATE TABLE IF NOT EXISTS feedback (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id   INTEGER NOT NULL,
  tg_id       INTEGER,
  kind        TEXT NOT NULL DEFAULT 'baho'
              CHECK (kind IN ('baho', 'taklif', 'shikoyat')),
  stars       INTEGER CHECK (stars BETWEEN 1 AND 5),
  text        TEXT,
  photo_id    TEXT,
  phone       TEXT,
  employee_id INTEGER,            -- kimga tegishli (ixtiyoriy)
  status      TEXT NOT NULL DEFAULT 'yangi'
              CHECK (status IN ('yangi', 'korildi', 'hal_qilindi')),
  answered_by INTEGER,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_feedback_new
  ON feedback (tenant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_feedback_stars
  ON feedback (tenant_id, stars);
