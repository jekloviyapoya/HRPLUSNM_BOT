-- 008_catalog.sql — mahsulot katalogi keshi
--
-- Nakladnoy qatorlarini Bito katalogiga moslashtirish uchun butun katalog
-- kerak. Har qator uchun alohida qidiruv yuborish — 50 qatorli hujjatda
-- 50 ta so'rov, ya'ni bir necha daqiqa.
--
-- Ombor skaneri allaqachon hamma sahifani varaqlab o'tadi. Shuning uchun
-- bitta o'tishda ikkala natija yoziladi: kam qolganlar (stock_item) va
-- to'liq katalog (catalog).
--
-- `key` — moslashtirish uchun normallashtirilgan nom: kichik harf,
-- faqat harf va raqam. Indeks shu ustunda.

CREATE TABLE IF NOT EXISTS catalog (
  tenant_id   INTEGER NOT NULL,
  product_id  TEXT NOT NULL,
  name        TEXT NOT NULL,
  key         TEXT NOT NULL,
  sku         TEXT,
  barcodes    TEXT,               -- vergul bilan ajratilgan
  measure     TEXT,
  measure_id  TEXT,
  category    TEXT,
  amount      REAL NOT NULL DEFAULT 0,
  updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (tenant_id, product_id)
);
CREATE INDEX IF NOT EXISTS ix_catalog_key ON catalog (tenant_id, key);
CREATE INDEX IF NOT EXISTS ix_catalog_sku ON catalog (tenant_id, sku);

-- Moslashtirish xotirasi: foydalanuvchi bir marta tanlagan mos kelish
-- keyingi nakladnoylarda avtomatik qo'llanadi.
CREATE TABLE IF NOT EXISTS nak_alias (
  tenant_id   INTEGER NOT NULL,
  key         TEXT NOT NULL,      -- nakladnoydagi nom, normallashtirilgan
  product_id  TEXT NOT NULL,
  product_name TEXT,
  used_count  INTEGER NOT NULL DEFAULT 1,
  updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (tenant_id, key)
);
