-- 011_inventarizatsiya.sql — telefonda sanash
--
-- Sanash MAHALLIY olib boriladi. Bito'ga faqat oxirida, aniq tasdiqdan
-- keyin yoziladi. Sabab: Bito'da `done` holati qoldiqni qaytarib
-- bo'lmaydigan tarzda o'zgartiradi. Yarim sanalgan ro'yxat yuborilsa,
-- sanalmagan mahsulotlar nolga tushib qoladi.
--
-- Sanash bir necha soat davom etishi mumkin (katta do'konda kun bo'yi),
-- shuning uchun bazada — deployda yo'qolmasin.

CREATE TABLE IF NOT EXISTS stock_take (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id    INTEGER NOT NULL,
  started_by   INTEGER NOT NULL,
  title        TEXT,
  status       TEXT NOT NULL DEFAULT 'sanalmoqda'
               CHECK (status IN ('sanalmoqda', 'yakunlandi', 'yuklandi',
                                 'bekor')),
  bito_id      TEXT,              -- Bito revision _id
  bito_number  TEXT,
  error        TEXT,
  created_at   TEXT NOT NULL DEFAULT (datetime('now')),
  finished_at  TEXT
);
CREATE INDEX IF NOT EXISTS ix_take_tenant
  ON stock_take (tenant_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS stock_take_item (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id    INTEGER NOT NULL,
  take_id      INTEGER NOT NULL,
  product_id   TEXT NOT NULL,
  name         TEXT,
  measure      TEXT,
  expected     REAL NOT NULL DEFAULT 0,   -- katalogdagi qoldiq
  counted      REAL NOT NULL DEFAULT 0,   -- sanalgan
  counted_by   INTEGER,
  updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_take_item
  ON stock_take_item (tenant_id, take_id, product_id);
