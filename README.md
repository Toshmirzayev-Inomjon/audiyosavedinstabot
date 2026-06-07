# Media Downloader Telegram Bot

Bot quyidagilarni bajaradi:

- YouTube va Instagram public havolalaridan video yuklash
- Telegram post havolasidan media yuklash
- Botga yuborilgan yoki forward qilingan video/audio faylni qabul qilish
- Video/audio yoki havolani MP3 formatiga o'tkazish
- Videoni Telegram aylana video (`video_note`) formatiga o'tkazish
- Aylana videoni 16:9 to'rtburchak videoga o'tkazish
- SQLite balans, tranzaksiya tarixi, haq yechish va xatoda avtomatik refund
- Telegram Stars orqali balans to'ldirish
- Admin orqali `/addbalance USER_ID SUMMA` komandasi
- Telegram WebApp orqali profil, telefon tasdiqlash kodi va ichki virtual hisoblar

Stars paketlari `.env` ichidagi `STAR_PACKAGES` orqali boshqariladi. Foydalanuvchi
`O'zim kiritaman` tugmasi orqali ham hisob to'ldira oladi; standart minimal miqdor
`CUSTOM_STAR_MIN=5`, custom kurs esa `STAR_CREDIT_RATE=1000`.

Stars to'lovi kelganda bot avval payment'ni `pending` holatda saqlaydi, 5 soniya
tekshiruv progressini ko'rsatadi va keyin ichki balansga qo'shadi.

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

Standart sozlamada media davomiyligi 11 soatgacha, lekin Telegramga yuboriladigan
har bir tayyor fayl 49 MB'dan oshmasligi kerak. Juda uzun videolar hajm limitiga
sig'masa bot ularni yubora olmaydi.

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
