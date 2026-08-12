"""Joriy ijarachi konteksti.

telebot ko'p threadli: bir vaqtda bir necha mijozning xabari ishlanadi.
Shu sabab joriy `tenant_id` global o'zgaruvchida saqlanmaydi — thread-local.
Aks holda ikki mijozning ma'lumoti aralashadi va buni loglardan topib
bo'lmaydi.
"""

import threading

from .errors import BotError

_local = threading.local()


class NoTenant(BotError):
    def __init__(self):
        super().__init__(
            "Sizning biznesingiz topilmadi. /start bosing."
        )


def set(tenant_id):  # noqa: A001
    _local.tenant_id = int(tenant_id) if tenant_id is not None else None
    return _local.tenant_id


def current():
    """Joriy tenant_id yoki None."""
    return getattr(_local, "tenant_id", None)


def require():
    tid = current()
    if tid is None:
        raise NoTenant()
    return tid


def clear():
    _local.tenant_id = None


class scope:
    """with ctx.scope(5): ... — fon ishlari uchun."""

    def __init__(self, tenant_id):
        self.tenant_id = tenant_id
        self.previous = None

    def __enter__(self):
        self.previous = current()
        set(self.tenant_id)
        return self.tenant_id

    def __exit__(self, *exc):
        set(self.previous)
        return False
