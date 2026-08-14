-- 015_login.sql — sotuvchi tomonidan mijoz ochish
--
-- O'zgargan model: mijoz o'zi biznes ocholmaydi. Sotuvchi hisob yaratadi,
-- telefon va parol beradi, Bito kalitini o'zi kiritadi. Mijoz botga kirib
-- telefon + parol bilan o'z biznesiga bog'lanadi.
--
-- Parol XESHLANGAN holda saqlanadi. Ochiq matnda hech qayerda yozilmaydi.

ALTER TABLE tenant ADD COLUMN phone TEXT;
ALTER TABLE tenant ADD COLUMN password_hash TEXT;
ALTER TABLE tenant ADD COLUMN must_change INTEGER NOT NULL DEFAULT 1;

CREATE UNIQUE INDEX IF NOT EXISTS ux_tenant_phone ON tenant (phone);

-- Parol tanlashga urinishlarni cheklash
CREATE TABLE IF NOT EXISTS login_try (
  tg_id       INTEGER PRIMARY KEY,
  fails       INTEGER NOT NULL DEFAULT 0,
  blocked_at  TEXT,
  updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
