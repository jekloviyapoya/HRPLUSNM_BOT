-- 012_ombor_ai.sql — sotuv tezligi keshi
--
-- Sotuv hisoboti sahifalab olinadi va mahalliy saqlanadi. Har savolda
-- qayta so'ralsa, bot bir necha daqiqa jim turardi.
--
-- MUHIM: bu jadvalda faqat SOTILGAN mahsulotlar bo'ladi. Bito'ning
-- sales/by-item hisoboti sotilmaganlarni umuman ko'rsatmaydi. «Turib
-- qolganlar» ro'yxati katalogdan shu jadvalni AYIRIB olinadi.

CREATE TABLE IF NOT EXISTS sales_stat (
  tenant_id   INTEGER NOT NULL,
  product_id  TEXT NOT NULL,
  name        TEXT,
  qty         REAL NOT NULL DEFAULT 0,      -- davr ichida sotilgan
  revenue     REAL NOT NULL DEFAULT 0,
  days        INTEGER NOT NULL DEFAULT 30,
  updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (tenant_id, product_id)
);
CREATE INDEX IF NOT EXISTS ix_sales_qty ON sales_stat (tenant_id, qty DESC);

CREATE TABLE IF NOT EXISTS sales_scan (
  tenant_id    INTEGER PRIMARY KEY,
  days         INTEGER NOT NULL DEFAULT 30,
  finished_at  TEXT,
  total_items  INTEGER NOT NULL DEFAULT 0,
  error        TEXT
);
