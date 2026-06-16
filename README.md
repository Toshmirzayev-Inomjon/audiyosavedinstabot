# Saved Insta Bot

Telegram bot link orqali video/MP3 yuklaydi, qo'shiq nomi yoki ijrochi nomi
bo'yicha musiqa qidiradi, video note tayyorlaydi va video note'ni oddiy videoga
o'tkazadi.

## Asosiy imkoniyatlar

- YouTube, YouTube Music, Instagram, TikTok, SoundCloud, Facebook va X/Twitter linklaridan media yuklash
- Qo'shiq nomi yoki ijrochi nomi bilan MP3 qidirish (`yt-dlp` `ytsearch1` + SoundCloud fallback)
- Instagram/TikTok/Facebook/X linklarida metadata bo'lsa qisqa reel audiosi o'rniga to'liq qo'shiqni qidirish
- Voice message orqali qo'shiqni tanish (`AudD`) yoki qo'shiq nomini aytib qidirish (`Hugging Face` ASR)
- Video sifatini tanlash: 360p, 720p, 1080p yoki MP3
- Video/audio fayldan MP3 qilish
- Videoni Telegram aylana video (`video_note`) qilish
- Aylana videoni ortiqcha effektlarsiz oddiy videoga o'tkazish
- Yuklash tarixi va katta fayllar uchun vaqtinchalik HTTPS link
- Telegram WebApp: profil, telefon tasdiqlash, parol, profil rasmi va so'rovlar tarixi
- Telegram admin komandasi: foydalanuvchini qidirish va AI obunani qo'lda faollashtirish
- AI obuna faol bo'lsa matnli promptdan qisqa musiqa generatsiya qilish

YouTube'ning yangi JavaScript challenge'lari uchun Docker image ichida Deno
runtime va `yt-dlp[default]` EJS solver o'rnatiladi.

## Pullik oqimlar

Bot ichidagi Stars, balans, avtomatik tarif va promo kod oqimlari olib tashlangan.
Media yuklash va video note funksiyalari bepul ishlaydi.

AI qo'shiq yaratish alohida pullik obuna bo'ladi, lekin hozir avtomatik to'lov
yo'q. Foydalanuvchi botdagi `/tarif` orqali 30, 90 yoki 365 kunni tanlaydi va
adminga murojaat qiladi. Admin karta orqali to'lovni tekshiradi va botdagi
`/aiactivate USER_ID DAYS` komandasi bilan obunani ochadi.

AI qo'shiq yaratish `/ai` yoki menyudagi `AI qo'shiq / Obuna` orqali ishlaydi.
Foydalanuvchi prompt yozadi, bot Hugging Face MusicGen'dan audio oladi va MP3
qilib yuboradi. Hugging Face ulanishi serverning maxfiy Variables qismida
saqlanadi:

```env
HUGGINGFACE_API_TOKEN=hf_yangi_maxfiy_token
HUGGINGFACE_MUSIC_MODEL=facebook/musicgen-small
HUGGINGFACE_ASR_MODEL=openai/whisper-large-v3-turbo
AUDD_API_TOKEN=
```

Tokenni `.env.example` yoki GitHub ichiga yozmang. Hugging Face Inference
foydalanishi hisob krediti va provider limitlariga bog'liq.

`AUDD_API_TOKEN` ixtiyoriy. U berilsa foydalanuvchi ovozli xabarda qo'shiq
fragmentini yuborganda bot artist/title topishga urinadi. Token bo'lmasa bot
faqat foydalanuvchi ovoz bilan aytgan qo'shiq nomini matnga aylantirib qidiradi.

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

WebApp barcha foydalanuvchilarga profil, tarix va AI obuna holatini ko'rsatadi.
Admin foydalanuvchilarda qo'shimcha admin panel ochiladi: user qidirish,
obunani faollashtirish, admin qo'shish va oxirgi xatolarni ko'rish.
Telegram bot komandalarida ham admin boshqaruvi bor:

```text
/admin USER
/aiactivate USER_ID DAYS
```

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
