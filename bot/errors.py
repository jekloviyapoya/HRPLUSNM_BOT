"""Xatolar. Har biri foydalanuvchiga ko'rsatiladigan matnni o'zi biladi.

Jim yiqilish taqiqlanadi: har handler shu turlarni ushlab, foydalanuvchiga
tushunarli xabar chiqaradi va to'liq traceback'ni logga yozadi.
"""


class BotError(Exception):
    """Foydalanuvchiga ko'rsatish mumkin bo'lgan xato."""

    user_message = "Kutilmagan xato yuz berdi."

    def __init__(self, message=None):
        super().__init__(message or self.user_message)
        if message:
            self.user_message = message


class SetupError(BotError):
    """Sozlanmagan qiymat so'raldi."""

    @classmethod
    def for_key(cls, key, section="Sozlamalar"):
        return cls(
            f"Bu funksiya uchun avval {section} bo'limini to'ldiring "
            f"(yetishmayapti: {key})."
        )


class BitoError(BotError):
    """Bito API xatosi. code — Bito qaytargan raqam (masalan 26018)."""

    def __init__(self, message=None, code=None, path=None, raw=None):
        self.code = code
        self.path = path
        self.raw = raw
        super().__init__(message or "Bito bilan aloqada xato.")


class LicenseError(BotError):
    """Obuna muddati tugagan."""

    def __init__(self):
        super().__init__(
            "Obuna muddati tugadi. Ma'lumotlaringiz saqlanib turibdi — "
            "to'lovdan keyin hammasi joyida qoladi."
        )


class AccessError(BotError):
    """Rol yetmaydi."""

    def __init__(self):
        super().__init__("Bu bo'lim sizning rolingizga ochiq emas.")
