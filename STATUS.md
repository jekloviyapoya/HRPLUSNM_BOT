# HRPLUSNM_BOT — joriy holat

> Bu fayl har ish sessiyasi oxirida yangilanadi.
> Oxirgi yangilanish: 2026-08-14 · commit `e50e826`
>
> **Yagona manba:** `jekloviyapoya/BMP_BOT/CONTRACT.md`. Unga qarshi kod
> yozilmaydi. O'zgartirish kerak bo'lsa — BMP chatida, keyin bu yerda.

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

**Shartnomaga muvofiqlik** (`tests/test_contract.py`)
- `CONTRACT.md` §1 dagi javob namunasi aynan ko'chirilgan va sinaladi
- Tekshiriladi: 12 soniyalik uzilish, `?key=&bot=`, 200+`invalid`,
  503 → offline, bo'sh `[]` va maydon yo'qligining farqi, `notice.id`
  barqarorligi, `expired` → grace/qulf, modul kalitlari va bog'liqliklari,
  kalitning niqoblanishi
- Shartnoma o'zgarsa bu testlar yiqiladi — bu maqsad

**Testlar:** 70 ta, hammasi o'tadi.

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

1. **72 soatdan keyin nima bo'ladi?** `CONTRACT.md` §1.1: «mijoz 503 ni
   offline deb qabul qiladi va oxirgi holatda ishlashda davom etadi
   (72 soat)». Undan keyingi xulq aytilmagan.
   Hozirgi kod: **qulflamaydi**, faqat sotuvchiga ogohlantirish yuboradi.
   Sabab — BMP uzoq yiqilsa 50 ta biznes to'xtashi serverning o'zi
   yo'qligidan yomonroq. Agar shartnoma 72 soatdan keyin qulflashni
   ko'zda tutsa — ayting, bir qatorlik o'zgarish
2. **`modules_detail` saqlanmaydi.** HRPLUSNM modullari limitsiz (yoq/o'chir),
   shuning uchun hozircha kerak emas. `/api/usage` faqat limitli modullar
   uchun — HRPLUSNM'da bittasi ham yo'q. Limitli modul paydo bo'lsa,
   migratsiya + `usage()` chaqiruvi qo'shiladi
3. **`business_name` ishlatilmaydi.** Do'kon nomi mijozning o'zidan olinadi
   (sehrgarda). BMP'dagi nom bilan solishtirish foydali bo'lishi mumkin —
   kerak bo'lsa qo'shaman
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
