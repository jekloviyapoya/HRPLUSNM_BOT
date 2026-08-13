# HRPLUSNM_BOT — joriy holat

> Bu fayl har ish sessiyasi oxirida yangilanadi.
> Oxirgi yangilanish: 2026-08-14 · commit `c2e56c5`

---

## Nima ishlayapti

**Poydevor**
- SQLite + migratsiyalar (`001` → `004`), RLock bilan thread-safe wrapper
- `push.sh`: `ast.parse` → `SyntaxWarning` → `node --check` → duplikat `def` →
  `pytest`. Biror biri yiqilsa push to'xtaydi
- Flask webapp (`/health`, `/`), Jinja2 shablonlari — HTML Python satri ichida emas
- Railway deploy, volume `/data`

**Ko'p ijarachilik**
- Bitta bot, 50 tagacha biznes. `bot/ctx.py` — thread-local tenant konteksti
- Har biznes o'z Bito kaliti va sozlamalari bilan (`settings` jadvali)
- Taklif kodi bilan jamoaga qo'shilish, deep link `t.me/BOT?start=KOD`
- Rollar: `owner` / `manager` / `staff`

**Bito ulanishi** (`bot/bito.py`)
- Auth sxemasi va endpoint yo'llari taxmin qilinmaydi — nomzodlar sinaladi,
  ishlagani keshlanadi (`bito_paths` jadvali, `bito_auth_scheme` sozlamasi)
- 5xx yo'l xatosi deb hisoblanmaydi
- O'rnatish sehrgari 4 savol: do'kon nomi, Bito kaliti, tashkilot, ombor +
  narx-ro'yxati. Valyuta narx-ro'yxatidan, o'lchov birliklari `system_code`
  orqali topiladi. Yagona variant avtomatik tanlanadi

**Litsenziya** (`bot/licsrv.py`, `bot/license.py`)
- Kalit bo'lsa haqiqat manbai BMP_BOT; bo'lmasa mahalliy 14 kunlik sinov
- **Server javob bermasa mijoz ishlashda davom etadi** — oxirgi ma'lum holat
  bilan. Avtomatik qulflash yo'q, sotuvchiga ogohlantirish boradi
- `license_key` logdan tozalanadi

**Modul litsenziyasi** (`bot/modules/`)
- Pog'onali tarif olib tashlandi. Har modul alohida yoqiladi
- Katalog: 10 modul (`registry.py`), `@implement` bilan sinf biriktiriladi
- Menyu reyestrdan quriladi — yoqilmagan modul tugmasi ko'rinmaydi
- Bog'liqlik avtomatik qo'shiladi (`ombor_ai` → `ombor`)
- `/set_modules <biznes_id> kalit,kalit`

**Testlar:** 58 ta, hammasi o'tadi.

---

## Modullar holati

| Kalit | Katalogda | Yozilgan |
|---|---|---|
| `xodimlar` | ✅ | ❌ keyingi ish |
| `vazifalar` | ✅ | ❌ |
| `hr` | ✅ | ❌ |
| `ombor` | ✅ | ❌ |
| `ombor_ai` | ✅ | ❌ |
| `nakladnoy` | ✅ | ❌ |
| `inventarizatsiya` | ✅ | ❌ |
| `moliya` | ✅ | ❌ |
| `marketing` | ✅ | ❌ |
| `mijoz` | ✅ | ❌ |

Hozir menyuda faqat **Sozlamalar** va **Obuna** ko'rinadi — bu kutilgan holat.

---

## Keyingi qadam

**`xodimlar` moduli.** Bito talab qilmaydi, shuning uchun mijoz Bito ulanmasdan
ham darrov foyda ko'radi.

Tarkibi: davomat (lokatsiya bilan), ish haqi, ballar va reyting, ish jadvali.

Undan keyingi tartib: `vazifalar` → `hr` → `ombor` → `nakladnoy` → `moliya` →
qolganlari. Har modul alohida push, sinovlari bilan.

---

## Ochiq savollar

1. **`CONTRACT.md` o'qilmadi.** Token `BMP_BOT` repoga kira olmaydi
   (`Not Found`). Contents: Read ruxsati kerak. Shu sababli hozirgi kod
   avvalgi kelishuvlarga qurilgan — shartnoma bilan solishtirilmagan
2. **`/api/usage` hali yo'q.** Modul limitlari (masalan oyiga nechta nakladnoy)
   BMP tomonida tayyor bo'lgach ulanadi
3. **`modules` maydoni** `/api/check` javobida hali kelmaydi. Kod tayyor:
   maydon yo'q bo'lsa oxirgi ma'lum ro'yxat saqlanadi, mijoz modullarini
   yo'qotmaydi
4. **Tugma bilan tanlash yo'li sinalmagan.** Bonnu'da har biridan bitta
   tashkilot/ombor bo'lgani uchun sehrgar avtomatik o'tadi. Bir nechta variant
   bo'lgan mijozda bu yo'l birinchi marta ishlaydi

---

## Muhim prinsiplar (o'zgarmaydi)

- **Markaz yagona nosozlik nuqtasi emas.** BMP yiqilsa 50 ta biznes to'xtamaydi
- **Kodda qotirilgan do'kon qiymati yo'q.** Hammasi `tenant.get()` orqali.
  Buni tekshiradigan test bor: `test_konfigda_dokonga_xos_qiymat_yoq`
- **Jim yiqilish yo'q.** Har handler `try/except`, xato ham logga, ham
  foydalanuvchiga
- **Har yozuv `tenant_id` bilan**, so'rovlarda ham doim filtr
- **Sessiyalar bazada** — deploy qayta ishga tushganda yarim qolgan ish
  yo'qolmaydi
- **HTML parse mode**, Markdown emas: eski Markdown `**` ni jimgina yeb qo'yadi
