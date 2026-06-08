from __future__ import annotations

import base64
import io
import re
import textwrap
from dataclasses import dataclass
from urllib.parse import quote

import aiohttp


class AIServiceError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        quota_exceeded: bool = False,
    ) -> None:
        super().__init__(message)
        self.quota_exceeded = quota_exceeded


@dataclass(frozen=True, slots=True)
class AIResult:
    text: str
    sources: tuple[dict[str, str], ...] = ()


class AIService:
    def __init__(
        self,
        *,
        provider: str,
        openai_api_key: str | None,
        openai_model: str,
        openai_image_model: str,
        gemini_api_key: str | None,
        gemini_model: str,
        gemini_image_model: str,
    ) -> None:
        self.provider = provider
        self.openai_api_key = openai_api_key
        self.openai_model = openai_model
        self.openai_image_model = openai_image_model
        self.gemini_api_key = gemini_api_key
        self.gemini_model = gemini_model
        self.gemini_image_model = gemini_image_model

    @property
    def active_provider(self) -> str:
        if self.provider == "auto":
            return "local"
        return self.provider

    @property
    def configured(self) -> bool:
        if self.active_provider == "local":
            return True
        if self.active_provider == "gemini":
            return bool(self.gemini_api_key)
        if self.active_provider == "openai":
            return bool(self.openai_api_key)
        return False

    def _openai_headers(self) -> dict[str, str]:
        if not self.openai_api_key:
            raise AIServiceError("OPENAI_API_KEY serverda sozlanmagan")
        return {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json",
        }

    def _gemini_headers(self) -> dict[str, str]:
        if not self.gemini_api_key:
            raise AIServiceError("GEMINI_API_KEY serverda sozlanmagan")
        return {
            "X-goog-api-key": self.gemini_api_key,
            "Content-Type": "application/json",
        }

    def _gemini_url(self, model: str) -> str:
        model_name = model if model.startswith("models/") else f"models/{model}"
        return (
            "https://generativelanguage.googleapis.com/v1beta/"
            f"{quote(model_name, safe='/')}:generateContent"
        )

    @property
    def _can_fallback_to_openai(self) -> bool:
        return self.provider == "auto" and bool(self.openai_api_key)

    @property
    def _can_fallback_to_local(self) -> bool:
        return self.provider == "auto"

    async def respond(
        self,
        *,
        user_input: str,
        instructions: str,
        web_search: bool = False,
        domains: tuple[str, ...] = (),
    ) -> AIResult:
        if self.active_provider == "gemini":
            try:
                return await self._respond_gemini(
                    user_input=user_input,
                    instructions=instructions,
                    web_search=web_search,
                    domains=domains,
                )
            except AIServiceError:
                if not self._can_fallback_to_openai:
                    if self._can_fallback_to_local:
                        return self._respond_local(
                            user_input=user_input,
                            instructions=instructions,
                            web_search=web_search,
                            domains=domains,
                        )
                    raise
                return await self._respond_openai(
                    user_input=user_input,
                    instructions=instructions,
                    web_search=web_search,
                    domains=domains,
                )
        if self.active_provider == "openai":
            try:
                return await self._respond_openai(
                    user_input=user_input,
                    instructions=instructions,
                    web_search=web_search,
                    domains=domains,
                )
            except AIServiceError:
                if not self._can_fallback_to_local:
                    raise
                return self._respond_local(
                    user_input=user_input,
                    instructions=instructions,
                    web_search=web_search,
                    domains=domains,
                )
        if self.active_provider == "local":
            return self._respond_local(
                user_input=user_input,
                instructions=instructions,
                web_search=web_search,
                domains=domains,
            )
        raise AIServiceError("AI API kaliti serverda sozlanmagan")

    def _respond_local(
        self,
        *,
        user_input: str,
        instructions: str,
        web_search: bool,
        domains: tuple[str, ...],
    ) -> AIResult:
        text = self._local_text(user_input, instructions, web_search)
        sources = (
            tuple(
                {
                    "url": f"https://{domain}",
                    "title": domain,
                }
                for domain in domains[:8]
            )
            if domains
            else ()
        )
        return AIResult(text=text, sources=sources)

    def _local_text(
        self,
        user_input: str,
        instructions: str,
        web_search: bool,
    ) -> str:
        value = " ".join(user_input.strip().split())
        lowered = (instructions + " " + value).lower()
        header = "Lokal AI rejimi: API kalitisiz soddalashtirilgan javob."
        if web_search:
            header += " Jonli internet qidiruvi o'rniga lokal taxminiy yordam beriladi."

        slug = self._service_slug(instructions)
        planned = self._local_planned_service(slug, value)
        if planned:
            return f"{header}\n\n{planned}"
        if any(word in lowered for word in ("summarizer", "xulosa", "qisqa")):
            return f"{header}\n\n{self._local_summary(value)}"
        if any(word in lowered for word in ("grammar", "imlo", "grammatik")):
            return f"{header}\n\n{self._local_grammar(value)}"
        if "nickname" in lowered:
            return f"{header}\n\n{self._local_nicknames(value)}"
        if any(word in lowered for word in ("brand", "slogan", "brend")):
            return f"{header}\n\n{self._local_brand(value)}"
        if any(word in lowered for word in ("math", "tenglama", "misol")):
            return f"{header}\n\n{self._local_math(value)}"
        if any(word in lowered for word in ("code", "kod", "xato")):
            return f"{header}\n\n{self._local_code(value)}"
        if any(word in lowered for word in ("resume", "cv", "rezyume")):
            return f"{header}\n\n{self._local_resume(value)}"
        if any(word in lowered for word in ("translator", "tarjima")):
            return f"{header}\n\n{self._local_translate(value)}"
        if any(word in lowered for word in ("weather", "ob-havo")):
            return f"{header}\n\n{self._local_weather(value)}"
        if any(
            word in lowered
            for word in ("currency", "crypto", "stock", "gold", "market", "kurs")
        ):
            return f"{header}\n\n{self._local_market(value)}"
        if any(
            word in lowered
            for word in ("medicine", "first aid", "calorie", "sog'liq", "dori")
        ):
            return f"{header}\n\n{self._local_health(value)}"
        if any(
            word in lowered
            for word in ("safe link", "spam", "security", "xavfsiz")
        ):
            return f"{header}\n\n{self._local_security(value)}"
        if any(word in lowered for word in ("quiz", "viktorina")):
            return f"{header}\n\n{self._local_quiz(value)}"
        if any(word in lowered for word in ("poem", "she'r", "lyrics")):
            return f"{header}\n\n{self._local_poem(value)}"
        return f"{header}\n\n{self._local_general(value)}"

    def _service_slug(self, instructions: str) -> str:
        match = re.search(r"Service slug:\s*([a-z0-9_]+)", instructions)
        return match.group(1) if match else ""

    def _local_planned_service(self, slug: str, value: str) -> str:
        if slug in {
            "tiktok_matrix",
            "facebook_twitter",
            "pinterest_tumblr",
            "public_media_inspector",
        }:
            return (
                "Public media yordamchisi:\n"
                f"- Havola: {value or 'havola kiritilmagan'}\n"
                "- Muallif ruxsatisiz yopiq yoki shaxsiy kontent yuklanmaydi.\n"
                "- Public havola bo'lsa Video yuklab olish bo'limida ham sinab ko'ring.\n"
                "- Natija: platforma, havola turi va xavfsiz yuklash bo'yicha yo'l-yo'riq tayyor."
            )
        if slug == "telegram_helpers":
            return (
                "Telegram admin yordamchisi:\n"
                "- Avto-salom matni\n"
                "- Reklama/so'kinish uchun filtr so'zlar ro'yxati\n"
                "- Adminlarga haftalik reja\n\n"
                f"Taklif: {value or 'guruh qoidalari va maqsadini kiriting'}"
            )
        if slug == "cloud_transporter":
            return (
                "Cloud Transporter lokal rejimi:\n"
                "- Google Drive/Dropbox public havolasini tekshiradi.\n"
                "- Fayl egasining ruxsati bo'lishi kerak.\n"
                "- Katta fayllar uchun bot vaqtinchalik link berishi mumkin.\n\n"
                f"Havola yoki izoh: {value[:500]}"
            )
        if slug == "voice_changer":
            return (
                "Ovoz effekt rejasi:\n"
                "- Robot: pitch past, tezlik 0.95\n"
                "- Multfilm: pitch yuqori, tezlik 1.08\n"
                "- Kino ovozi: bass kuchaytirish, echo ozgina\n\n"
                "Audio fayl yuborish UI ulanmaguncha bu lokal preset tavsiyasi."
            )
        if slug == "anonymous_feedback":
            return (
                "Anonim feedback matni moderatsiyadan o'tkazildi:\n"
                f"{value[:900] or 'Xabar kiriting'}\n\n"
                "Haqorat, shaxsiy ma'lumot yoki tahdid bo'lsa yuborilmaydi."
            )
        if slug == "chat_storyboard":
            return self._local_storyboard(value)
        if slug == "avatar_restyle":
            return (
                "Avatar restyle prompti:\n"
                f"{value or 'Portret'} - clean vector avatar, soft light, "
                "original style, no impersonation.\n\n"
                "Rasm yaratish uchun AI Image servisidan ham foydalaning."
            )
        if slug in {
            "pdf_master",
            "office_converter",
            "image_compressor",
            "ocr",
            "audio_transcriber",
            "text_to_speech",
            "background_remover",
            "archive_manager",
            "video_to_gif",
            "watermark_add",
            "exif_remover",
        }:
            return self._local_document_tool(slug, value)
        if slug == "ai_vision":
            return (
                "AI Vision lokal rejimi:\n"
                "- Rasm tavsifini matn qilib yozsangiz tahlil qilaman.\n"
                "- Misol/masala matnini kiritsangiz bosqichma-bosqich yechaman.\n\n"
                f"Kiritilgan tavsif: {value[:900] or 'Rasm tavsifini yozing'}"
            )
        if slug == "expense_tracker":
            return self._local_expense_tracker(value)
        if slug == "speedtest":
            return (
                "Speedtest lokal yo'riqnomasi:\n"
                "1. Wi-Fi yoki mobil internetni tanlang.\n"
                "2. 3 marta ping/download/upload o'lchang.\n"
                "3. O'rtacha natijani yozing.\n\n"
                "Baholash: ping < 50ms yaxshi, download 20Mbps+ kundalik ishlar uchun yetarli."
            )
        if slug == "water_reminder":
            return self._local_water_reminder(value)
        if slug == "admin_manager":
            return (
                "Admin panel sozlama paketi:\n"
                "- /rules: guruh qoidalari\n"
                "- /warn: ogohlantirish\n"
                "- /mute: vaqtincha cheklash\n"
                "- Reklama filtri: link, @username, spam kalit so'zlari\n\n"
                f"Guruh maqsadi: {value[:500] or 'maqsad kiritilmagan'}"
            )
        if slug == "feedback_system":
            return (
                "Feedback tizimi tayyor matni:\n"
                "Foydalanuvchi xabari adminlarga ID bilan boradi, javob esa bot orqali qaytadi.\n"
                "Shaxsiy ma'lumotlar minimal saqlanadi.\n\n"
                f"Namuna: {value[:700] or 'feedback matnini kiriting'}"
            )
        return ""

    def _local_storyboard(self, value: str) -> str:
        topic = value or "mijoz va admin suhbati"
        return (
            "DEMO chat storyboard:\n"
            f"1. Mijoz: {topic} bo'yicha savol beradi.\n"
            "2. Admin: qisqa va aniq javob beradi.\n"
            "3. Mijoz: narx yoki muddatni so'raydi.\n"
            "4. Admin: keyingi qadamni tushuntiradi.\n\n"
            "Bu haqiqiy chat emas, faqat demo ssenariy."
        )

    def _local_document_tool(self, slug: str, value: str) -> str:
        names = {
            "pdf_master": "PDF birlashtirish/siqish/parollash",
            "office_converter": "Office fayl konvertatsiyasi",
            "image_compressor": "Rasm siqish",
            "ocr": "Rasm matnini ajratish",
            "audio_transcriber": "Audio transkripsiya",
            "text_to_speech": "Matndan ovoz",
            "background_remover": "Fon olib tashlash",
            "archive_manager": "ZIP arxiv",
            "video_to_gif": "Video-to-GIF",
            "watermark_add": "Watermark qo'shish",
            "exif_remover": "EXIF metadata tozalash",
        }
        return (
            f"{names.get(slug, 'Hujjat vositasi')} lokal rejimi:\n"
            f"- Kiruvchi ma'lumot: {value[:500] or 'fayl tavsifi kiritilmagan'}\n"
            "- Fayl yuklash UI ulanmaguncha bot format, xavfsizlik va sozlama rejasini beradi.\n"
            "- Shaxsiy fayllarni yuborishda faqat o'zingizga tegishli materiallardan foydalaning.\n"
            "- Tavsiya: kerakli format, sifat va yakuniy nomni yozing."
        )

    def _local_expense_tracker(self, value: str) -> str:
        income = 0
        expense = 0
        for amount in re.findall(r"[-+]?\d+(?:[.,]\d+)?", value):
            number = float(amount.replace(",", "."))
            if number >= 0:
                income += number
            else:
                expense += abs(number)
        balance = income - expense
        return (
            "Expense tracker natijasi:\n"
            f"- Daromad yig'indisi: {income:,.0f}\n"
            f"- Xarajat yig'indisi: {expense:,.0f}\n"
            f"- Qoldiq: {balance:,.0f}\n\n"
            "Format tavsiya: +500000 oylik, -25000 ovqat, -12000 transport"
        )

    def _local_water_reminder(self, value: str) -> str:
        numbers = [
            float(item.replace(",", "."))
            for item in re.findall(r"\d+(?:[.,]\d+)?", value)
        ]
        weight = numbers[0] if numbers else 70
        liters = max(1.5, min(4.5, weight * 0.035))
        return (
            "Suv ichish rejasi:\n"
            f"- Taxminiy kunlik norma: {liters:.1f} litr\n"
            "- 09:00, 11:00, 13:00, 15:00, 17:00, 19:00 da kichik porsiya\n"
            "- Sport/issiq havoda ehtiyoj oshishi mumkin.\n"
            "Bu tibbiy ko'rsatma emas."
        )

    def _local_weather(self, value: str) -> str:
        return (
            "Ob-havo lokal rejimi:\n"
            f"- Joy: {value or 'shahar kiritilmagan'}\n"
            "- Jonli harorat API kalitisiz olinmaydi.\n"
            "- Reja: ertalab/kechqurun harorat farqi, shamol va "
            "yog'ingarchilikni tekshiring.\n"
            "- Aniq prognoz uchun rasmiy meteorologiya manbasini solishtiring."
        )

    def _local_market(self, value: str) -> str:
        return (
            "Bozor ma'lumoti lokal rejimi:\n"
            f"- So'rov: {value or 'aktiv/valyuta nomi kiritilmagan'}\n"
            "- Jonli narx API kalitisiz olinmaydi.\n"
            "- Risk: narxlar tez o'zgaradi, qaror qabul qilishdan oldin "
            "rasmiy manbani tekshiring.\n"
            "- Bu investitsiya maslahati emas."
        )

    def _local_health(self, value: str) -> str:
        return (
            "Sog'liq lokal rejimi:\n"
            f"- Savol: {value[:500] or 'savol kiritilmagan'}\n"
            "- Favqulodda holatda 103 yoki mahalliy tez yordamga murojaat qiling.\n"
            "- Dori, tashxis va davolashni shifokor bilan tasdiqlang.\n"
            "- Men faqat umumiy ma'lumot va xavfsiz yo'l-yo'riq bera olaman."
        )

    def _local_security(self, value: str) -> str:
        return (
            "Xavfsizlik tekshiruvi:\n"
            f"- Kiruvchi ma'lumot: {value[:500] or 'havola/xabar kiritilmagan'}\n"
            "- Shubhali belgilar: qisqa link, imlo xatolari, shoshiltirish, parol/kod so'rash.\n"
            "- Kod, parol va karta ma'lumotlarini hech kimga yubormang.\n"
            "- Havolani ochishdan oldin domenni tekshiring."
        )

    def _local_summary(self, value: str) -> str:
        sentences = re.split(r"(?<=[.!?])\s+", value)
        useful = [sentence.strip() for sentence in sentences if sentence.strip()]
        if not useful:
            return "Xulosa qilish uchun matn kiriting."
        summary = useful[:3]
        return "Qisqa xulosa:\n" + "\n".join(f"- {item}" for item in summary)

    def _local_grammar(self, value: str) -> str:
        cleaned = re.sub(r"\s+", " ", value).strip()
        if cleaned:
            cleaned = cleaned[0].upper() + cleaned[1:]
        cleaned = re.sub(r"\s+([,.!?])", r"\1", cleaned)
        if cleaned and cleaned[-1] not in ".!?":
            cleaned += "."
        return (
            "Tahrirlangan matn:\n"
            f"{cleaned or 'Matn kiriting.'}\n\n"
            "Eslatma: lokal rejim chuqur grammatik tahlil qilmaydi."
        )

    def _local_nicknames(self, value: str) -> str:
        base = re.sub(r"[^a-zA-Z0-9]+", "", value.title()) or "User"
        suffixes = ("Pro", "X", "Uz", "Prime", "One", "Wave", "Neo", "Max")
        names = [f"{base}{suffix}" for suffix in suffixes]
        return "Nickname variantlari:\n" + "\n".join(f"- {name}" for name in names)

    def _local_brand(self, value: str) -> str:
        words = [word.capitalize() for word in re.findall(r"[A-Za-z0-9']+", value)]
        root = words[0] if words else "Nova"
        ideas = (
            f"{root}Hub - tezkor va ishonchli xizmatlar markazi",
            f"{root}Flow - ishni yengillashtiradigan yechim",
            f"{root}Line - sodda, zamonaviy va aniq brend",
            f"{root}Pro - premium xizmat va sifat belgisi",
        )
        return "Brend g'oyalari:\n" + "\n".join(f"- {idea}" for idea in ideas)

    def _local_math(self, value: str) -> str:
        expression = value.strip()
        if not re.fullmatch(r"[0-9+\-*/().,\s]+", expression):
            return (
                "Matematik ifoda uchun faqat sonlar va + - * / belgilarini kiriting.\n"
                "Masalan: (120000 + 80000) / 4"
            )
        if "**" in expression or "//" in expression:
            return "Daraja yoki floor-division lokal rejimda bloklangan."
        try:
            result = eval(expression.replace(",", "."), {"__builtins__": {}}, {})
        except Exception:
            return "Ifodani hisoblab bo'lmadi. Qavslar va belgilarni tekshiring."
        return f"Hisob natijasi: {result}"

    def _local_code(self, value: str) -> str:
        hints: list[str] = []
        if "traceback" in value.lower() or "error" in value.lower():
            hints.append("xato stack trace'ning eng pastki qatoridan boshlang")
        if "none" in value.lower() or "null" in value.lower():
            hints.append("None/null qiymat kelayotgan joyni tekshiring")
        if "async" in value.lower():
            hints.append("await ishlatilgan joylar va event loop oqimini tekshiring")
        if not hints:
            hints = [
                "kiruvchi qiymatlarni validate qiling",
                "kichik test yozib xatoni takrorlang",
                "funksiyani alohida qismlarga bo'lib tekshiring",
            ]
        return "Kod bo'yicha tezkor tekshiruv:\n" + "\n".join(f"- {hint}" for hint in hints)

    def _local_resume(self, value: str) -> str:
        return (
            "CV skeleti:\n"
            "1. Ism va kontaktlar\n"
            "2. Qisqa professional summary\n"
            "3. Tajriba: lavozim, kompaniya, natija\n"
            "4. Ko'nikmalar\n"
            "5. Ta'lim va sertifikatlar\n\n"
            f"Kiritilgan ma'lumot: {value[:500]}"
        )

    def _local_translate(self, value: str) -> str:
        if "->" in value:
            target, text = value.split("->", maxsplit=1)
            return (
                f"Tarjima yo'nalishi: {target.strip()}\n"
                "Lokal tarjima soddalashtirilgan: matnni ma'no bo'yicha "
                "qayta yozish kerak.\n\n"
                f"Matn: {text.strip()[:700]}"
            )
        return (
            "Tarjima formati: til -> matn\n"
            f"Kiritilgan matn: {value[:700]}"
        )

    def _local_quiz(self, value: str) -> str:
        topic = value or "umumiy bilim"
        return (
            f"{topic} bo'yicha mini-test:\n"
            "1. Asosiy tushuncha nima?\n"
            "2. Bitta real misol keltiring.\n"
            "3. Eng muhim qoida qaysi?\n"
            "4. Qanday xato ko'p uchraydi?\n"
            "5. Xulosa qilib ayting.\n\n"
            "Javoblarni foydalanuvchi o'zi yozadi, keyin tekshirish mumkin."
        )

    def _local_poem(self, value: str) -> str:
        topic = value or "orzular"
        return (
            f"{topic} haqida qisqa she'r:\n"
            "Yo'l boshida niyat uyg'oq,\n"
            "Har qadamda umid porlar.\n"
            "Mehnat bilan ochilar yo'l,\n"
            "Yurak ishga nur sochar."
        )

    def _local_general(self, value: str) -> str:
        if not value:
            return "Savol yoki mavzu kiriting."
        return (
            "Tezkor javob rejasi:\n"
            f"- Mavzu: {value[:220]}\n"
            "- Maqsadni aniqlang.\n"
            "- Kerakli ma'lumotlarni 3-5 bandga ajrating.\n"
            "- Eng oson bajariladigan birinchi qadamni tanlang.\n"
            "- Natijani tekshirib, keyingi qadamni belgilang."
        )

    async def _respond_openai(
        self,
        *,
        user_input: str,
        instructions: str,
        web_search: bool,
        domains: tuple[str, ...],
    ) -> AIResult:
        payload: dict[str, object] = {
            "model": self.openai_model,
            "instructions": (
                "You are a service inside a Telegram Mini App. "
                "Answer in the user's language, be concise and accurate. "
                "Never claim a real-time fact without a source. "
                + instructions
            ),
            "input": user_input,
            "max_output_tokens": 1600,
        }
        if web_search:
            tool: dict[str, object] = {"type": "web_search"}
            if domains:
                tool["filters"] = {"allowed_domains": list(domains)}
            payload["tools"] = [tool]
            payload["include"] = ["web_search_call.action.sources"]

        timeout = aiohttp.ClientTimeout(total=90)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                "https://api.openai.com/v1/responses",
                headers=self._openai_headers(),
                json=payload,
            ) as response:
                data = await response.json(content_type=None)
                if response.status >= 400:
                    message = (
                        data.get("error", {}).get("message")
                        if isinstance(data, dict)
                        else None
                    )
                    raise AIServiceError(message or "AI provayder xatosi")

        text = str(data.get("output_text", "")).strip()
        sources: list[dict[str, str]] = []
        for output in data.get("output", []):
            if not isinstance(output, dict):
                continue
            for content in output.get("content", []):
                if not isinstance(content, dict):
                    continue
                if not text and content.get("type") == "output_text":
                    text = str(content.get("text", "")).strip()
                for annotation in content.get("annotations", []):
                    if not isinstance(annotation, dict):
                        continue
                    url = annotation.get("url")
                    if url and not any(item["url"] == url for item in sources):
                        sources.append(
                            {
                                "url": str(url),
                                "title": str(annotation.get("title") or url),
                            }
                        )
            action = output.get("action")
            if isinstance(action, dict):
                for source in action.get("sources", []):
                    if not isinstance(source, dict) or not source.get("url"):
                        continue
                    url = str(source["url"])
                    if not any(item["url"] == url for item in sources):
                        sources.append(
                            {
                                "url": url,
                                "title": str(source.get("title") or url),
                            }
                        )
        if not text:
            raise AIServiceError("AI bo'sh javob qaytardi")
        return AIResult(text=text, sources=tuple(sources[:8]))

    async def _respond_gemini(
        self,
        *,
        user_input: str,
        instructions: str,
        web_search: bool,
        domains: tuple[str, ...],
    ) -> AIResult:
        system_text = (
            "You are a service inside a Telegram Mini App. "
            "Answer in the user's language, be concise and accurate. "
            "Never claim a real-time fact without a source. "
            + instructions
        )
        if web_search and domains:
            system_text += (
                "\nWhen using Google Search grounding, focus on and cite these "
                f"allowed domains where possible: {', '.join(domains)}."
            )
        payload: dict[str, object] = {
            "systemInstruction": {"parts": [{"text": system_text}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_input}],
                }
            ],
            "generationConfig": {"maxOutputTokens": 1600},
        }
        if web_search:
            payload["tools"] = [{"googleSearch": {}}]

        timeout = aiohttp.ClientTimeout(total=90)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                self._gemini_url(self.gemini_model),
                headers=self._gemini_headers(),
                json=payload,
            ) as response:
                data = await response.json(content_type=None)
                if response.status >= 400:
                    raise self._gemini_error(data)
        text, sources = self._parse_gemini_text(data)
        if not text:
            raise AIServiceError("Gemini bo'sh javob qaytardi")
        return AIResult(text=text, sources=tuple(sources[:8]))

    def _gemini_error(self, data: object) -> AIServiceError:
        message = "Gemini provayder xatosi"
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict) and error.get("message"):
                message = str(error["message"])
        lowered = message.lower()
        quota_exceeded = any(
            item in lowered
            for item in (
                "quota",
                "rate limit",
                "resource_exhausted",
                "billing",
            )
        )
        if quota_exceeded:
            message = (
                "Gemini API kvotasi tugagan yoki billing yoqilmagan. "
                "Google AI Studio'da billing/limitni tekshiring yoki "
                "Railway Variables'ga OPENAI_API_KEY qo'shing."
            )
        return AIServiceError(message, quota_exceeded=quota_exceeded)

    def _parse_gemini_text(
        self,
        data: object,
    ) -> tuple[str, list[dict[str, str]]]:
        if not isinstance(data, dict):
            return "", []
        parts: list[str] = []
        sources: list[dict[str, str]] = []
        for candidate in data.get("candidates", []):
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content")
            if isinstance(content, dict):
                for part in content.get("parts", []):
                    if isinstance(part, dict) and part.get("text"):
                        parts.append(str(part["text"]).strip())
            metadata = candidate.get("groundingMetadata")
            if not isinstance(metadata, dict):
                metadata = candidate.get("grounding_metadata")
            if not isinstance(metadata, dict):
                continue
            chunks = metadata.get("groundingChunks")
            if not isinstance(chunks, list):
                chunks = metadata.get("grounding_chunks", [])
            for chunk in chunks:
                if not isinstance(chunk, dict):
                    continue
                web = chunk.get("web")
                if not isinstance(web, dict):
                    continue
                url = web.get("uri") or web.get("url")
                if not url or any(item["url"] == str(url) for item in sources):
                    continue
                sources.append(
                    {
                        "url": str(url),
                        "title": str(web.get("title") or url),
                    }
                )
        return "\n".join(part for part in parts if part).strip(), sources

    async def generate_image(
        self,
        *,
        prompt: str,
        instructions: str,
    ) -> bytes:
        if self.active_provider == "gemini":
            try:
                return await self._generate_gemini_image(
                    prompt=prompt,
                    instructions=instructions,
                )
            except AIServiceError:
                if not self._can_fallback_to_openai:
                    if self._can_fallback_to_local:
                        return self._generate_local_image(
                            prompt=prompt,
                            instructions=instructions,
                        )
                    raise
                return await self._generate_openai_image(
                    prompt=prompt,
                    instructions=instructions,
                )
        if self.active_provider == "openai":
            try:
                return await self._generate_openai_image(
                    prompt=prompt,
                    instructions=instructions,
                )
            except AIServiceError:
                if not self._can_fallback_to_local:
                    raise
                return self._generate_local_image(
                    prompt=prompt,
                    instructions=instructions,
                )
        if self.active_provider == "local":
            return self._generate_local_image(
                prompt=prompt,
                instructions=instructions,
            )
        raise AIServiceError("AI API kaliti serverda sozlanmagan")

    async def _generate_openai_image(
        self,
        *,
        prompt: str,
        instructions: str,
    ) -> bytes:
        payload = {
            "model": self.openai_image_model,
            "prompt": f"{instructions}\n\nUser request: {prompt}",
            "size": "1024x1024",
        }
        timeout = aiohttp.ClientTimeout(total=180)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                "https://api.openai.com/v1/images/generations",
                headers=self._openai_headers(),
                json=payload,
            ) as response:
                data = await response.json(content_type=None)
                if response.status >= 400:
                    message = (
                        data.get("error", {}).get("message")
                        if isinstance(data, dict)
                        else None
                    )
                    raise AIServiceError(message or "AI rasm yaratish xatosi")
            items = data.get("data", []) if isinstance(data, dict) else []
            if not items:
                raise AIServiceError("AI rasm qaytarmadi")
            item = items[0]
            encoded = item.get("b64_json") if isinstance(item, dict) else None
            if encoded:
                return base64.b64decode(encoded)
            url = item.get("url") if isinstance(item, dict) else None
            if not url:
                raise AIServiceError("AI rasm formati noma'lum")
            async with session.get(str(url)) as image_response:
                if image_response.status >= 400:
                    raise AIServiceError("AI rasmini yuklab bo'lmadi")
                return await image_response.read()

    async def _generate_gemini_image(
        self,
        *,
        prompt: str,
        instructions: str,
    ) -> bytes:
        payload: dict[str, object] = {
            "contents": [
                {
                    "parts": [
                        {"text": f"{instructions}\n\nUser request: {prompt}"}
                    ]
                }
            ],
            "generationConfig": {"responseModalities": ["IMAGE"]},
        }
        timeout = aiohttp.ClientTimeout(total=180)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                self._gemini_url(self.gemini_image_model),
                headers=self._gemini_headers(),
                json=payload,
            ) as response:
                data = await response.json(content_type=None)
                if response.status >= 400:
                    raise self._gemini_error(data)
        image = self._parse_gemini_image(data)
        if not image:
            raise AIServiceError("Gemini rasm qaytarmadi")
        return image

    def _parse_gemini_image(self, data: object) -> bytes | None:
        if not isinstance(data, dict):
            return None
        for candidate in data.get("candidates", []):
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content")
            if not isinstance(content, dict):
                continue
            for part in content.get("parts", []):
                if not isinstance(part, dict):
                    continue
                inline_data = part.get("inlineData") or part.get("inline_data")
                if not isinstance(inline_data, dict):
                    continue
                encoded = inline_data.get("data")
                if encoded:
                    return base64.b64decode(str(encoded))
        return None

    def _generate_local_image(
        self,
        *,
        prompt: str,
        instructions: str,
    ) -> bytes:
        from PIL import Image, ImageDraw, ImageFont

        image = Image.new("RGB", (1024, 1024), "#101827")
        draw = ImageDraw.Draw(image)
        for y in range(1024):
            shade = int(18 + y / 1024 * 48)
            draw.line((0, y, 1024, y), fill=(16, shade, 48 + shade // 2))
        draw.rounded_rectangle(
            (82, 110, 942, 914),
            radius=48,
            fill=(13, 25, 42),
            outline=(74, 144, 226),
            width=4,
        )
        draw.ellipse((760, 80, 980, 300), fill=(72, 88, 230))
        draw.ellipse((40, 760, 260, 980), fill=(0, 194, 168))
        try:
            title_font = ImageFont.truetype("DejaVuSans-Bold.ttf", 58)
            body_font = ImageFont.truetype("DejaVuSans.ttf", 34)
            small_font = ImageFont.truetype("DejaVuSans.ttf", 24)
        except OSError:
            title_font = body_font = small_font = ImageFont.load_default()

        draw.text((130, 160), "Local AI Image", fill="#ffffff", font=title_font)
        draw.text(
            (130, 238),
            "API kalitisiz yaratilgan oddiy rasm",
            fill="#93c5fd",
            font=small_font,
        )
        text = prompt or instructions or "Mini App"
        wrapped = textwrap.wrap(text, width=34)[:10]
        y = 330
        for line in wrapped:
            draw.text((130, y), line, fill="#e5e7eb", font=body_font)
            y += 52
        draw.text(
            (130, 845),
            "API kalitisiz lokal rasm. Kalit qo'shilsa kuchliroq model ishlaydi.",
            fill="#a7f3d0",
            font=small_font,
        )
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
