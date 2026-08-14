-- 005_xodimlar.sql — davomat, ballar, ish haqi
--
-- Har jadvalda tenant_id bor va u standart qiymatsiz: kod uni doim
-- ochiq uzatadi. Standart bo'lsa, unutilgan so'rov jimgina 1-biznesga
-- yozib yuboradi.

-- Ish jadvali: xodim + hafta kuni -> boshlanish/tugash
CREATE TABLE IF NOT EXISTS shift (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id   INTEGER NOT NULL,
  tg_id       INTEGER NOT NULL,
  weekday     INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),  -- 0 = dushanba
  starts_at   TEXT NOT NULL,     -- 'HH:MM'
  ends_at     TEXT NOT NULL,
  active      INTEGER NOT NULL DEFAULT 1,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_shift
  ON shift (tenant_id, tg_id, weekday) WHERE active = 1;

-- Davomat: kunlik kelish/ketish
CREATE TABLE IF NOT EXISTS attendance (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id    INTEGER NOT NULL,
  tg_id        INTEGER NOT NULL,
  work_date    TEXT NOT NULL,     -- 'YYYY-MM-DD', mahalliy vaqt bo'yicha
  came_at      TEXT,              -- ISO, mahalliy
  left_at      TEXT,
  late_minutes INTEGER NOT NULL DEFAULT 0,
  early_minutes INTEGER NOT NULL DEFAULT 0,
  status       TEXT NOT NULL DEFAULT 'keldi'
               CHECK (status IN ('keldi', 'kechikdi', 'kelmadi', 'sababli')),
  note         TEXT,
  came_lat     REAL,
  came_lon     REAL,
  distance_m   INTEGER,
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_attendance
  ON attendance (tenant_id, tg_id, work_date);
CREATE INDEX IF NOT EXISTS ix_attendance_date
  ON attendance (tenant_id, work_date);

-- Ballar: har o'zgarish alohida qator. Jami hech qachon ustunda saqlanmaydi,
-- har doim yig'indi bilan hisoblanadi — aks holda ular bir-biridan uzoqlashadi.
CREATE TABLE IF NOT EXISTS points (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id   INTEGER NOT NULL,
  tg_id       INTEGER NOT NULL,
  amount      INTEGER NOT NULL,      -- musbat yoki manfiy
  reason      TEXT NOT NULL,
  source      TEXT NOT NULL DEFAULT 'qolda'
              CHECK (source IN ('qolda', 'davomat', 'vazifa', 'tizim')),
  ref         TEXT,                  -- masalan attendance.id
  given_by    INTEGER,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_points_user
  ON points (tenant_id, tg_id, created_at DESC);

-- Ish haqi: oylik hisob
CREATE TABLE IF NOT EXISTS salary (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id    INTEGER NOT NULL,
  tg_id        INTEGER NOT NULL,
  base         REAL NOT NULL DEFAULT 0,
  per_day      REAL,                 -- kunbay bo'lsa
  currency     TEXT,
  active       INTEGER NOT NULL DEFAULT 1,
  started_at   TEXT NOT NULL DEFAULT (date('now')),
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_salary_user ON salary (tenant_id, tg_id);

-- To'lovlar va ushlab qolishlar
CREATE TABLE IF NOT EXISTS payout (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id   INTEGER NOT NULL,
  tg_id       INTEGER NOT NULL,
  period      TEXT NOT NULL,         -- 'YYYY-MM'
  amount      REAL NOT NULL,
  kind        TEXT NOT NULL DEFAULT 'tolov'
              CHECK (kind IN ('tolov', 'avans', 'ushlab_qolish', 'mukofot')),
  note        TEXT,
  created_by  INTEGER,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_payout_period
  ON payout (tenant_id, period, tg_id);
