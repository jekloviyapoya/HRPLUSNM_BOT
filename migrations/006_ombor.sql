-- 006_ombor.sql — qoldiq keshi
--
-- Nima uchun kesh kerak: Bito'da 10 000+ mahsulot bo'lishi mumkin, sahifa
-- hajmi 200. «Kam qolganlar» ro'yxati uchun 50+ so'rov kerak — bot javobi
-- uchun juda sekin. Shuning uchun fonda skanerlanadi, bot keshdan o'qiydi.
--
-- Keshda FAQAT chegaradan pastdagilar saqlanadi. Qidiruv esa jonli —
-- to'g'ridan-to'g'ri Bito'ga boradi, chunki u bitta so'rov bilan bajariladi.

CREATE TABLE IF NOT EXISTS stock_scan (
  tenant_id      INTEGER PRIMARY KEY,
  started_at     TEXT,
  finished_at    TEXT,
  total_products INTEGER,
  low_count      INTEGER NOT NULL DEFAULT 0,
  out_count      INTEGER NOT NULL DEFAULT 0,
  pages_done     INTEGER NOT NULL DEFAULT 0,
  error          TEXT
);

CREATE TABLE IF NOT EXISTS stock_item (
  tenant_id   INTEGER NOT NULL,
  product_id  TEXT NOT NULL,
  name        TEXT,
  sku         TEXT,
  category    TEXT,
  measure     TEXT,
  amount      REAL NOT NULL DEFAULT 0,
  threshold   REAL,
  status      TEXT NOT NULL CHECK (status IN ('tugagan', 'kam')),
  updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (tenant_id, product_id)
);
CREATE INDEX IF NOT EXISTS ix_stock_status
  ON stock_item (tenant_id, status, amount);
