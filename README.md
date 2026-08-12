# HRPLUSNM_BOT

Do'kon boshqaruv boti — abonent to'lovli SaaS. Har mijozga alohida bot,
alohida baza; kod bitta.

> Bonnu Market boti (`jekloviyapoya/market-bot`) bilan hech qanday aloqasi
> yo'q. O'sha repo, servis, token va bazaga tegilmaydi.

## Ishga tushirish

### Railway

1. Servis yarating → GitHub repo `jekloviyapoya/HRPLUSNM_BOT`
2. **Volume qo'shing**, mount path `/data` — busiz har deployda baza yo'qoladi
3. Variables (pastdagi ro'yxat)
4. Deploy. Health: `/health`, holat sahifasi: `/`

### Env o'zgaruvchilar

Majburiy:

| Kalit | Izoh |
|---|---|
| `TELEGRAM_BOT_TOKEN` | BotFather'dan |
| `SAAS_OWNER_ID` | sotuvchining Telegram ID |

Tavsiya etiladi:

| Kalit | Standart |
|---|---|
| `DB_PATH` | `/data/bot.db` |
| `PUBLIC_URL` | Railway domeni |
| `WEBAPP_SECRET` | tasodifiy uzun satr |
| `TZ` | `Asia/Tashkent` |
| `TRIAL_DAYS` | `14` |
| `GRACE_DAYS` | `3` |
| `LICENSE_SERVER_URL` | bo'sh — BMP-BOTLAR manzili |
| `LICENSE_BOT_USERNAME` | `HRPLUSNM_BOT` |
| `LICENSE_CHECK_MINUTES` | `15` |

Keyingi bosqichlarda kerak bo'ladi: `ANTHROPIC_API_KEY`, `GROQ_API_KEY`,
`GEMINI_API_KEY`, `OPENAI_API_KEY`.

**Bito API kaliti env'da emas** — u har mijoz uchun sehrgar orqali kiritiladi
va bazada saqlanadi.

### Lokal

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
DB_PATH=./local.db TELEGRAM_BOT_TOKEN=... SAAS_OWNER_ID=... python main.py
```

## Push

```bash
./push.sh "nima o'zgardi"
```

Tekshiruvlar: `ast.parse` → `SyntaxWarning` → `node --check` (webapp JS) →
duplikat `def` → `pytest`. **Biror biri yiqilsa push bo'lmaydi.**

## Tuzilma

```
bot/
  config.py      env va konstantalar
  db.py          SQLite, RLock, migratsiyalar
  tenant.py      sozlamalar (standart qiymatsiz)
  users.py       rollar
  license.py     obuna holatlari va tariflar
  sessions.py    bazada saqlanadigan sessiyalar
  errors.py      xatolar iyerarxiyasi
  ui.py          klaviaturalar, formatlash
  handlers.py    Telegram handlerlari
  jobs.py        fon threadlari
  onboarding.py  o'rnatish sehrgari
  webapp/        Flask + Jinja2 (HTML Python satri ichida EMAS)
  modules/       3-bosqichdan
migrations/      001_init.sql, ...
tests/
```

## Litsenziya

`LICENSE_SERVER_URL` bo'sh bo'lsa — mahalliy 14 kunlik sinov ishlaydi.

Manzil berilsa va biznes egasi **Obuna → Kalitni kiritish** orqali BMP-BOTLAR
kalitini kiritsa, muddat markazdan boshqariladi: `GET /api/check`.

Markaz javob bermasa mijoz **ishlashda davom etadi** — oxirgi ma'lum holat
bo'yicha. Bu ataylab: markaziy server yagona nosozlik nuqtasi bo'lmasligi
kerak. Uzoq uzilishda sotuvchiga ogohlantirish boradi, mijoz qulflanmaydi.

## Holat

- **1-bosqich** — poydevor: baza, migratsiyalar, rollar, menyu, webapp
- **2-bosqich** — Bito ulanishi va o'rnatish sehrgari
- **3-bosqich** — bitta bazada ko'p biznes, taklif kodlari
- **4-bosqich** — BMP-BOTLAR litsenziya serveriga ulanish

Keyingisi — modullar: Ombor, Nakladnoy, Moliya, Vazifalar, Marketing.

## Buyruqlar

| Buyruq | Kim |
|---|---|
| `/start`, `/menu`, `/build` | hamma |
| `/saas` | sotuvchi |
| `/set_license <biznes_id> YYYY-MM-DD [tarif]` | sotuvchi |
| `/saas_msg <matn>` | sotuvchi |
