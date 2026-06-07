from __future__ import annotations

import io
import math
import random
import secrets
import string
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import qrcode


class CatalogExecutionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LocalResult:
    text: str = ""
    image: bytes | None = None
    image_name: str = "result.png"


def _numbers(value: str, count: int) -> list[float]:
    try:
        result = [float(item.strip()) for item in value.split(",")]
    except ValueError as exc:
        raise CatalogExecutionError("Raqamlarni vergul bilan kiriting") from exc
    if len(result) != count:
        raise CatalogExecutionError(f"{count} ta qiymat vergul bilan kerak")
    return result


def _invoice(value: str) -> str:
    parts = [item.strip() for item in value.split("|")]
    if len(parts) != 4 or not all(parts):
        raise CatalogExecutionError(
            "Format: Sotuvchi | Mijoz | Xizmat | Summa"
        )
    seller, customer, item, amount = parts
    return (
        "INVOICE / HISOB-FAKTURA\n"
        "========================\n"
        f"Sotuvchi: {seller}\n"
        f"Mijoz: {customer}\n"
        f"Xizmat: {item}\n"
        f"Summa: {amount}\n"
        f"Sana: {datetime.now().date().isoformat()}\n\n"
        "Bu to'lov tasdig'i emas. Rasmiy hisob hujjati sifatida tekshirib chiqing."
    )


def execute_local(slug: str, value: str) -> LocalResult:
    value = value.strip()
    if not value:
        raise CatalogExecutionError("Ma'lumot kiriting")

    if slug == "randomizer":
        parts = [item.strip() for item in value.split(",") if item.strip()]
        if len(parts) == 2:
            try:
                start, end = int(parts[0]), int(parts[1])
            except ValueError:
                pass
            else:
                if start > end or end - start > 10_000_000:
                    raise CatalogExecutionError("Son oralig'i noto'g'ri")
                return LocalResult(f"Tasodifiy natija: {random.randint(start, end)}")
        if len(parts) < 2:
            raise CatalogExecutionError("Kamida 2 ta variant kiriting")
        return LocalResult(f"Tanlandi: {secrets.choice(parts)}")

    if slug == "password_generator":
        try:
            length = int(value)
        except ValueError as exc:
            raise CatalogExecutionError("Parol uzunligini son bilan kiriting") from exc
        if not 8 <= length <= 128:
            raise CatalogExecutionError("Parol uzunligi 8-128 oralig'ida bo'lsin")
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*_-+="
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        return LocalResult(f"Kuchli parol:\n{password}")

    if slug == "bmi":
        weight, height = _numbers(value, 2)
        if weight <= 0 or height <= 0:
            raise CatalogExecutionError("Bo'y va vazn musbat bo'lishi kerak")
        bmi = weight / (height * height)
        label = (
            "vazn yetishmasligi"
            if bmi < 18.5
            else "me'yoriy"
            if bmi < 25
            else "ortiqcha vazn"
            if bmi < 30
            else "yuqori BMI"
        )
        return LocalResult(
            f"BMI: {bmi:.1f} ({label}). "
            "Bu tashxis emas; sog'liq bo'yicha shifokorga murojaat qiling."
        )

    if slug == "loan_calculator":
        principal, annual_rate, months_value = _numbers(value, 3)
        months = int(months_value)
        if principal <= 0 or annual_rate < 0 or months <= 0:
            raise CatalogExecutionError("Qiymatlar noto'g'ri")
        monthly_rate = annual_rate / 100 / 12
        payment = (
            principal / months
            if monthly_rate == 0
            else principal
            * monthly_rate
            * (1 + monthly_rate) ** months
            / ((1 + monthly_rate) ** months - 1)
        )
        total = payment * months
        return LocalResult(
            f"Taxminiy oylik to'lov: {payment:,.0f}\n"
            f"Jami to'lov: {total:,.0f}\n"
            f"Foiz xarajati: {total - principal:,.0f}\n\n"
            "Bank komissiyasi va sug'urta hisobga olinmagan."
        )

    if slug == "world_time":
        try:
            now = datetime.now(ZoneInfo(value))
        except ZoneInfoNotFoundError as exc:
            raise CatalogExecutionError(
                "IANA zona kiriting, masalan Asia/Tokyo"
            ) from exc
        return LocalResult(
            f"{value}: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}"
        )

    if slug == "qibla_compass":
        latitude, longitude = _numbers(value, 2)
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise CatalogExecutionError("Koordinatalar noto'g'ri")
        kaaba_lat = math.radians(21.4225)
        delta_lon = math.radians(39.8262 - longitude)
        lat = math.radians(latitude)
        bearing = math.degrees(
            math.atan2(
                math.sin(delta_lon),
                math.cos(lat) * math.tan(kaaba_lat)
                - math.sin(lat) * math.cos(delta_lon),
            )
        )
        return LocalResult(
            f"Qibla yo'nalishi: {(bearing + 360) % 360:.1f}° "
            "(shimoldan soat yo'nalishi bo'yicha)."
        )

    if slug == "font_stylist":
        bold = str.maketrans(
            string.ascii_letters + string.digits,
            "𝐚𝐛𝐜𝐝𝐞𝐟𝐠𝐡𝐢𝐣𝐤𝐥𝐦𝐧𝐨𝐩𝐪𝐫𝐬𝐭𝐮𝐯𝐰𝐱𝐲𝐳"
            "𝐀𝐁𝐂𝐃𝐄𝐅𝐆𝐇𝐈𝐉𝐊𝐋𝐌𝐍𝐎𝐏𝐐𝐑𝐒𝐓𝐔𝐕𝐖𝐗𝐘𝐙"
            "𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗",
        )
        circled = str.maketrans(
            string.ascii_lowercase,
            "ⓐⓑⓒⓓⓔⓕⓖⓗⓘⓙⓚⓛⓜⓝⓞⓟⓠⓡⓢⓣⓤⓥⓦⓧⓨⓩ",
        )
        return LocalResult(
            f"Qalin:\n{value.translate(bold)}\n\n"
            f"Doirali:\n{value.lower().translate(circled)}\n\n"
            f"Ajratilgan:\n{' '.join(value)}"
        )

    if slug in {"demo_invoice", "invoice_generator"}:
        return LocalResult(_invoice(value))

    if slug == "qr_barcode":
        image = qrcode.make(value)
        output = io.BytesIO()
        image.save(output, format="PNG")
        return LocalResult(image=output.getvalue(), image_name="qr-code.png")

    raise CatalogExecutionError("Bu lokal xizmat hali ulanmagan")
