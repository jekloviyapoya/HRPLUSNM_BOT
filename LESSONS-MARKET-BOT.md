# market-bot dan olingan saboqlar

> Manba: `jekloviyapoya/market-bot/bot.py` (21 444 qator, bitta fayl).
> Faqat **o'qildi** — kod ko'chirilmagan. market-bot bitta do'kon uchun
> yozilgan, qiymatlari qotirilgan va `tenant_id` yo'q; uni ko'chirish
> ko'p ijarachilikni buzardi.
>
> Bu fayldagi har bir band — amalda yuz bergan xatoning natijasi. Ular
> HRPLUSNM'da qaytarilmasligi uchun yozildi.

---

## 1. Nakladnoy: AI ekstraksiyasi

### 1.1 Narx hujjatdan AYNAN olinadi, hisoblanmaydi

AI mahsulot nomidagi `1X12` kabi belgiga qarab «bitta donaning narxi» ni
o'zi hisoblab chiqarishga urinadi. Bunday belgisi yo'q qatorlarda
(masalan Bonaqua) xato taxmin qiladi.

**Qoida:** `price` — hujjatda yozilgan narx ustunidan so'zma-so'z. Hech
qanday bo'lish yoki ko'paytirish yo'q.

### 1.2 «Итого» qatori mahsulot emas

*2026-08-08 xatosi.* Jadval oxiridagi umumiy qator oxirgi mahsulotga
qo'shilib ketgan: 2 dona o'rniga **80 dona** yozilgan.

**Qoida:** promptda «Итого/Jami qatoridagi son hech qaysi mahsulotga
qo'shilmasin» deb aniq yozilishi shart.

### 1.3 Blok invarianti — eng qimmat xato

*2026-08-02 xatosi.* Blokli tovarda `qty` donaga aylantirilgan (5 blok →
30 dona), keyin kodning boshqa joyi **yana** `×6` qilgan. Natijada
135 000 o'rniga **810 000** chiqib, Bito'ga olti barobar ortiq yuklangan.

**Invariant:** `qty` = **blok soni**, `price` = **bitta dona narxi**.
Jami har joyda `qty × block_size`. Bu qoida butun kod bo'ylab bir xil
bo'lishi shart — bitta joyda buzilsa, xato ko'rinmaydi va faqat ombor
qoldig'ida chiqadi.

`block_size` hujjatdagi jami summadan teskari hisoblanadi va faqat
butun songa yaqin bo'lsa (2–96 oralig'ida) qabul qilinadi.

### 1.4 Jami ustuni tekshiruv uchun kerak

Hujjatda qator jamisi (`Сумма`, `Jami`, `Стоимость поставки`) bo'lsa —
u ham aynan olinadi. Miqdor va narx to'g'ri o'qilganini tekshirish
imkonini beradi.

### 1.5 Yetkazib beruvchini aniqlash

AI quyidagilarni supplier deb olib qo'yadi va bu xato:
- `Покупатель/Получатель` — bu **bizning do'kon**
- `Ответственный`/ekspeditor — bu shaxs ismi
- Mahsulot nomlari va brendlar (Snickers, Nestle)

Firma nomiga mahsulot so'zini qo'shish ham xato: «Adler» firmasi bo'lsa
«Adler Snickers» deb yozmaslik kerak.

Aniq topilmasa — bo'sh qoldirilsin, foydalanuvchi o'zi tanlaydi.

### 1.6 `max_tokens` kesilishi

100+ qatorli nakladnoyda javob kesilib, JSON buziladi
(«Unterminated string»).

**Qoida:** kesilganda **yuqoriga** qarab qayta urinish. Kichikroq limit
bilan qayta urinish faqat battar kesadi, hech narsani tuzatmaydi.
8192 dan yuqori chiqish uchun Anthropic'ning beta-header'i kerak.

### 1.7 Shtrix-kodni tozalash

AI ba'zan artikul yoki bo'lak matnni shtrix-kodga ilashtirib qo'yadi.
Faqat raqamlar qoldiriladi va uzunligi 8–14 oralig'ida ekani tekshiriladi.

### 1.8 Firma tuzilishi xotirasi

Har firmaning jadval tuzilishi bir marta o'rganilib, keyingi
nakladnoylarda AI'ga eslatma sifatida beriladi (`settings` da
`nakhint:<firma>` kalitlari). Bu ekstraksiya aniqligini sezilarli
oshiradi.

---

## 2. Bito API xulq-atvori

### 2.1 `purchase/get-paging` mahsulotlarni qaytarmaydi

Ro'yxatda faqat sarlavha ma'lumotlari bor. Mahsulotlar **faqat**
`purchase/get-by-id` orqali ko'rinadi. Ya'ni firma bo'yicha tahlil
uchun har xaridni alohida ochish kerak.

### 2.2 Filtr parametri nomi noaniq

Supplier bo'yicha filtrda `supliaer_id` / `supplier_id` / `supplier_ids`
— qaysi biri ishlashi oldindan ma'lum emas. market-bot ularni sinab
ko'radi, ishlamasa bruteforce bilan hamma sahifani varaqlaydi.

