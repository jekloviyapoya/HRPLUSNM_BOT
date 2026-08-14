-- 009_vazifalar.sql — vazifa berish, bajarish, hisobot
--
-- Vazifa xodimlar moduliga bog'lanadi: bajarilgani ball beradi, muddati
-- o'tgani ball ayiradi. Ballar `points` jadvaliga yoziladi — u yagona manba.

CREATE TABLE IF NOT EXISTS task (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id    INTEGER NOT NULL,
  title        TEXT NOT NULL,
  details      TEXT,
  photo_id     TEXT,                -- Telegram file_id
  assigned_to  INTEGER,             -- NULL = hammaga
  created_by   INTEGER NOT NULL,
  due_at       TEXT,                -- ISO, mahalliy
  status       TEXT NOT NULL DEFAULT 'yangi'
               CHECK (status IN ('yangi', 'bajarilmoqda', 'tekshiruvda',
                                 'bajarildi', 'qaytarildi', 'bekor')),
  points       INTEGER NOT NULL DEFAULT 1,
  repeat_rule  TEXT,                -- 'kunlik' | 'haftalik' | NULL
  parent_id    INTEGER,             -- takrorlanuvchi vazifaning nusxasi
  done_at      TEXT,
  checked_by   INTEGER,
  late         INTEGER NOT NULL DEFAULT 0,
  created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_task_user
  ON task (tenant_id, assigned_to, status);
CREATE INDEX IF NOT EXISTS ix_task_due
  ON task (tenant_id, status, due_at);

-- Vazifa bo'yicha yozishmalar: hisobot, qaytarish sababi
CREATE TABLE IF NOT EXISTS task_note (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id   INTEGER NOT NULL,
  task_id     INTEGER NOT NULL,
  tg_id       INTEGER NOT NULL,
  kind        TEXT NOT NULL DEFAULT 'izoh'
              CHECK (kind IN ('izoh', 'hisobot', 'qaytarish')),
  text        TEXT,
  photo_id    TEXT,
  created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_task_note ON task_note (tenant_id, task_id);
