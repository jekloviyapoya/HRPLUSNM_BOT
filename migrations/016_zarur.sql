-- 016_zarur.sql — zarur mahsulotlar ro'yxati (market-bot tengligi)
--
-- Jamoaviy «tugayapti» ro'yxati: xodim ham qo'shadi. product_id bo'lsa
-- Bito kuzatiladi va mahsulot kelganda qator o'zi o'chadi; NULL bo'lsa
-- faqat ma'lumot.
--
-- baseline: qo'shilganda EMAS, birinchi tekshiruvda joriy qoldiq
-- yoziladi — eski qoldiq «keldi» deb adashtirmasin (market-bot qoidasi).

CREATE TABLE IF NOT EXISTS zarur (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id    INTEGER NOT NULL,
  product_id   TEXT,
  name         TEXT NOT NULL,
  stars        INTEGER NOT NULL DEFAULT 3,
  expected     TEXT,
  added_by     INTEGER NOT NULL,
  baseline     REAL,
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_zarur ON zarur (tenant_id, stars DESC, id);
