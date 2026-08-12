"""Foydalanuvchilar va rollar."""

from . import config, ctx, db
from .errors import AccessError

ROLES = ("owner", "manager", "staff")
_RANK = {"staff": 0, "manager": 1, "owner": 2}


def get(tg_id):
    return db.row(
        "SELECT * FROM users WHERE tenant_id = ? AND tg_id = ?",
        (ctx.require(), tg_id),
    )


def has_owner():
    return bool(
        db.value(
            "SELECT 1 FROM users WHERE tenant_id = ? AND role = 'owner' LIMIT 1",
            (ctx.require(),),
        )
    )


def upsert(tg_id, name=None, username=None, role=None):
    existing = get(tg_id)
    if existing:
        db.run(
            "UPDATE users SET name = COALESCE(?, name), "
            "  username = COALESCE(?, username), role = COALESCE(?, role), "
            "  last_seen = datetime('now') "
            "WHERE tenant_id = ? AND tg_id = ?",
            (name, username, role, ctx.require(), tg_id),
        )
    else:
        db.run(
            "INSERT INTO users (tenant_id, tg_id, name, username, role, last_seen) "
            "VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (ctx.require(), tg_id, name, username, role or "staff"),
        )
    return get(tg_id)


def role_of(tg_id):
    u = get(tg_id)
    return u["role"] if u else None


def is_seller(tg_id):
    """Sotuvchi — SaaS egasi. Bu rol bazada emas, env'da."""
    return config.SAAS_OWNER_ID and int(tg_id) == config.SAAS_OWNER_ID


def require_role(tg_id, minimum):
    if is_seller(tg_id):
        return "owner"
    got = role_of(tg_id)
    if got is None or _RANK.get(got, -1) < _RANK[minimum]:
        raise AccessError()
    return got


def touch(tg_id):
    db.run(
        "UPDATE users SET last_seen = datetime('now') "
        "WHERE tenant_id = ? AND tg_id = ?",
        (ctx.require(), tg_id),
    )


def listing():
    return db.rows(
        "SELECT * FROM users WHERE tenant_id = ? AND active = 1 "
        "ORDER BY CASE role WHEN 'owner' THEN 0 WHEN 'manager' THEN 1 "
        "ELSE 2 END, name",
        (ctx.require(),),
    )
