-- 013_hr.sql — ishga qabul: vakansiya va nomzodlar
--
-- Nomzod tenant foydalanuvchisi EMAS: u botga faqat vakansiya havolasi
-- orqali kiradi va suhbatdan keyin chiqib ketadi. Shuning uchun `users`
-- jadvaliga yozilmaydi — aks holda bir odam bitta biznesda qoidasi
-- buzilardi va u boshqa do'konga ishga kira olmasdi.

CREATE TABLE IF NOT EXISTS job (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id    INTEGER NOT NULL,
  title        TEXT NOT NULL,
  requirements TEXT,
  questions    TEXT,              -- JSON massiv
  salary       TEXT,
  place_lat    REAL,
  place_lon    REAL,
  max_km       REAL,
  status       TEXT NOT NULL DEFAULT 'ochiq'
               CHECK (status IN ('ochiq', 'yopiq')),
  created_by   INTEGER,
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_job_tenant ON job (tenant_id, status);

CREATE TABLE IF NOT EXISTS applicant (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id   INTEGER NOT NULL,
  job_id      INTEGER NOT NULL,
  tg_id       INTEGER NOT NULL,
  full_name   TEXT,
  phone       TEXT,
  photo_id    TEXT,
  lat         REAL,
  lon         REAL,
  distance_km REAL,
  history     TEXT,               -- JSON: suhbat tarixi
  score       INTEGER,
  summary     TEXT,
  strengths   TEXT,
  concerns    TEXT,
  status      TEXT NOT NULL DEFAULT 'suhbatda'
              CHECK (status IN ('suhbatda', 'baholandi', 'qabul', 'rad')),
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  finished_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_applicant
  ON applicant (tenant_id, job_id, tg_id);
CREATE INDEX IF NOT EXISTS ix_applicant_score
  ON applicant (tenant_id, job_id, score DESC);
