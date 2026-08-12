-- 001_init.sql — poydevor sxemasi
-- tenant_id hamma joyda bor va hozircha doim 1. Keyin "bitta bazada ko'p mijoz"
-- ga o'tilsa, jadval o'zgartirilmaydi — faqat so'rovlarga filtr qo'shiladi.

CREATE TABLE IF NOT EXISTS tenant (
  id          INTEGER PRIMARY KEY,
  shop_name   TEXT,
  setup_done  INTEGER NOT NULL DEFAULT 0,
  setup_step  TEXT,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
  tenant_id   INTEGER NOT NULL DEFAULT 1,
  key         TEXT NOT NULL,
  value       TEXT,
  updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (tenant_id, key)
);

CREATE TABLE IF NOT EXISTS users (
  tenant_id   INTEGER NOT NULL DEFAULT 1,
  tg_id       INTEGER NOT NULL,
  name        TEXT,
  username    TEXT,
  phone       TEXT,
  role        TEXT NOT NULL DEFAULT 'staff'
              CHECK (role IN ('owner', 'manager', 'staff')),
  section     TEXT,
  active      INTEGER NOT NULL DEFAULT 1,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  last_seen   TEXT,
  PRIMARY KEY (tenant_id, tg_id)
);

CREATE TABLE IF NOT EXISTS license (
  tenant_id   INTEGER PRIMARY KEY DEFAULT 1,
  state       TEXT NOT NULL DEFAULT 'trial'
              CHECK (state IN ('trial', 'active', 'grace', 'locked')),
  plan        TEXT NOT NULL DEFAULT 'boshlangich'
              CHECK (plan IN ('boshlangich', 'standart', 'toliq')),
  started_at  TEXT NOT NULL DEFAULT (datetime('now')),
  expires_at  TEXT NOT NULL,
  notified    TEXT
);

-- Deploy qayta ishga tushganda yarim qolgan ish yo'qolmasin
CREATE TABLE IF NOT EXISTS sessions (
  tenant_id   INTEGER NOT NULL DEFAULT 1,
  tg_id       INTEGER NOT NULL,
  state       TEXT,
  data        TEXT,
  updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (tenant_id, tg_id)
);

-- Oxirgi 8 tasi saqlanadi: eski xabardagi tugma ham ishlashi kerak
CREATE TABLE IF NOT EXISTS webapp_tokens (
  token       TEXT PRIMARY KEY,
  tenant_id   INTEGER NOT NULL DEFAULT 1,
  tg_id       INTEGER NOT NULL,
  purpose     TEXT,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_webapp_tokens_user
  ON webapp_tokens (tg_id, created_at DESC);

-- _bito_try_paths keshi: ishlagan manzil saqlanadi, qayta sinalmaydi
CREATE TABLE IF NOT EXISTS bito_paths (
  tenant_id   INTEGER NOT NULL DEFAULT 1,
  logical     TEXT NOT NULL,
  resolved    TEXT,
  checked_at  TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (tenant_id, logical)
);

-- Telegram bir update'ni ikki marta yuborishi mumkin
CREATE TABLE IF NOT EXISTS idempotency (
  key         TEXT PRIMARY KEY,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit_log (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id   INTEGER NOT NULL DEFAULT 1,
  tg_id       INTEGER,
  action      TEXT NOT NULL,
  payload     TEXT,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_audit_time ON audit_log (created_at DESC);
