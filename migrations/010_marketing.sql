-- 010_marketing.sql — aksiya postlari
--
-- Post bir necha bosqichda tuziladi (mahsulot → narx → matn → rasm) va
-- foydalanuvchi orasida chalg'ishi mumkin. Xotirada saqlansa deployda
-- yo'qoladi — shuning uchun bazada.

CREATE TABLE IF NOT EXISTS promo (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id    INTEGER NOT NULL,
  tg_id        INTEGER NOT NULL,
  product_id   TEXT,
  product_name TEXT,
  old_price    REAL,
  new_price    REAL,
  post_text    TEXT,
  photo_id     TEXT,              -- Telegram file_id (foydalanuvchi yuborgan)
  poster_id    TEXT,              -- AI yasagan poster
  status       TEXT NOT NULL DEFAULT 'tuzilmoqda'
               CHECK (status IN ('tuzilmoqda', 'tayyor', 'yuborildi', 'bekor')),
  channel_id   TEXT,
  message_id   INTEGER,
  created_at   TEXT NOT NULL DEFAULT (datetime('now')),
  sent_at      TEXT
);
CREATE INDEX IF NOT EXISTS ix_promo_user
  ON promo (tenant_id, tg_id, created_at DESC);
