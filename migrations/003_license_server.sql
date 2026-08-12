-- 003_license_server.sql — litsenziya markazdan (BMP-BOTLAR) boshqariladi
--
-- license_key bo'lmasa: mahalliy sinov muddati ishlaydi (o'z-o'ziga xizmat).
-- license_key bo'lsa: haqiqat manbai BMP. Mahalliy yozuv — kesh va server
-- javob bermaganda ishlatiladigan zaxira.

ALTER TABLE license ADD COLUMN license_key TEXT;
ALTER TABLE license ADD COLUMN source TEXT NOT NULL DEFAULT 'local';
ALTER TABLE license ADD COLUMN remote_status TEXT;
ALTER TABLE license ADD COLUMN grace_days INTEGER;
ALTER TABLE license ADD COLUMN checked_at TEXT;
ALTER TABLE license ADD COLUMN offline_since TEXT;
ALTER TABLE license ADD COLUMN notice_id TEXT;
ALTER TABLE license ADD COLUMN price REAL;

CREATE INDEX IF NOT EXISTS ix_license_key ON license (license_key);
