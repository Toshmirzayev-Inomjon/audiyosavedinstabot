from __future__ import annotations

# ruff: noqa: E501
from dataclasses import dataclass

PLAN_RANK = {"none": -1, "free": 0, "standard": 1, "premium": 2}


@dataclass(frozen=True, slots=True)
class Service:
    slug: str
    icon: str
    name: str
    description: str
    min_plan: str
    mode: str
    prompt: str = ""
    placeholder: str = "So'rovingizni yozing"
    domains: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Category:
    slug: str
    icon: str
    title: str
    subtitle: str
    color: str
    services: tuple[Service, ...]


def service(
    slug: str,
    icon: str,
    name: str,
    description: str,
    min_plan: str,
    mode: str,
    prompt: str = "",
    placeholder: str = "So'rovingizni yozing",
    domains: tuple[str, ...] = (),
) -> Service:
    return Service(
        slug,
        icon,
        name,
        description,
        min_plan,
        mode,
        prompt,
        placeholder,
        domains,
    )


CATALOG = (
    Category(
        "media",
        "📥",
        "Media va tarmoqlar",
        "Video, audio va bulut xizmatlari",
        "#35a7ff",
        (
            service("instagram_tools", "📱", "Instagram Tools", "Public Reels va postlarni yuklash.", "standard", "media", placeholder="Instagram havolasini kiriting"),
            service("youtube_suite", "🎥", "YouTube Suite", "Video, Shorts va sifat tanlab yuklash.", "standard", "media", placeholder="YouTube havolasini kiriting"),
            service("tiktok_matrix", "🎵", "TikTok Matrix", "Muallif ruxsat bergan public media bilan ishlash.", "standard", "planned"),
            service("telegram_helpers", "🚀", "Telegram Helpers", "Kanal va guruh boshqaruvi uchun yordamchilar.", "standard", "planned"),
            service("pinterest_tumblr", "📌", "Pinterest & Tumblr", "Public rasm va g'oyalarni tartiblash.", "standard", "planned"),
            service("facebook_twitter", "📘", "Facebook & X", "Public post va media havolalarini qayta ishlash.", "premium", "planned"),
            service("music_downloader", "🎧", "Musiqa yuklash", "YouTube havolasidan MP3 tayyorlash. Bepul tarifdagi yagona media xizmati.", "free", "media_audio", placeholder="Musiqa yoki YouTube havolasini kiriting"),
            service("public_media_inspector", "🌐", "Public Media Inspector", "Ochiq sahifadagi media metadata va havolalarni ko'rish.", "premium", "planned"),
            service("official_app_search", "📥", "Official App Search", "Google Play va App Store'dan rasmiy ilovalarni qidirish.", "premium", "ai_web", "Faqat rasmiy ilova do'konlaridan qonuniy havolalarni toping.", "Ilova yoki o'yin nomi", ("play.google.com", "apps.apple.com")),
            service("cloud_transporter", "☁️", "Cloud Transporter", "Foydalanuvchiga tegishli bulut fayllarini Telegramga o'tkazish.", "premium", "planned"),
        ),
    ),
    Category(
        "fun",
        "🃏",
        "Ko'ngilochar",
        "Yumor, ijod va guruh o'yinlari",
        "#a96cff",
        (
            service("demo_invoice", "🧾", "Demo Invoice Designer", "DEMO belgili qonuniy hisob-faktura maketi.", "standard", "local", placeholder="Sotuvchi | Mijoz | Xizmat | Summa"),
            service("voice_changer", "🎭", "Ovoz o'zgartirgich", "Ovozli xabarlarga ijodiy effektlar.", "standard", "planned"),
            service("anonymous_feedback", "🤫", "Anonim Feedback", "Moderatsiyali anonim fikr-mulohaza tizimi.", "standard", "planned"),
            service("chat_storyboard", "💬", "Chat Storyboard", "DEMO belgili hikoya va sahna maketi.", "standard", "planned"),
            service("avatar_restyle", "👥", "Avatar Restyle", "O'zingizga tegishli suratni badiiy uslubga o'tkazish.", "standard", "planned"),
            service("meme_maker", "🗿", "Memes Studio", "Original mem va demotivator g'oyalari.", "premium", "ai_image", "Xavfsiz, original va haqorat qilmaydigan mem rasmi yarating."),
            service("name_meaning", "📝", "Ismlar ma'nosi", "Ism kelib chiqishi va ma'nosi.", "premium", "ai", "Ismning ehtimoliy kelib chiqishi va ma'nosini ehtiyotkor izohlang.", "Ismni kiriting"),
            service("horoscope", "🔮", "Horoscope", "Faqat ko'ngilochar burj talqini.", "premium", "ai", "Bu ko'ngilochar talqin ekanini aytib, ijobiy va zararsiz burj matni yozing.", "Burj va sana"),
            service("sound_effects", "🔊", "Sound Effects", "Royalty-free tovushlar katalogi.", "premium", "ai_web", "Faqat royalty-free yoki ruxsat etilgan tovush manbalarini toping.", "Qanday tovush kerak?", ("freesound.org", "pixabay.com")),
            service("nickname_generator", "👑", "Nickname Generator", "Profil va o'yinlar uchun original nickname.", "premium", "ai", "Berilgan mavzu asosida 20 ta original nickname yarating.", "Ism yoki mavzu"),
            service("wedding_jokes", "💍", "To'y hazillari", "Yengil, kamsitmaydigan test va hazillar.", "premium", "ai", "Kamsitmaydigan, oilaviy auditoriyaga mos original o'zbekcha hazil yoki mini-test yarating."),
            service("randomizer", "🎲", "Randomizer & Dice", "Son, ro'yxat yoki tasodifiy g'olib tanlash.", "premium", "local", placeholder="1,100 yoki Ali,Vali,Sami"),
        ),
    ),
    Category(
        "documents",
        "🛠",
        "Hujjat va konverter",
        "PDF, rasm, audio va fayl vositalari",
        "#ff9f43",
        (
            service("pdf_master", "📄", "PDF Master", "PDF birlashtirish, siqish va parollash.", "standard", "planned"),
            service("office_converter", "📂", "Office Converter", "Word, Excel va PPT formatlarini o'zgartirish.", "standard", "planned"),
            service("image_compressor", "🖼", "Image Compressor", "Rasm hajmini optimallashtirish.", "standard", "planned"),
            service("ocr", "🔍", "OCR", "Rasmdagi matnni ajratib olish.", "standard", "planned"),
            service("audio_transcriber", "🎙", "Audio Transcriber", "Ovozli xabarni matnga aylantirish.", "standard", "planned"),
            service("text_to_speech", "🗣", "Text-to-Speech", "Matnni tabiiy ovozga aylantirish.", "premium", "planned"),
            service("background_remover", "✂️", "Background Remover", "Rasm fonini avtomatik olib tashlash.", "premium", "planned"),
            service("qr_barcode", "🏁", "QR & Barcode", "Matn yoki havoladan QR-kod yaratish.", "premium", "local_image", placeholder="QR ichiga yoziladigan matn yoki havola"),
            service("archive_manager", "📦", "Archive Manager", "ZIP arxiv yaratish va ochish.", "premium", "planned"),
            service("font_stylist", "✍️", "Font Stylist", "Matnni turli dekorativ uslublarga o'tkazish.", "premium", "local", placeholder="Matnni kiriting"),
            service("video_to_gif", "🎞", "Video-to-GIF", "Videoni GIF formatiga o'tkazish.", "premium", "planned"),
            service("watermark_add", "🏷", "Watermark Add", "O'zingizga tegishli media faylga logotip qo'shish.", "premium", "planned"),
            service("exif_remover", "🛡", "EXIF Remover", "Rasmdagi GPS va qurilma metadatasini o'chirish.", "premium", "planned"),
        ),
    ),
    Category(
        "ai",
        "🤖",
        "Sun'iy intellekt",
        "Lokal fallback va tashqi AI xizmatlari",
        "#00c2a8",
        (
            service("ai_chat", "💬", "AI Chat", "Savol-javob, reja va matnlar.", "standard", "ai", "Foydali, aniq va o'zbek tilida javob bering."),
            service("ai_vision", "👁", "AI Vision", "Rasm va hujjatlarni tahlil qilish.", "standard", "planned"),
            service("ai_image", "🎨", "AI Image Generator", "Matn asosida original rasm yaratish.", "standard", "ai_image", "Foydalanuvchi tavsifiga mos original va xavfsiz rasm yarating."),
            service("ai_logo", "📐", "AI Logo Maker", "Biznes va kanal uchun original logo.", "standard", "ai_image", "Minimal, original, professional logo yarating. Mavjud brend logotipini ko'chirmang."),
            service("code_fixer", "💻", "Code Fixer & Writer", "Kod xatolarini topish va tushuntirish.", "standard", "ai", "Koddagi xatoni toping, xavfsiz tuzatish va qisqa izoh bering.", "Kod va xato matni"),
            service("resume_builder", "📄", "AI Resume Builder", "Professional CV va rezyume.", "premium", "ai", "Berilgan ma'lumotdan rostgo'y, professional va ATS-friendly CV tayyorlang."),
            service("summarizer", "📉", "Text Summarizer", "Uzun matnni qisqa va aniq xulosa qilish.", "premium", "ai", "Matnning asosiy fikrlarini yo'qotmasdan qisqa xulosa qiling."),
            service("grammar_ai", "🔤", "Grammar AI", "Imlo va uslub xatolarini to'g'rilash.", "premium", "ai", "Matn tilini saqlab, imlo va grammatikani tuzating; ma'noni o'zgartirmang."),
            service("brand_generator", "💡", "Slogan & Brand", "Nom, slogan va brend g'oyalari.", "premium", "ai", "Original brend nomlari va sloganlar taklif qiling; mavjud mashhur brendlarni ko'chirmang."),
            service("poems", "🎼", "AI Poems", "Original she'r va qo'shiq g'oyasi.", "premium", "ai", "Original matn yozing. Mavjud qo'shiq yoki ijodkor uslubini nusxalamang."),
        ),
    ),
    Category(
        "weather",
        "🌤",
        "Ob-havo va geo",
        "Jonli ma'lumot va geografik vositalar",
        "#4cc9f0",
        (
            service("live_weather", "🌤", "Live Weather", "Joriy ob-havo va harorat.", "standard", "ai_web", "Joriy ob-havoni aniq sana va manbalar bilan toping.", "Shahar nomi"),
            service("weather_forecast", "📅", "Weather Forecast", "7 yoki 14 kunlik prognoz.", "standard", "ai_web", "Ob-havo prognozini ishonchli manbalar bilan jadval ko'rinishida bering.", "Shahar va kunlar soni"),
            service("magnetic_storms", "🌋", "Magnetic Storms", "Geomagnit bo'ronlar ma'lumoti.", "standard", "ai_web", "Geomagnit faollikni ilmiy manbalardan topib, noaniqlikni ko'rsating.", domains=("swpc.noaa.gov", "nasa.gov")),
            service("air_quality", "💨", "Air Quality", "AQI va havo sifati.", "standard", "ai_web", "Shahar AQI ko'rsatkichini sana va manba bilan toping."),
            service("natural_disasters", "🚨", "Natural Disasters", "Zilzila va tabiiy hodisalar.", "premium", "ai_web", "Eng yangi rasmiy tabiiy ofat ma'lumotlarini toping.", domains=("usgs.gov", "reliefweb.int", "wmo.int")),
            service("world_time", "⏰", "World Time", "IANA vaqt zonasi bo'yicha joriy vaqt.", "premium", "local", placeholder="Masalan: Asia/Tokyo"),
            service("qibla_compass", "🧭", "Qibla Compass", "Koordinata bo'yicha qibla yo'nalishi.", "premium", "local", placeholder="Kenglik,uzunlik masalan 39.65,66.96"),
        ),
    ),
    Category(
        "education",
        "🎓",
        "Ta'lim va tillar",
        "O'qish, tarjima va fan yordamchilari",
        "#ffd166",
        (
            service("translator", "🔄", "Smart Translator", "Ko'p tilli tarjima.", "standard", "ai", "Matnni foydalanuvchi so'ragan tilga tabiiy tarjima qiling.", "Til va tarjima qilinadigan matn"),
            service("e_library", "📚", "E-Library", "Qonuniy ochiq kitob manbalarini qidirish.", "standard", "ai_web", "Faqat qonuniy public-domain yoki rasmiy kitob havolalarini toping.", "Kitob nomi yoki muallif", ("gutenberg.org", "archive.org", "openlibrary.org")),
            service("flashcards", "🎴", "English Flashcards", "So'z yodlash kartalari.", "standard", "ai", "Mavzu bo'yicha inglizcha-o'zbekcha 15 ta flashcard yarating."),
            service("math_solver", "🧮", "Math Solver", "Misol va tenglamalarni bosqichma-bosqich yechish.", "standard", "ai", "Masalani bosqichma-bosqich yeching va yakuniy javobni tekshiring."),
            service("chemistry_lab", "🧪", "Chemistry Lab", "Davriy jadval va reaksiyalar.", "standard", "ai", "Ta'limiy kimyo savoliga xavfsiz javob bering; xavfli tajriba ko'rsatmalarini bermang."),
            service("physics_formulas", "🧲", "Physics Formulas", "Fizika formulalari va birliklar.", "premium", "ai", "Fizika masalasini formulalar, birliklar va hisob bilan tushuntiring."),
            service("history_calendar", "📜", "History Calendar", "Tarixda bugun bo'lgan voqealar.", "premium", "ai_web", "Berilgan sana uchun tekshiriladigan tarixiy voqealarni manbalar bilan toping."),
            service("geography_quiz", "🗺", "Geography Quiz", "Bayroq va poytaxtlar viktorinasi.", "premium", "ai", "10 savollik geografiya viktorinasi yarating; javoblarni oxirida bering."),
            service("uzbek_spelling", "🇺🇿", "Uzbek Spelling", "O'zbek imlo va uslub yordamchisi.", "premium", "ai", "O'zbek lotin imlosida matnni tekshirib, tuzatish sababini ayting."),
            service("iq_tests", "🧠", "IQ & Logic", "Mantiqiy mini-testlar.", "premium", "ai", "Yoshga mos 10 ta original mantiqiy savol va javob yarating."),
            service("speed_reading", "📖", "Speed Reading", "Tez o'qish mashqlari.", "premium", "ai", "Xavfsiz ko'z tanaffuslari bilan tez o'qish mashg'uloti tuzing."),
            service("audiobooks", "🗣", "Audiobooks", "Qonuniy audio kitob manbalari.", "premium", "ai_web", "Faqat public-domain yoki rasmiy audio kitob havolalarini toping."),
            service("coding_basics", "🛠", "Coding Basics", "Dasturlash bo'yicha interaktiv dars.", "premium", "ai", "Boshlovchiga mos qisqa dars, misol va mashq tuzing."),
            service("quotes", "💎", "Quotes & Philosophy", "Iqtiboslar va falsafiy sharh.", "premium", "ai", "Manbasi aniq bo'lmasa iqtibosni mashhur shaxsga nisbat bermang; original fikr yozing."),
            service("biology_world", "🧬", "Biology World", "Biologiya va anatomiya ma'lumotnomasi.", "premium", "ai", "Ta'limiy biologiya javobi bering; tibbiy tashxis qo'ymang."),
            service("astronomy", "🌌", "Astronomy Guide", "Kosmos va astronomiya.", "premium", "ai_web", "Astronomiya savoliga ilmiy va yangilangan manbalar bilan javob bering.", domains=("nasa.gov", "esa.int")),
        ),
    ),
    Category(
        "business",
        "📊",
        "Biznes va finans",
        "Hisob-kitob, bozor va tadbirkorlik",
        "#06d6a0",
        (
            service("currency_rates", "💵", "Currency Rates", "Joriy valyuta kurslari.", "standard", "ai_web", "Joriy valyuta kursini sana va rasmiy manba bilan toping.", domains=("cbu.uz", "ecb.europa.eu")),
            service("crypto_tracker", "🪙", "Crypto Tracker", "Kripto narxlari va bozor ma'lumoti.", "standard", "ai_web", "Joriy kripto narxini manba va vaqt bilan bering; investitsiya kafolati bermang.", domains=("coingecko.com", "coinmarketcap.com")),
            service("stock_market", "📈", "Stock Market", "Aksiya narxlari va kompaniya ma'lumoti.", "standard", "ai_web", "Joriy bozor ma'lumotini manba va vaqt bilan bering; bu investitsiya maslahati emasligini ayting."),
            service("expense_tracker", "👛", "Expense Tracker", "Daromad va xarajatlar daftari.", "standard", "planned"),
            service("loan_calculator", "🧮", "Loan Calculator", "Kreditning taxminiy oylik to'lovi.", "standard", "local", placeholder="Summa, yillik foiz, oylar masalan 100000000,25,24"),
            service("tax_calculator", "📝", "Tax Calculator", "Soliq bo'yicha ma'lumot va hisob.", "premium", "ai_web", "Faqat rasmiy amaldagi soliq manbalaridan foydalaning va professional maslahat emasligini ayting.", domains=("soliq.uz", "lex.uz")),
            service("inflation_calculator", "📉", "Inflation Calculator", "Pul qiymatining vaqt bo'yicha o'zgarishi.", "premium", "ai_web", "Rasmiy inflyatsiya ma'lumotlari asosida taxminiy hisob bering."),
            service("atm_finder", "🏦", "ATM Finder", "Yaqin bankomatlarni topish bo'yicha yordam.", "premium", "ai_web", "Foydalanuvchi shahri bo'yicha rasmiy bank xaritalarini toping."),
            service("business_ideas", "💡", "Business Ideas", "Bozor va resursga mos biznes g'oyalari.", "premium", "ai", "Budjet, hudud va ko'nikmaga mos realistik biznes g'oyalarini risklari bilan bering."),
            service("gold_metals", "👑", "Gold & Metals", "Oltin va metall narxlari.", "premium", "ai_web", "Joriy metall narxlarini vaqt va manba bilan bering."),
            service("invoice_generator", "🧾", "Invoice Generator", "Qonuniy hisob-faktura matni.", "premium", "local", placeholder="Sotuvchi | Mijoz | Xizmat | Summa"),
            service("freelance_hub", "💻", "Freelance Hub", "Buyurtma tahlili va taklif yozish.", "premium", "ai", "Freelance buyurtmani tahlil qilib, rostgo'y va professional taklif matni yozing."),
        ),
    ),
    Category(
        "travel",
        "✈️",
        "Sayohat va logistika",
        "Transport, mehmonxona va jo'natmalar",
        "#ef476f",
        (
            service("flight_search", "✈️", "Flight Search", "Rasmiy avia yo'nalish va narx havolalari.", "standard", "ai_web", "Yo'nalish va sanaga mos rasmiy yoki ishonchli avia havolalarni toping; narx o'zgarishini ayting."),
            service("train_schedule", "🚂", "Train Schedule", "Poezd jadvali va rasmiy bilet havolalari.", "standard", "ai_web", "Rasmiy poezd jadvali va bilet manbasini toping."),
            service("postal_tracking", "📦", "Postal Tracking", "Rasmiy tracking sahifasini topish.", "standard", "ai_web", "Tracking kodni oshkor qilmasdan rasmiy kuryer kuzatuv sahifasini toping."),
            service("hotel_search", "🏨", "Hotel Search", "Mehmonxona variantlarini solishtirish.", "standard", "ai_web", "Hudud, sana va budjet bo'yicha variantlarni manbalar bilan toping."),
            service("country_guide", "🌍", "Country Guide", "Viza va sayohat qoidalari.", "premium", "ai_web", "Faqat rasmiy elchixona va hukumat manbalaridan joriy qoidalarni toping; sanani ko'rsating."),
            service("fuel_prices", "⛽", "Fuel Prices", "Yoqilg'i narxlari va stansiyalar.", "premium", "ai_web", "Hudud bo'yicha joriy yoqilg'i ma'lumotlarini manba bilan toping."),
            service("speedtest", "⚡", "Speedtest", "Qurilmada internet tezligini tekshirish.", "premium", "planned"),
            service("ip_domain_info", "🖥", "IP & Domain Info", "Public IP va domen texnik ma'lumoti.", "premium", "ai_web", "Faqat public WHOIS/DNS ma'lumotlarini izohlang; shaxsiy ma'lumot qidirmang."),
        ),
    ),
    Category(
        "health",
        "🏥",
        "Sog'liq va sport",
        "Ta'limiy sog'liq va mashg'ulot vositalari",
        "#ff6b6b",
        (
            service("bmi", "⚖️", "BMI Calculator", "Bo'y va vazndan BMI hisoblash.", "standard", "local", placeholder="Vazn kg, bo'y metr masalan 70,1.75"),
            service("water_reminder", "💧", "Water Reminder", "Suv ichish eslatmalari.", "standard", "planned"),
            service("calorie_counter", "🍏", "Calorie Counter", "Taomlarning taxminiy kaloriyasi.", "standard", "ai_web", "Ishonchli oziqlanish manbalari asosida taxminiy kaloriya bering; tibbiy tavsiya bermang.", domains=("fdc.nal.usda.gov", "who.int")),
            service("medicine_guide", "💊", "Medicine Guide", "Dori haqida rasmiy ma'lumot.", "standard", "ai_web", "Faqat rasmiy dori ma'lumotini toping. Tashxis, retsept yoki o'zboshimcha almashtirish tavsiyasi bermang.", domains=("who.int", "fda.gov", "ema.europa.eu")),
            service("workout_planner", "🏋️", "Workout Planner", "Darajaga mos mashq rejasi.", "premium", "ai", "Sog'liq cheklovlarini so'rab, xavfsiz umumiy mashq rejasi tuzing; og'riqda to'xtashni ayting."),
            service("sleep_calculator", "🛌", "Sleep Calculator", "Uyqu sikliga mos vaqtlar.", "premium", "ai", "Uyqu sikli taxminiy ekanini aytib, xavfsiz uyqu jadvali tuzing."),
            service("first_aid", "🚑", "First Aid Guide", "Favqulodda vaziyat uchun umumiy qo'llanma.", "premium", "ai_web", "Avval mahalliy tez yordamga qo'ng'iroq qilishni ayting. Faqat rasmiy birinchi yordam manbalaridan qisqa ko'rsatma bering.", domains=("who.int", "redcross.org", "nhs.uk")),
        ),
    ),
    Category(
        "security",
        "🔐",
        "Xavfsizlik va admin",
        "Hisob himoyasi va boshqaruv",
        "#8d99ae",
        (
            service("password_generator", "🔑", "Password Generator", "Kuchli tasodifiy parol yaratish.", "standard", "local", placeholder="Uzunligi, masalan 20"),
            service("spam_detector", "💣", "Spam Attack Detector", "SMS va xabar spam belgilarini aniqlash bo'yicha himoya.", "standard", "ai", "Himoyaviy tavsiya bering; hujum qilish yoki chetlab o'tish yo'lini bermang."),
            service("safe_link", "🔗", "Safe Link Inspector", "Havolaning xavfsizlik belgilarini tekshirish.", "standard", "ai_web", "Public manbalar asosida havola xavf belgilarini tushuntiring; havolani ochishni kafolatlamang."),
            service("admin_manager", "⚙️", "Admin Panel Manager", "Guruh moderatsiyasi va reklama filtrlari.", "premium", "planned"),
            service("feedback_system", "📮", "Feedback System", "Foydalanuvchi va admin o'rtasida aloqa.", "premium", "planned"),
        ),
    ),
)

SERVICES = {
    item.slug: item
    for category in CATALOG
    for item in category.services
}


def plan_allows(active_plan: str | None, required_plan: str) -> bool:
    return PLAN_RANK.get(active_plan or "none", -1) >= PLAN_RANK[required_plan]


def serialize_catalog(
    active_plan: str | None,
    *,
    ai_configured: bool,
) -> list[dict]:
    result = []
    for category in CATALOG:
        items = []
        for item in category.services:
            configured = item.mode not in {"ai", "ai_web", "ai_image", "planned"} or ai_configured
            ready = configured
            items.append(
                {
                    "slug": item.slug,
                    "icon": item.icon,
                    "name": item.name,
                    "description": item.description,
                    "min_plan": item.min_plan,
                    "mode": item.mode,
                    "unlocked": plan_allows(active_plan, item.min_plan),
                    "ready": ready,
                    "configured": configured,
                    "placeholder": item.placeholder,
                }
            )
        result.append(
            {
                "slug": category.slug,
                "icon": category.icon,
                "title": category.title,
                "subtitle": category.subtitle,
                "color": category.color,
                "services": items,
            }
        )
    return result
