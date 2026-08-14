"""Nakladnoy ekstraksiya prompti.

Har bir qoida — market-bot'da amalda yuz bergan xatoning natijasi.
Batafsil: `LESSONS-MARKET-BOT.md`. Qoidalarni yumshatishdan oldin
o'sha faylni o'qing — ularning har biri qimmatga tushgan.
"""

SCHEMA = """Javobni FAQAT JSON qaytaring, boshqa hech narsa yozmang:

{
  "supplier": "yetkazib beruvchi firma nomi yoki bo'sh satr",
  "number": "hujjat raqami yoki bo'sh satr",
  "date": "YYYY-MM-DD yoki bo'sh satr",
  "total": hujjatdagi umumiy summa (son) yoki null,
  "items": [
    {
      "name": "mahsulot nomi hujjatda yozilganidek",
      "qty": miqdor (son),
      "qty_unit": "birlik: бл, kor, dona, kg — yozilgan bo'lsa",
      "price": narx (son),
      "total": qator jamisi (son) yoki null,
      "barcode": "shtrix-kod yoki bo'sh satr"
    }
  ]
}"""

RULES = """NAKLADNOY O'QISH QOIDALARI

NARX: "price" — hujjatda YOZILGAN narx ustunidan AYNAN olinadi. HECH QANDAY
hisob-kitob qilmang: bo'lmang, ko'paytirmang. Mahsulot nomidagi "1X12",
"1*6" kabi belgilarga qarab "bitta donaning narxi"ni O'ZINGIZ hisoblashga
urinmang — bunday belgisi yo'q qatorlarda xato taxmin qilasiz. Narx
ustunida nima yozilgan bo'lsa, o'shani yozing.

CHEGIRMA: chegirmali narx ustuni bo'lsa — o'sha olinadi. Bo'lmasa oddiy
narx ustuni.

QATOR JAMISI: hujjatda qator jamisi ustuni bo'lsa ("Сумма", "Jami",
"Стоимость поставки") — uni "total" ga AYNAN yozing. Hisoblab chiqarmang.
Bu miqdor va narx to'g'ri o'qilganini tekshirish uchun kerak.

⛔ "ИТОГО" QATORI MAHSULOT EMAS. Jadval oxiridagi Итого/Jami/Всего
qatoridagi umumiy miqdor va umumiy summani HECH QAYSI mahsulot qatoriga
QO'SHMANG. Oxirgi mahsulotning miqdori — o'z qatoridagi son. Umumiy summani
faqat yuqoridagi "total" maydoniga yozing.

MIQDOR BIRLIGI: miqdor ustunida "1 бл", "3 бл", "2 kor" kabi birlik
yozilgan bo'lsa — sonni "qty" ga, birlikni "qty_unit" ga yozing.

YETKAZIB BERUVCHI: "supplier" ga hujjatdagi SOTUVCHI / YETKAZIB BERUVCHI
tashkilot nomini yozing ("Поставщик", "Продавец", hujjat shapkasidagi
firma).
Quyidagilarni supplier deb OLMANG:
- "Покупатель" / "Получatель" — bu bizning do'kon
- "Ответственный" / ekspeditor — bu shaxs ismi
- mahsulot nomlari va brendlar (Snickers, Nestle, Coca-Cola)
Firma nomiga mahsulot so'zini QO'SHMANG: "Adler" firmasi bo'lsa
"Adler Snickers" deb yozish XATO.
Aniq sotuvchi nomi topilmasa — bo'sh qoldiring, foydalanuvchi o'zi tanlaydi.

SHTRIX-KOD: faqat raqamlardan iborat, 8–14 xonali bo'lsa yozing. Artikul
yoki boshqa kodni shtrix-kod deb yozmang.

TO'LIQLIK: hujjatda 50+ qator bo'lishi mumkin — BARCHASINI qamrab oling,
hech birini tashlab ketmang. O'qib bo'lmagan qatornigina tashlang."""


def hints_block(rows):
    """Firma tuzilishi eslatmalari.

    Har firmaning jadval tuzilishi bir marta o'rganilib, keyingi
    hujjatlarda AI'ga beriladi — aniqlikni sezilarli oshiradi.
    """
    lines = [f"- {row['supplier']}: {str(row['hint'])[:220]}" for row in rows
             if row["hint"]]
    if not lines:
        return ""
    return (
        "\n\nFIRMA TUZILISH ESLATMALARI (oldingi nakladnoylardan o'rganilgan; "
        "hujjat qaysi firmaniki ekanini aniqlagach, mos eslatmaga AMAL QILING "
        "— ustunlarni shunga ko'ra o'qing):\n" + "\n".join(lines) + "\n"
    )


def build(hint_rows=(), text=None):
    """To'liq ko'rsatma matni."""
    parts = [RULES, hints_block(hint_rows), "\n\n", SCHEMA]
    if text:
        parts += ["\n\nNAKLADNOY MATNI:\n", text]
    return "".join(parts)
