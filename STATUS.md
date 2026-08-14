# HRPLUSNM_BOT — joriy holat

> Bu fayl har ish sessiyasi oxirida yangilanadi.
> Oxirgi yangilanish: 2026-08-14 · Savdo (PARITY 1-band)
>
> **Katalogdagi 10 ta modulning hammasi yozildi.**
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

**Offline qoidasi** (`CONTRACT.md` §1.6)
- Aloqa yo'qligi **hech qachon** qulflash sababi emas
- Oxirgi ma'lum `expires` mahalliy saqlanadi. `expires + grace_days` o'tsa —
  server holatidan qat'i nazar cheklanadi
- Ikki manbadan qat'iyrog'i olinadi: server javobi va sana hisobi
- Natija: yo'lni to'sib cheksiz litsenziya olib bo'lmaydi; BMP yiqilsa
  to'lagan mijoz to'xtamaydi

**Bito ikki qavatli mantiq**
- Ikkita mustaqil shart aralashtirilmaydi:
  (a) **to'lov** — BMP moduli yoqiqmi → `ModuleError`, aloqa: sotuvchi
  (b) **texnik** — tenant Bito kalitini kiritganmi → `BitoNotConnected`,
  aloqa: Sozlamalar
- Modul to'langan lekin Bito ulanmagan bo'lsa: tugma **ko'rinadi**, bosilganda
  tushunarli xabar chiqadi. Bot yiqilmaydi
- Obuna ekranida ⚠️ belgisi: to'langan, lekin ulanish kutilyapti
- Bito ma'lumotlari faqat tenant `settings` da, BMP'ga hech qachon yuborilmaydi

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

