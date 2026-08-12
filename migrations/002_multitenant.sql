-- 002_multitenant.sql — bitta bazada ko'p biznes
--
-- Oldin: tenant.id CHECK (id=1), ya'ni bitta do'kon.
-- Endi: har egasi o'z tenant'ini ochadi, xodimlar taklif kodi bilan kiradi.
-- SQLite CHECK ni olib tashlay olmaydi — jadval qayta quriladi.

CREATE TABLE tenant_new (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  shop_name    TEXT,
  owner_tg_id  INTEGER,
  invite_code  TEXT UNIQUE,
  setup_done   INTEGER NOT NULL DEFAULT 0,
  setup_step   TEXT,
  active       INTEGER NOT NULL DEFAULT 1,
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT INTO tenant_new (id, shop_name, setup_done, setup_step, created_at)
  SELECT id, shop_name, setup_done, setup_step, created_at FROM tenant;

DROP TABLE tenant;
ALTER TABLE tenant_new RENAME TO tenant;

-- license: tenant_id endi 1 ga qotirilmagan
CREATE TABLE license_new (
  tenant_id   INTEGER PRIMARY KEY,
  state       TEXT NOT NULL DEFAULT 'trial'
              CHECK (state IN ('trial', 'active', 'grace', 'locked')),
  plan        TEXT NOT NULL DEFAULT 'boshlangich'
              CHECK (plan IN ('boshlangich', 'standart', 'toliq')),
  started_at  TEXT NOT NULL DEFAULT (datetime('now')),
  expires_at  TEXT NOT NULL,
  notified    TEXT
);

INSERT INTO license_new (tenant_id, state, plan, started_at, expires_at, notified)
  SELECT tenant_id, state, plan, started_at, expires_at, notified FROM license;

DROP TABLE license;
ALTER TABLE license_new RENAME TO license;

-- Bir odam bir biznesda. Bu qoida bo'lmasa, kimning nomidan yozayotganini
-- aniqlash uchun har safar so'rash kerak bo'ladi.
CREATE UNIQUE INDEX IF NOT EXISTS ux_users_tg ON users (tg_id);

-- Mavjud tenant'ga egasini bog'lash
UPDATE tenant SET owner_tg_id = (
  SELECT tg_id FROM users
  WHERE users.tenant_id = tenant.id AND users.role = 'owner'
  LIMIT 1
);

CREATE INDEX IF NOT EXISTS ix_settings_tenant ON settings (tenant_id);
CREATE INDEX IF NOT EXISTS ix_users_tenant ON users (tenant_id);
CREATE INDEX IF NOT EXISTS ix_audit_tenant ON audit_log (tenant_id, created_at DESC);