*(HRPLUSNM'da bu naqsh allaqachon bor: `bito.resolve()` yo'llarni,
`verify()` esa auth sxemasini sinab keshlaydi.)*

### 2.3 `PUT product/update` to'liq almashtiradi

`custom_fields` yuborilmasa, mahsulotning **PLU (tarozi kodi) o'chib
ketadi**. Shuning uchun o'qilgan qiymat o'zgartirilmasdan qaytariladi.

**Umumiy qoida:** Bito'da yangilashdan oldin obyektni o'qib, o'zgarmagan
maydonlarni qaytarib yuborish shart.

### 2.3a `PUT product/update` HAMMA maydonni almashtiradi (jonli tasdiq)

2026-08-14 jonli sinov: yangilashda `barcode` yuborilmagan edi — mahsulot
shtrix-kodi **null bo'lib o'chdi**. Ya'ni to'liq almashtirish faqat
`custom_fields` ga emas, *har bir* ixtiyoriy maydonga tegishli.

Yaratishda esa (`POST product/create`): `barcode` topda yuboriladi,
`barcodes[]` bo'sh qolsa ham skaner qidiruvi (`get-by-barcode`) ishlaydi.
PLU shakli: `custom_fields: [{"_id": <ta'rif id>, "value": <raqam>}]`.

### 2.4 `sales/by-item-pagin` faqat sotilganlarni beradi

Umuman sotilmagan mahsulotlar bu hisobotda **yo'q**. «Turib qolganlar»
ro'yxatini undan qurish mumkin emas — alohida endpoint kerak.

---

## 3. Telegram cheklovlari

- Bitta xabarga **~100 tadan ortiq inline tugma sig'maydi**
- Uzun matn 4096 belgidan keyin kesiladi (`ui.chunks` bor)
- Izoh (caption) 1024 belgi (`ui.caption` bor)

---

## 4. Arxitektura saboqlari

### 4.1 Bitta SQLite ulanishi

market-bot butun bot bo'ylab bitta ulanishdan foydalanadi
(`check_same_thread=False`). HRPLUSNM'da bu `db.py` da RLock bilan
o'ralgan — aynan shu sabab.

### 4.2 Dashboard Bito'ni jonli kutmasin

Sahifa har ochilganda Bito'ga borsa, foydalanuvchi kutib qoladi va
Bito sekin bo'lsa sahifa umuman ochilmaydi.

*(HRPLUSNM'da `ombor` moduli shu tamoyilda: ro'yxat keshdan, qidiruv
jonli.)*

### 4.3 Xodim ishdan bo'shatilsa jadval o'chirilmaydi

Faqat `users.role = 'fired'` qo'yiladi. Tarix saqlanadi.

---

## 4b. Keyingi tuzatishlar (2026-08-13/14)

### 4b.1 Eski ochiq davomat yozuvi

`WHERE checkout_time IS NULL` tekshiruvining o'zi yetarli emas. Xodim bir
kun «Ketdim» bosishni unutsa, o'sha yozuv uni **abadiy «ishda»**
ko'rsatardi.

To'g'ri yo'l: faqat **oxirgi** yozuv olinadi va u **bugungi** bo'lishi ham
shart. Qo'shimcha: eski ochiq yozuvlar jadval oxiri bo'yicha yopiladi,
jadval yo'q bo'lsa umuman yopilmaydi — soxta ish soati yozilmasin.

### 4b.2 Fantom qarz

Qarz hisobotida Bito ro'yxatida endi mavjud bo'lmagan firmalar qolib
ketadi va yo'q qarzni ko'rsatadi. **Ro'yxatda yo'q firma to'langan
hisoblanadi** — qarz summasi hisobotdan emas, `supplier/get-paging`
ro'yxatidan yig'iladi.

### 4b.3 Vazifa ishga kelganda yetkaziladi

Ish vaqtidan tashqarida berilgan vazifani xodim ko'rmay qolishi mumkin.
Kelish qayd etilganda ochiq vazifalar qayta eslatiladi.

### 4b.4 Chegirmasiz post «aksiya» emas

Chegirma bo'lmasa postda «AKSIYA», «chegirma», «arzon» so'zlari
ishlatilmaydi — faqat «Narxi». Aks holda mijoz chegirma kutadi va narxni
ko'rib xafa bo'ladi.

## 5. HRPLUSNM uchun xulosa

`nakladnoy` modulini yozishda:

1. Yuqoridagi prompt qoidalari (1.1–1.7) **to'liq ko'chiriladi** —
   ular amalda sinovdan o'tgan
2. Blok invarianti (1.3) kodda bitta joyda belgilanadi va test bilan
   qopladi
3. Firma xotirasi (1.8) `settings` da, tenant bo'yicha alohida
4. `purchase/get-by-id` chaqiruvi (2.1) hisobga olinadi — ro'yxat
   yetarli emas
5. Mahsulot yangilashda (2.3) o'qib-qaytarish naqshi qo'llanadi
