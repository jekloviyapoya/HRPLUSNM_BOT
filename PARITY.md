# market-bot ↔ HRPLUSNM tenglik jadvali

> Manba: `jekloviyapoya/market-bot/bot.py` (21 564 qator), 2026-08-14
> inventarizatsiyasi. Maqsad: **xatti-harakat tengligi** — market-bot
> qanday ishlasa, HRPLUSNM ham shunday. Kod ko'chirilmaydi (bitta do'kon,
> qotirilgan qiymatlar, tenant_id yo'q) — har funksiya ko'p ijarachi
> qilib qayta yoziladi.
>
> Har yopilgan band commit SHA bilan belgilanadi.

## ✅ Bor (tenglik yetarli)

| market-bot | HRPLUSNM |
|---|---|
| 👥 Xodimlar, ⏱ Davomat, 💰 Ish haqi, 🏆 Reyting, 📅 Jadval | `xodimlar` |
| 📋 Vazifa berish, ✅ Tasdiqlash, takror | `vazifalar` (67189be) |
| 🧑‍💼 Ishga qabul | `hr` |
| 📦 Ombor hisoboti | `ombor` |
| 🛒 Zakaz tavsiyasi, ABC, turib qolganlar | `ombor_ai` |
| 📦 Inventarizatsiya | `inventarizatsiya` |
| ⭐ Mijoz baholari (QR) | `mijoz` |
| 📈 MARKETING, 📣 Post | `marketing` |
| 🏢 Firmalar (qarz), 🎯 Zakaz limiti | `moliya` |
| Nakladnoy (AI o'qish, moslash, yaratish) | `nakladnoy` (55e227a) |
| Kelish/Ketish, Holat, Ballarim, Baholarim | `xodimlar` xodim tomoni |

## ❌ Yo'q — ko'chirish navbati

Tartib — do'konga foyda bo'yicha. Yopilganda SHA yoziladi.

1. ~~💵 Savdo~~ — **yopildi** (`moliya` ichida, yangi modul kaliti
   CONTRACT §3 ni buzmasin deb). Bugungi/haftalik/oylik/muddatli, oylik
   reja + chiziq, bonus foizi, xodimga «mening savdom», xodim↔Bito ismi
   bog'lash (30 kunlik sotuvchilardan tanlanadi, qo'lda yozilmaydi).
   Keyinga qoldi: «turib qolgan mahsulot sotuvi» kesimi, bonusni ish
   haqiga qo'shish
2. ~~🛒 Zakaz~~ — **yopildi** (`ombor_ai` da «🛒 Zakaz»). Firma
   tanlanadi (qidiruv bilan) → 1–4 hafta → «hafta savdosi × hafta −
   qoldiq», summa oxirgi kirim narxida, «olingan lekin sotilmayapti»
   ro'yxati. Filtr parametri variantlari sinaladi, tekshiruv: qaytgan
   qatorlar HAMMASI shu firmaniki (Bito noma'lum parametrni jim
   o'tkazadi); ishlagani keshlanadi, bo'lmasa bruteforce
3. ~~🛒 Zarur mahsulotlar~~ — **yopildi** (`ombor` da, xodimga ham
   ochiq). Bito'dan ko'p tanlash yoki ✏️ erkin matn, ⭐ 1–5, kutish
   muddati. Xodim faqat o'zinikini o'chiradi; xodim qo'shsa rahbarlarga
   xabar. Fon kuzatuvchisi (30 daq): baseline usuli — birinchi
   tekshiruvda qoldiq yoziladi, keyin oshsa «keldi», qator o'chadi va
   qo'shganga xabar
4. **📋 Vazifa tarixi** + 📊 Vazifa hisoboti (kesimlar). 13579-qator
5. **📆 Haftalik / 🗓 Muddatli hisobot** — xodimning davriy hisobotlari.
   11288/11308-qator
6. **📢 Takliflar va Shikoyatlar** — XODIM taklif/shikoyati (mijoznikidan
   farqli, ichki, anonim variant bilan). 12966-qator
7. **💬 Guruh chat** — jamoa ichki chati, yoq/o'chir sozlamasi bilan.
   11503-qator
8. **🎯 Maqsadlar** — savdo maqsadlari va holat paneli. 2344-qator
9. **💰 Pul taqvimi** — to'lovlar taqvimi (moliya'ga qo'shimcha).
   5190-qator
10. **📥 Excel** — vazifa/davomat eksporti (openpyxl). 13030-qator
11. **⚖️ PLU kodlar** — hisobot (kimda bor/yo'q) + bo'shlarga taklif.
    14564-qator
12. **🔗 Mahsulot bog'lash** — xodimga mahsulot biriktirish. 14695-qator
13. **🧠 Test natijalari** + kunlik quiz xodimlarga (set_toggle_quiz).
    12977-qator
14. **📁 Menyu guruhlari** — tugmalarni papkalarga yig'ish, yashirish
    (menu_groups, hidden_menu). 4382–4560-qator
15. **Sozlamalar kalitlari** — quiz/chat/ai_advice yoq-o'chir,
    tips_time, ombor eslatma jadvali (set_toggle_*, set_stock_*)
16. **⏰ Vazifa kechiktirish** — «Keyinroq / 1 soatdan keyin» eslatma

## ⚠️ Ochiq savol

- market-bot'da `/app` (webapp, PLU plitkasi) bor — Telegram WebApp.
  HRPLUSNM'da webapp yo'q. Ko'chiriladimi — egasi hal qiladi.
- Reply-keyboard (doimiy pastki menyu) market-bot uslubi; HRPLUSNM
  inline-menyuda. Tenglik ma'noda, ko'rinishda emas — hozircha inline
  qoladi, chunki 50 biznesda rol-menyu inline'da soddaroq.