**`xodimlar` moduli** (`bot/modules/xodimlar.py`, migratsiya `005`)
- Ish jadvali: hafta kuni bo'yicha boshlanish/tugash vaqti
- Davomat: keldim/ketdim, kechikish avtomatik hisoblanadi (5 daqiqagacha
  bag'rikenglik), ishlagan vaqt
- Joylashuv tekshiruvi: ish joyi belgilangan bo'lsa, radiusdan tashqarida
  qayd qilinmaydi. Belgilanmagan bo'lsa — so'ralmaydi
- Ballar: har o'zgarish alohida qator, jami **hech qachon ustunda
  saqlanmaydi** — har doim yig'indi bilan hisoblanadi
- Reyting: oylik, medallar bilan
- Ish haqi: oylik yoki kunbay stavka, avans/ushlab qolish/mukofot, qoldiq
- Menejer paneli: jamoa holati bir ekranda

**`ombor` moduli** (`bot/modules/ombor.py`, migratsiya `006`)
- **Qidiruv jonli** — bitta so'rov, tez. Nom, SKU, shtrix-kod bo'yicha
- **Kam qolganlar keshdan** — Bito'da 10 000+ mahsulot bo'lishi mumkin,
  sahifa 200 ta. Har safar yig'ish 50+ so'rov degani, bot javobi uchun
  juda sekin. Fonda kuniga bir marta skanerlanadi
- Chegara: Bito'dagi `red_line` → `yellow_line` → tenant sozlamasi. Hech
  biri yo'q bo'lsa **faqat tugaganlar** ko'rsatiladi. Aks holda chegara
  to'ldirilmagan do'konda mahsulotlarning yarmi «kam» bo'lib chiqardi
- `_warehouses` bor bo'lsa faqat u hukmron — ko'p omborli do'konda boshqa
  filial qoldig'i o'ziniki ko'rinmasin
- Modul fon ishlari `jobs.py` orqali: faqat modul yoqilgan va Bito ulangan
  biznesda ishlaydi

**Bito klientida yangi**
- `paged()`: `page` **doim yuboriladi** — Bito uni majburiy talab qiladi,
  hujjatda ixtiyoriy deb yozilgan bo'lsa ham (400 qaytaradi)
- So'rov usuli (GET/POST) noma'lum — ikkalasi sinaladi, ishlagani keshlanadi

**`nakladnoy` moduli — to'liq** (`bot/modules/nakladnoy.py`, migratsiya `007`)
- Rasm / PDF / Excel qabul qiladi, AI o'qiydi, tekshirish ekranini beradi
- Moslashtirish ekrani: nomzodlardan tanlash, tanlov xotiraga yoziladi
- Firma Bito yetkazib beruvchilaridan topiladi, topilmasa ro'yxatdan tanlanadi
- **Bito'ga kirim** (`bot/nak_upload.py`)
- `bot/ai.py`: Anthropic klienti. Javob kesilsa **yuqoriga** qarab qayta
  urinadi (pastga urinish battar kesadi), 529/503 da qayta uriniladi
- `nak_prompt.py`: ekstraksiya qoidalari market-bot'dan olingan va test
  bilan qo'riqlanadi (`test_prompt_qoidalari_joyida`)
- Firma tuzilishi xotirasi: har firmaning ustunlari o'rganilib, keyingi
  hujjatlarda AI'ga eslatma sifatida beriladi
- Hujjatdagi jami bilan solishtirish: farq 1% dan oshsa ogohlantiradi

**Kirim yuklashdagi uchta himoya** (`nak_upload.py`)
- **504 «yaratilmadi» degani emas.** Bito nginx'i uzsa, kirim serverda
  yaratilgan bo'lishi mumkin. Avtomatik qayta yuborilmaydi — izohdagi
  betakror belgi bo'yicha tekshiriladi
- **Partiyalash**: 60 qatordan bo'linadi, aks holda katta hujjat 504 beradi.
  Bir partiya yiqilsa qolgani yuklanadi
- **26000 xatosi** (mahsulot o'chirilgan) nomi bilan aytiladi

**INVARIANT — buzilmasin:** `qty` = blok soni, `price` = bitta dona narxi.
Blok donaga FAQAT `nak_upload.build_products()` da aylanadi:
`amount = qty × block_size`, `cost = price`. market-bot'da bu ikki joyda
qilinib, Bito'ga olti barobar ortiq yuklangan edi (2026-08-02).

**Katalog keshi va moslashtirish** (`bot/catalog.py`, migratsiya `008`)
- Ombor skaneri hamma sahifani varaqlaganda **katalog ham to'ldiriladi** —
  ikkinchi marta varaqlash kerak emas
- Moslashtirish tartibi: xotira → shtrix-kod → SKU → aniq nom →
  so'z ustma-ustligi
- **Ikkilanishda taxmin qilinmaydi.** Ikki mahsulot yaqin ball olsa,
  nomzodlar foydalanuvchiga ko'rsatiladi. Noto'g'ri moslashtirish ombor
  qoldig'ini buzadi va uni qo'lda tuzatish og'ir
- Xotira: foydalanuvchi bir marta tanlagan mos kelish keyingi
  nakladnoylarda avtomatik qo'llanadi (`nak_alias`)
- Defis bo'shliqqa aylanadi: «Coca-Cola» va «Coca Cola» bir-birini topsin

**Sozlamalar bo'limi** (`bot/settings_ui.py`)
Modul emas — har doim ochiq. To'rt bo'lim:
- **Do'kon**: nom, valyuta, vaqt mintaqasi, ish joyi (lokatsiya), radius
- **Bito**: kalitni almashtirish, tashkilot/ombor/narx qayta tanlash,
  aloqani tekshirish
- **Xodimlar**: har xodim uchun jadval (haftalik, bir urinishda),
  oylik yoki kunlik stavka, rol, ishdan bo'shatish
- **Ombor**: kam qolgan chegarasi

Ishdan bo'shatishda hech narsa o'chirilmaydi — `users.active = 0`, davomat
va ish haqi tarixi saqlanadi.

**`vazifalar` moduli** (`bot/modules/vazifalar.py`, migratsiya `009`)
- Oqim: menejer beradi → xodim qabul qiladi va hisobot yuboradi →
  menejer tasdiqlaydi yoki sabab bilan qaytaradi
- **Ball faqat tasdiqlangach beriladi.** Xodim o'zi «bajardim» desa ball
  yo'q — aks holda hisob ma'nosini yo'qotadi
- Muddat matndan o'qiladi: «bugun 18:00», «ertaga», «3 kun», sana
- Muddati o'tgani uchun ball **bir marta** ayiriladi (`late` bayrog'i)
- Hammaga berilgan vazifani kim qabul qilsa — o'shanga biriktiriladi
- Ballar `xodimlar` moduliga yoziladi, ikkinchi hisob yuritilmaydi

**`moliya` moduli** (`bot/modules/moliya.py`)
Uchta qoida market-bot'da amalda sinovdan o'tgan:
- **Kassa balans hisobotidan** olinadi, tranzaksiyalardan yig'ilmaydi
  (taxmin 10.7 mln ko'rsatgan, haqiqiysi 31.2 mln edi)
- **Firmalar `supplier/get-paging` dan.** Qarz hisobotidagi `supplier._id`
  mahsulot kartochkasidagi `supplier_ids` bilan mos kelmaydi — 114 ta
  bog'langan mahsulotda nol moslik chiqqan
- **Zakaz limiti ufq kuniga bo'linadi.** Bo'linmasa bir kunlik zakazga
  butun haftalik byudjet ruxsat berilgan bo'lardi (7 barobar ortiq)

Ko'rsatadi: kassadagi pul kassalar bo'yicha, ikki tomonlama qarzlar,
zakaz limiti ochiq hisob-kitob bilan va odatdagi sur'atga nisbatan tavsiya.
Bir hisobot yiqilsa qolgani ishlaydi.

**`marketing` moduli** (`bot/modules/marketing.py`, migratsiya `010`)
- Oqim: mahsulot (katalogdan qidiriladi) → narxlar → AI matn → rasm →
  AI poster (ixtiyoriy) → kanalga yuborish
- **AI ishlamasa ham post chiqadi** — zaxira matn tayyor
- **Holat qisman yangilanadi.** To'liq qayta yozish narxlarni o'chirib
  yuborardi (2026-08-08 xatosi) — `update()` faqat berilgan maydonni
  o'zgartiradi, test qo'riqlaydi
- Poster (`bot/imagen.py`, gpt-image-1): mahsulot rasmidan sahna yasaydi.
  Promptda «matn qo'shma» aytilgan — AI rasmda harflarni buzadi
- Bito'da fayl yuklab olish endpointi yo'q, shuning uchun rasm
  foydalanuvchidan so'raladi, avval behuda qidirilmaydi

**`inventarizatsiya` moduli** (migratsiya `011`)
- Sanash **mahalliy** olib boriladi, Bito'ga faqat oxirida yoziladi.
  Sabab: `done` holati qoldiqni qaytarib bo'lmaydigan tarzda o'zgartiradi.
  Yarim sanalgan ro'yxat yuborilsa, sanalmaganlari nolga tushardi
- Takroriy sanash **almashtiradi**, qo'shmaydi
- Yuklash uch qadam: create → add-products → set-status done.
  `starting_date` majburiy (busiz 400). Har qadam alohida tekshiriladi va
  o'rtada uzilsa mijozga Bito'da nima ochiq qolgani aytiladi
- Yuklashdan oldin aniq ogohlantirish, faqat egasi tasdiqlaydi
- 250 tadan ortiq mahsulot 100 tadan bo'lib qo'shiladi

**`ombor_ai` moduli** (migratsiya `012`)
- Zakaz tavsiyasi: `kunlik_sotuv × ufq − qoldiq`. Eng shoshilinchi
  (zaxirasi tez tugaydigani) birinchi. Bot hech narsa buyurtma qilmaydi —
  faqat ko'rsatadi
- **Turib qolganlar katalogdan sotuv keshini AYIRIB olinadi.** Bito'ning
  `sales/by-item` hisoboti umuman sotilmagan mahsulotni ko'rsatmaydi —
  ayirilmasa ro'yxat doim bo'sh chiqardi
- Sekin sotilayotganlar: zaxirasi 90 kundan ortiqqa yetadiganlar
- ABC: tushum ulushi bo'yicha. **Sinf mahsulot qo'shilgunga qadar bo'lgan
  ulushga qarab beriladi** — aks holda chegarani kesib o'tgan eng katta
  tovar «C» bo'lib chiqardi (test topdi)
- Sotuv hisoboti keshlanadi, kuniga bir marta yangilanadi

**`hr` moduli** (migratsiya `013`)
- Vakansiya yaratiladi, havola e'lon qilinadi: `t.me/BOT?start=job_<id>`
- Nomzod havolani ochsa, bot u bilan **AI orqali suhbatlashadi**, keyin
  ball va xulosa bilan menejerlarga yuboradi
- **Nomzod `users` jadvaliga yozilmaydi** — u boshqa do'konga ham ariza
  bera olsin, «bir odam bitta biznesda» qoidasi buzilmasin
- Promptda: bir xabarda **faqat bitta savol** (ikkitasi birlashsa nomzod
  faqat oxirgisiga javob beradi)
- Suhbat oxiri `[TUGADI]` belgisi bilan aniqlanadi, belgi javobdan olinadi
- **Rasm va matn alohida yuboriladi** — izoh 1024 belgidan oshsa Telegram
  jimgina rad etadi
- AI yiqilsa ariza yo'qolmaydi: ballsiz saqlanadi va sabab yoziladi

**`mijoz` moduli** (migratsiya `014`)
- QR kod: `t.me/BOT?start=baho_<tenant_id>`. Mijoz skanerlaydi, yulduzcha
  qo'yadi, xohlasa izoh yozadi yoki rasm yuboradi
- **Past baho (1–2⭐) darhol egaga boradi** — javob qaytarish imkoni bo'lsin
- Mijoz `users` jadvaliga yozilmaydi va ismi so'ralmaydi. Baho anonim;
  aloqa kerak bo'lsa telefonni o'zi qoldiradi
- Statistika: o'rtacha ball va yulduzlar bo'yicha taqsimot

**Kirish modeli** (`bot/auth.py`, migratsiya `015`)
Mijoz **o'zi biznes ocholmaydi**. Sotuvchi hisob yaratadi:
- `/new_client +998901234567 [nom]` → telefon va parol chiqadi
- `/set_bito <id> <kalit>` → Bito ulanadi, tashkilot/ombor/narx avtomatik
  tanlanadi (yagona variant bo'lsa)
- `/set_key <id> <kalit>` → litsenziya kaliti. **Mijoz kalitni ko'rmaydi** —
  BMP «kalitni mijozga bermang» deydi. Kalit darhol tekshiriladi; server
  tanimasa eski kalit tiklanadi. `-` bilan olib tashlanadi
- `/reset_password <id>` → parol unutilganda

Mijoz botga telefon + parol bilan kiradi va birinchi kirishda parolni
almashtirishi so'raladi. Keyin Sozlamalar → Hisob dan istalgan payt.

- **Parol xeshlangan** (`pbkdf2`, 200 000 iteratsiya, tasodifiy tuz).
  Ochiq matnda hech qayerda saqlanmaydi
- 5 marta noto'g'ri urinishdan keyin 15 daqiqaga blok
- Bot har safar parol yozilgan xabarni o'chirishni eslatadi
- Xodimlar avvalgidek taklif kodi bilan kiradi — bu o'zgarmadi

**market-bot dan qabul qilingan tuzatishlar** (2026-08-13/14)
- **Eski ochiq davomat yozuvi** xodimni abadiy «ishda» ko'rsatardi.
  `at_work()` faqat oxirgi VA bugungi yozuvni oladi. `close_stale()`
  unutilgan ketishlarni jadval oxiri bo'yicha yopadi (jadvalsiz kun
  yopilmaydi — soxta ish soati yozilmasin)
- **Fantom qarz**: qarz hisobotida o'chirilgan firmalar qolib ketadi.
  Firmalar qarzi endi `supplier/get-paging` ro'yxatidan yig'iladi;
  ro'yxat olinmasa hisobot zaxira sifatida ishlatiladi
- **Vazifa ishga kelganda yetkaziladi** — ish vaqtidan tashqarida
  berilgani ko'rinmay qolmasin
- **Chegirmasiz post «aksiya» emas** — «chegirma», «arzon» so'zlari
  ishlatilmaydi, faqat «Narxi»

**Litsenziya env nomlari** (`bot/config.py`)
- BMP `LICENSE_API=https://.../api/check` deb beradi, kod esa `/api/check`
  ni o'zi qo'shadi. **Ikkala nom ham qabul qilinadi**, yo'l qismi kesiladi —
  aks holda so'rov `/api/check/api/check` ga ketardi
- `LICENSE_SERVER_URL` berilgan bo'lsa u ustunroq
- `LICENSE_KEY` — faqat **bitta do'kon uchun alohida deploy** qilinganda.
  Bazada bir nechta biznes bo'lsa e'tiborsiz qoldiriladi va logga yoziladi:
  kalit qaysi biznesniki ekani noma'lum, taxmin qilinmaydi
- Mavjud kalit env bilan qayta yozilmaydi

**BMP orqali avto ochish** (`CONTRACT.md §5`, `bot/auth.py`,
`licsrv.provision`)
- Sotuvchi mijozni **faqat BMP'da** ro'yxatga oladi (telefon bilan). Mijoz
  HRPLUSNM'da «Kirish» → 📱 kontakt tugmasi → hisob avtomatik ochiladi,
  kalit BMP'dan olinib bazaga yoziladi, mijoz o'ziga parol o'rnatadi
- **Faqat Telegram kontakt orqali** (`contact.user_id == from_user.id`) —
  yozilgan raqam bilan emas, aks holda birovning raqamini bilgan odam
  do'konini egallab olardi
- Token: BMP'da `PROVISION_TOKEN`, bu yerda `LICENSE_PROVISION_TOKEN` —
  bir xil qiymat. Bo'sh bo'lsa avto ochish o'chiq, `/new_client` ishlaydi
- 403/404/429 «topilmadi» emas — `Unreachable`: sozlama xatosida mijozga
  «obuna yo'q» deb aldab bo'lmaydi
- provision o'tib check o'tmasa — kalit turadi, fon ishi 15 daqiqada
  sinxronlaydi
- Mavjud hisob egasi kontakt yuborsa — odatdagidek parol so'raladi

**Nakladnoy: yangi mahsulot yaratish** (`create_in_bito`)
- Moslashtirish ekranida «➕ Bito'da yangi yaratish» tugmasi. Minimal tana
  jonli sinovda tasdiqlangan; nom/shtrix-kod qatordan, o'lchov nomdan
  taxmin qilinadi (kg belgisi bo'lsa kilogram, aks holda dona)
- SKU: 9 bilan boshlanadigan 8 xonali (vaqt + hisoblagich), to'qnashsa
  bir marta qayta uriladi
- PLU yaratishda BERILMAYDI — noto'g'ri tarozi kodi boshqa mahsulotni
  chiqarib yuborardi; mijozga «narx va PLU ni Bito'da belgilang» deyiladi
- Yaratilgach keshga yoziladi va qator avtomatik moslashadi

**Takrorlanuvchi vazifalar** (`spawn_next`, `spawn_recurring`)
- Yaratishda muddatdan keyin savol: bir martalik / har kuni / har hafta.
  Takror muddatsiz bo'lmaydi — bo'sh bo'lsa bugun 18:00 qo'yiladi
- «Bajarildi» → davomchi darhol; muddati o'tgan ochiq vazifa → fon ishi
  (15 daq) davomchini ochadi, eskisi ochiq qoladi (qarzdorlik ko'rinadi)
- «Bekor» zanjirni to'xtatadi — takrorni o'chirish yo'li shu
- O'tkazib yuborilgan kunlar uchun BITTA davomchi (muddati kelajakka
  suriladi); parent_id tekshiruvi tufayli davomchi hech qachon ikkitalanmaydi

**Ovoz → matn** (`bot/stt.py`, Groq Whisper)
- Ovozli xabar matnga o'giriladi va xuddi yozilgan xabarday joriy oqimga
  qaytariladi: vazifa matni, muddat, hisobot, izoh — qayerda matn kutilsa
- Auth bosqichlarida (telefon/parol) ovoz ATAYLAB rad etiladi
- Sessiya yo'q bo'lsa — matn ko'rsatiladi, menyudan bo'lim tanlash taklifi
- 120 soniyadan uzun ovoz rad etiladi; til avtomatik (o'zbek/rus)
- Env: `GROQ_API_KEY` (bo'sh bo'lsa modul o'chiq, bot ishlayveradi)

**Savdo (moliya ichida)** — PARITY 1-band
- Yangi modul kaliti ochilmadi (CONTRACT §3 qat'iy) — savdo `moliya`
  bo'limi. Menejer: 💵 Savdo menyusi; xodim: «Bugungi savdongiz»
- Bito yo'llari market-bot'dan (ishlab turgan): `reports/dashboard/summary`
  (POST) va `reports/dashboard/top/responsible` (POST)
- Kun chegaralari mahalliy vaqtdan UTC ga o'giriladi (utc_range) —
  aks holda Bito kunni suradi
- Sozlamalar: `savdo_reja`, `savdo_bonus` (standart 0.5%),
  `bito_name:<tg_id>` — xodim↔Bito ismi

**Testlar:** 424 ta, hammasi o'tadi.

---

## Modullar holati

| Kalit | Katalogda | Yozilgan |
|---|---|---|
| `xodimlar` | ✅ | ✅ |
| `vazifalar` | ✅ | ✅ |
| `hr` | ✅ | ✅ |
| `ombor` | ✅ | ✅ |
| `ombor_ai` | ✅ | ✅ |
| `nakladnoy` | ✅ | ✅ |
| `inventarizatsiya` | ✅ | ✅ |
| `moliya` | ✅ | ✅ |
| `marketing` | ✅ | ✅ |
| `mijoz` | ✅ | ✅ |

`xodimlar` yoqilgan biznesda menyuda ikkita tugma chiqadi (egasi/menejerga),
xodimga bitta.

---

## Keyingi qadam

**Katalogdagi barcha modullar yozildi.** Endi haqiqiy mijozda sinov.

Yetishmayotgan qismlar (ehtiyoj paydo bo'lganda):
- `POST /api/usage` — modul limitlari, BMP tomonida tayyor bo'lgach

---

## Joriy yo'nalish: market-bot tengligi

Egasining ko'rsatmasi: market-bot qanday ishlasa, HRPLUSNM ham shunday.
Farqlar `PARITY.md` da — 16 band, tartib bilan yopiladi, kod
ko'chirilmaydi (xatti-harakat ko'chiriladi). market-bot repo tokenga
qo'shilgan.

## Ochiq savollar

1. **`modules_detail` saqlanmaydi.** HRPLUSNM modullari limitsiz (yoq/o'chir),
   shuning uchun hozircha kerak emas. `/api/usage` faqat limitli modullar
   uchun — HRPLUSNM'da bittasi ham yo'q. Limitli modul paydo bo'lsa,
   migratsiya + `usage()` chaqiruvi qo'shiladi
2. **`business_name` ishlatilmaydi.** Do'kon nomi mijozning o'zidan olinadi
   (sehrgarda). BMP'dagi nom bilan solishtirish foydali bo'lishi mumkin —
   kerak bo'lsa qo'shaman
3. **Tugma bilan tanlash yo'li sinalmagan.** Bonnu'da har biridan bitta
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
