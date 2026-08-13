"""Modul bazaviy sinfi.

Har modul shu interfeysni to'ldiradi. Hech biri majburiy emas —
faqat kerakligini yozing.
"""


class Module:
    spec = None  # registry tomonidan qo'yiladi

    def menu(self, role):
        """Rol uchun tugmalar: [(matn, callback_data), ...]

        Bo'sh ro'yxat qaytarsa — bu rolga modul ko'rinmaydi.
        Standart: bitta tugma, modul nomi bilan.
        """
        return [(self.spec.title, f"mod:{self.spec.key}")]

    def register(self, bot, guard):
        """Telegram handlerlarini biriktiradi.

        guard(fn) — handlerni o'rab, modul yoqilganini tekshiradi.
        Har handler shu orqali o'tishi shart.
        """

    def jobs(self):
        """Fon ishlari: [(nom, funksiya, interval_soniya), ...]

        Funksiya joriy tenant konteksti ichida chaqiriladi.
        """
        return []
