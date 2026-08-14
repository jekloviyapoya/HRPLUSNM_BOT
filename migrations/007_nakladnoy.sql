-- 007_nakladnoy.sql — hujjat o'qish va tekshirish
--
-- Hujjat qayta ishlanishi uzoq davom etadi (AI 30–60 soniya) va
-- foydalanuvchi natijani bir necha marta tahrirlaydi. Xotirada saqlansa,
-- deploy paytida ish yo'qoladi — shuning uchun bazada.

CREATE TABLE IF NOT EXISTS nak_doc (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id     INTEGER NOT NULL,
  tg_id         INTEGER NOT NULL,
  status        TEXT NOT NULL DEFAULT 'oqilmoqda'
                CHECK (status IN ('oqilmoqda', 'tekshirilmoqda', 'moslashtirilmoqda',
                                  'yuklandi', 'bekor', 'xato')),
  source        TEXT,              -- photo | pdf | excel | text
  file_id       TEXT,              -- Telegram file_id
  supplier_name TEXT,              -- hujjatdan o'qilgani
  supplier_id   TEXT,              -- Bito'dagi mos keluvchi
  doc_number    TEXT,
  doc_date      TEXT,
  doc_total     REAL,              -- hujjatda yozilgan jami
  error         TEXT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_nak_doc_user
  ON nak_doc (tenant_id, tg_id, created_at DESC);

-- Qatorlar.
--
-- INVARIANT (market-bot 2026-08-02 xatosidan): qty — BLOK soni,
-- price — BITTA DONA narxi. Jami har joyda qty * block_size * price.
-- Ilgari bu buzilib, Bito'ga olti barobar ortiq yuklangan edi.
CREATE TABLE IF NOT EXISTS nak_item (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id    INTEGER NOT NULL,
  doc_id       INTEGER NOT NULL,
  position     INTEGER NOT NULL DEFAULT 0,
  raw_name     TEXT NOT NULL,
  qty          REAL NOT NULL DEFAULT 0,      -- blok soni
  qty_unit     TEXT,                          -- 'бл', 'kor', 'dona'
  block_size   INTEGER NOT NULL DEFAULT 1,    -- 1 blokdagi dona
  price        REAL NOT NULL DEFAULT 0,       -- 1 DONA narxi
  doc_total    REAL,                          -- hujjatdagi qator jamisi
  barcode      TEXT,
  product_id   TEXT,                          -- Bito'dagi mos mahsulot
  product_name TEXT,
  match_state  TEXT NOT NULL DEFAULT 'yoq'
               CHECK (match_state IN ('yoq', 'topildi', 'yangi', 'tashlab')),
  note         TEXT
);
CREATE INDEX IF NOT EXISTS ix_nak_item_doc ON nak_item (tenant_id, doc_id, position);

-- Firma jadval tuzilishi xotirasi.
-- Har firmaning ustunlari bir marta o'rganilib, keyingi hujjatlarda
-- AI'ga eslatma sifatida beriladi — aniqlikni sezilarli oshiradi.
CREATE TABLE IF NOT EXISTS nak_hint (
  tenant_id   INTEGER NOT NULL,
  supplier    TEXT NOT NULL,
  hint        TEXT NOT NULL,
  used_count  INTEGER NOT NULL DEFAULT 1,
  updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (tenant_id, supplier)
);
