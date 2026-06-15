# Saved Insta Bot

Telegram bot link orqali video/MP3 yuklaydi, qo'shiq nomi yoki ijrochi nomi
bo'yicha musiqa qidiradi, video note tayyorlaydi va video note'ni oddiy videoga
o'tkazadi.

## Asosiy imkoniyatlar

- YouTube, YouTube Music, Instagram, TikTok, SoundCloud, Facebook va X/Twitter linklaridan media yuklash
- Qo'shiq nomi yoki ijrochi nomi bilan MP3 qidirish (`yt-dlp` `ytsearch1`)
- Video sifatini tanlash: 360p, 720p, 1080p yoki MP3
- Video/audio fayldan MP3 qilish
- Videoni Telegram aylana video (`video_note`) qilish
- Aylana videoni ortiqcha effektlarsiz oddiy videoga o'tkazish
- Yuklash tarixi va katta fayllar uchun vaqtinchalik HTTPS link
- Telegram WebApp: profil, telefon tasdiqlash, parol, profil rasmi va so'rovlar tarixi
- Admin WebApp: foydalanuvchini ID/username/ism/telefon bo'yicha qidirish va AI obunani qo'lda faollashtirish

## Pullik oqimlar

Bot ichidagi Stars, balans, avtomatik tarif va promo kod oqimlari olib tashlangan.
Media yuklash va video note funksiyalari bepul ishlaydi.

AI qo'shiq yaratish alohida pullik obuna bo'ladi, lekin hozir avtomatik to'lov
yo'q. Foydalanuvchi adminga murojaat qiladi, admin karta orqali to'lovni
tekshiradi va WebApp admin panelidan AI obunani qo'lda ochadi.

## Bepul AI bo'yicha real variantlar

Haqiqiy "tekin va limitsiz API" amalda yo'q: bepul servislar limit qo'yadi yoki
keyin pullik bo'ladi. Limitsizga yaqin yo'l - modelni o'z serveringizda yuritish.
Bunda API uchun pul to'lanmaydi, lekin server CPU/GPU resursi kerak bo'ladi.

Tavsiya etiladigan local/open-source yo'nalishlar:

- Text-to-speech: `Piper`, `Coqui TTS`
- Ovoz uslubi/effect: `RVC`, `so-vits-svc`
- Musiqa generatsiya: `MusicGen` yoki `AudioCraft`
- Oddiy audio effektlar: `ffmpeg` filterlari

Avval MVP uchun: matn -> TTS vokal -> fon beat/music loop -> ffmpeg mix. Keyin GPU
server bo'lsa MusicGen/RVC qo'shiladi.

## Railway PostgreSQL

Balans kerak emas, lekin profil, tarix va AI obuna yo'qolmasligi uchun PostgreSQL
tavsiya qilinadi:

1. Railway project ichida `+ Add` -> `Database` -> `PostgreSQL`.
2. Bot servisining `Variables` bo'limida:

```env
DATABASE_URL=${{Postgres.DATABASE_URL}}
```

`DATABASE_URL` bo'lmasa bot lokal SQLite ishlatadi.

## WebApp

Telegram ichidagi `Open` tugmasi `WEBAPP_PUBLIC_URL` orqali ishlaydi. Railway'da
public domain bo'lsa bot `RAILWAY_PUBLIC_DOMAIN`dan avtomatik foydalanadi.

WebApp oddiy foydalanuvchiga faqat profil va so'rovlar tarixini ko'rsatadi. Admin
ID `ADMIN_IDS` ichida bo'lsa, admin panel ham chiqadi.

## Docker bilan ishga tushirish

```bash
cd /home/inomjon/media_downloader_bot
cp .env.example .env
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

## Muhim xavfsizlik

Bot tokenini kodga yoki Git tarixiga yozmang. Token chat, skrinshot yoki boshqa
ochiq joyga yuborilgan bo'lsa, BotFather'da `/revoke` qilib yangisini oling.

## Test

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/pytest
```
