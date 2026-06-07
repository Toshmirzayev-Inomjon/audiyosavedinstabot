# Media Downloader Telegram Bot

Bot quyidagilarni bajaradi:

- YouTube va Instagram public havolalaridan video yuklash
- Telegram post havolasidan media yuklash
- Botga yuborilgan yoki forward qilingan video/audio faylni qabul qilish
- Video/audio yoki havolani MP3 formatiga o'tkazish
- Videoni Telegram aylana video (`video_note`) formatiga o'tkazish
- Aylana videoni 16:9 to'rtburchak videoga o'tkazish
- PostgreSQL/SQLite balans, tranzaksiya tarixi, haq yechish va xatoda refund
- Telegram Stars orqali balans to'ldirish
- Telegram Stars orqali 30 kunlik avtomatik Premium obuna
- `/start` va `/tarif` orqali 30 kunlik Bepul, Standard va Premium tariflar
- Standard/Premium tariflarni ichki balansdan xavfsiz sotib olish
- 360p, 720p, 1080p va faqat audio sifat tanlash
- Yuklash navbati, foiz ko'rsatkichi va `/cancel` orqali bekor qilish
- Yuklash tarixi va Telegram `file_id` orqali qayta yuborish
- Kunlik bepul limit, promo kod va referral bonuslari
- PostgreSQL yoki lokal SQLite database
- Telegram limitidan katta fayl uchun vaqtinchalik HTTPS havola
- O'zbek, rus va ingliz tilidagi asosiy menyu
- Mini App orqali yuklash, tarix, profil, balans va admin panel
- Mini App ichida 10 kategoriya va 100 ta tartibli servis katalogi
- Bitta AI kaliti orqali AI Chat, AI+Web va AI Image xizmatlari
- Admin orqali `/addbalance USER_ID SUMMA` komandasi
- Telegram WebApp orqali profil, telefon tasdiqlash kodi va ichki virtual hisoblar

Stars paketlari `.env` ichidagi `STAR_PACKAGES` orqali boshqariladi. Foydalanuvchi
`O'zim kiritaman` tugmasi orqali ham hisob to'ldira oladi; standart minimal miqdor
`CUSTOM_STAR_MIN=5`, custom kurs esa `STAR_CREDIT_RATE=1000`.

Stars to'lovi kelganda bot avval payment'ni `pending` holatda saqlaydi, 5 soniya
tekshiruv progressini ko'rsatadi va keyin ichki balansga qo'shadi.

Premium obuna `PREMIUM_STARS` narxida 30 kun ishlaydi va Telegram tomonidan
avtomatik yangilanadi. Premium foydalanuvchi kunlik limitdan ozod qilinadi va
1080p sifatni tanlay oladi.

## Railway PostgreSQL

Yangilanishda balans va profil yo'qolmasligi uchun Railway loyihasiga PostgreSQL
qo'shing:

1. Project ichida `+ Add` -> `Database` -> `PostgreSQL`.
2. Bot servisining `Variables` bo'limida:

```env
DATABASE_URL=${{Postgres.DATABASE_URL}}
```

`Postgres` qismi Railway yaratgan database servisining nomi bilan bir xil bo'lishi
kerak. `DATABASE_URL` berilsa bot avtomatik PostgreSQL ishlatadi. Berilmasa lokal
`DATABASE_PATH` bo'yicha SQLite ishlaydi.

Asosiy sozlamalar:

```env
MAX_DOWNLOAD_MB=500
TELEGRAM_UPLOAD_MB=49
QUEUE_CONCURRENCY=2
DAILY_FREE_LIMIT=3
PREMIUM_STARS=100
TARIFF_STANDARD_PRICE=25000
TARIFF_PREMIUM_PRICE=50000
TARIFF_STANDARD_STARS=25
TARIFF_PREMIUM_STARS=50
TARIFF_STANDARD_DAILY_LIMIT=15
TARIFF_PERIOD_DAYS=30
REFERRAL_REWARD=5000
REFERRAL_NEW_USER_REWARD=2000
PUBLIC_FILE_TTL_SECONDS=3600
```

`MAX_DOWNLOAD_MB` server qayta ishlaydigan hajm. `TELEGRAM_UPLOAD_MB`dan katta
natija `/files/<token>` vaqtinchalik HTTPS havolasi orqali beriladi. Railway
redeploy vaqtida ephemeral fayl o'chishi mumkin, shuning uchun katta fayl
havolasi uzoq muddatli saqlash emas.

AI xizmatlari uchun Railway `Variables` bo'limiga Gemini kalitini kiriting:

```env
AI_PROVIDER=auto
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-flash-latest
GEMINI_IMAGE_MODEL=gemini-2.5-flash-image
STANDARD_AI_DAILY_LIMIT=20
PREMIUM_AI_DAILY_LIMIT=100
```

`AI_PROVIDER=auto` bo'lsa `GEMINI_API_KEY` mavjud paytda Gemini ishlaydi.
OpenAI ishlatmoqchi bo'lsangiz `OPENAI_API_KEY`, `OPENAI_MODEL` va
`OPENAI_IMAGE_MODEL` qiymatlarini ham berishingiz mumkin.
Gemini kvotasi yoki billing limiti tugasa, auto rejimda OpenAI kaliti mavjud
bo'lsa bot avtomatik OpenAI'ga o'tadi.

Bitta AI kaliti barcha AI servislariga ishlatiladi. Bepul tarifda faqat
MP3/musiqa yuklash ochiq. Standard tarif katalogning taxminan yarmiga, Premium
esa barcha xavfsiz va integratsiyasi tayyor servislarga ruxsat beradi. Tashqi
fayl konverteri yoki alohida provayder talab qiladigan servislar katalogda
`sozlash kerak` holatida ko'rsatiladi.

Promo kod yaratish:

```text
/createpromo KOD SUMMA ISHLATISH_LIMITI
```

Foydalanuvchi promo kodni `/promo KOD`, referral linkini `/referral`, tarixni
`/history`, tariflarni `/tarif`, Stars Premium obunani `/premium` orqali
boshqaradi. Bepul tarif bir marta 30 kunga beriladi. Standard va Premium
tariflarini botning ichki balansi yoki Telegram Stars bilan sotib olish mumkin.

## Profil WebApp va xavfsizlik

Profil boshqaruvi bot klaviaturasiga qo'shilmaydi. `WEBAPP_PUBLIC_URL` berilsa bot
menu tugmasi orqali WebApp ochiladi. Telegram WebApp uchun public HTTPS URL kerak;
lokal `http://localhost:8080` Telegram ichidan ochilmaydi.

Railway'da `Generate Domain` bosilgandan keyin platforma
`RAILWAY_PUBLIC_DOMAIN` qiymatini beradi. Bot `WEBAPP_PUBLIC_URL` bo'sh bo'lsa shu
domenni va Railway bergan `PORT`ni avtomatik ishlatadi. Har ishga tushishda
Telegram'dagi `Open` menu tugmasi joriy WebApp manziliga qayta o'rnatiladi.

Public domen va `WEBAPP_PUBLIC_URL` bo'lmasa bot `cloudflared` orqali vaqtinchalik
`*.trycloudflare.com` HTTPS manzilini o'zi yaratadi va Telegram'dagi `Open`
tugmasiga o'rnatadi. Docker image ichiga `cloudflared` qo'shilgan. Lokal Python
bilan ishlatishda `cloudflared` tizimda o'rnatilgan bo'lishi kerak. Bu manzil bot
har qayta ishga tushganda o'zgaradi.

WebApp quyidagilarni qiladi:

- Telegram WebApp `initData` imzosini bot token orqali tekshiradi.
- Ism, familiya, telefon va parol sozlash imkonini beradi.
- Telefonni tasdiqlash uchun foydalanuvchining Telegram chatiga 6 xonali kod yuboradi.
- Parolni faqat PBKDF2 hash ko'rinishida saqlaydi.
- Ichki virtual hisob yaratish va olib tashlash imkonini beradi.

Bu real bank karta/hisob ochmaydi. Real bank karta, karta orqali pul chiqarish yoki
Stars'ni avtomatik fiat pulga aylantirish uchun alohida to'lov provayderi, KYC va
bank integratsiyasi kerak.

Standart sozlamada media davomiyligi 11 soatgacha. Telegramga 49 MB gacha fayl
yuboriladi, undan katta natijaga vaqtinchalik yuklash havolasi yaratiladi.

## 2 GB Local Bot API rejimi

Telegram cloud Bot API 50 MB bilan cheklangan. Taxminan 2 GB fayl yuborish uchun
Local Bot API server ishlatiladi:

1. `https://my.telegram.org` saytidan `api_id` va `api_hash` oling.
2. `.env` ichida `TELEGRAM_API_ID` va `TELEGRAM_API_HASH`ni kiriting.
3. Botni cloud API'dan chiqarish uchun bir marta `logOut` metodini chaqiring.
4. Local konfiguratsiyani ishga tushiring:

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build
```

Local rejim `MAX_DOWNLOAD_MB=1990` bilan ishlaydi. Katta media uchun diskda fayl
hajmidan kamida 2-3 baravar ko'p vaqtinchalik bo'sh joy bo'lishi tavsiya qilinadi.

## Muhim xavfsizlik

Bot tokenini kodga yoki Git tarixiga yozmang. Token chat, skrinshot yoki boshqa ochiq
joyga yuborilgan bo'lsa, BotFather'da `/revoke` qilib yangisini oling. `.env.example`
ichidagi qiymat faqat namuna.

## Docker bilan ishga tushirish

Docker varianti `ffmpeg`ni o'zi o'rnatadi:

```bash
cd /home/inomjon/media_downloader_bot
cp .env.example .env
```

`.env` ichiga yangi `BOT_TOKEN`, o'z Telegram ID'ingizni `ADMIN_IDS` sifatida va
kerakli narxlarni kiriting. Keyin:

```bash
docker compose up -d --build
docker compose logs -f bot
```

## Lokal ishga tushirish

Python 3.11+ va `ffmpeg`/`ffprobe` kerak:

```bash
sudo apt update
sudo apt install -y ffmpeg
cd /home/inomjon/media_downloader_bot
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python -m app.main
```

## Telegram post havolalari

Foydalanuvchi botga Telegram media faylini yuborsa yoki forward qilsa, qo'shimcha
sozlama kerak emas. `https://t.me/channel/123` ko'rinishidagi post havolasini yuklash
uchun:

1. `https://my.telegram.org` orqali `api_id` va `api_hash` oling.
2. `.env` ichida `TELEGRAM_API_ID` va `TELEGRAM_API_HASH`ni kiriting.
3. Private kanal uchun botni kanalga qo'shing.

Public bo'lmagan, o'chirilgan yoki botga ko'rinmaydigan postlar yuklanmaydi.

## YouTube va Instagram cheklovlari

Platforma login/cookies talab qilsa, Netscape formatidagi cookies faylini serverga
joylab, `YTDLP_COOKIES_FILE` bilan yo'lini ko'rsating. Cookies va `.env` Gitga
qo'shilmaydi.

Faqat o'zingizga tegishli yoki yuklashga ruxsatingiz bor materiallardan foydalaning.
Platforma qoidalari va mualliflik huquqiga rioya qilish bot egasi va foydalanuvchi
zimmasida.

## Test

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
.venv/bin/ruff check .
```
