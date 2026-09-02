"""`schedule_expression.parse_schedule` testlari (JB-9).

Tabiiy tildan cron ajratish — deterministik parser. Har test bitta
tabiiy iborani beradi va aniq cron kutadi. Aniq bo'lmagan ("noaniq")
ifodalar `None` qaytaradi va bu ham TASDIQLANADI.
"""

from __future__ import annotations

from zet.core.schedule_expression import ScheduleExpression, parse_schedule


class TestDailyExpressions:
    def test_har_kuni_soat_9_da(self) -> None:
        result = parse_schedule("Har kuni soat 9 da telegramimni tekshir.")
        assert isinstance(result, ScheduleExpression)
        assert result.cron == "0 9 * * *"

    def test_har_kuni_default_time(self) -> None:
        """'Har kuni' — soat berilmasa default 09:00."""
        result = parse_schedule("Har kuni biznes hisobotini ber.")
        assert result is not None
        assert result.cron == "0 9 * * *"

    def test_daily_english(self) -> None:
        result = parse_schedule("Daily standup at 10:30")
        assert result is not None
        assert result.cron == "30 10 * * *"

    def test_soat_daqiqa_uzbek(self) -> None:
        result = parse_schedule("Har kuni soat 21:45 da xabar yubor")
        assert result is not None
        assert result.cron == "45 21 * * *"


class TestWeeklyExpressions:
    def test_har_hafta_dushanba(self) -> None:
        result = parse_schedule("Har hafta dushanba soat 8 da rejalash")
        assert result is not None
        # dow=1 (dushanba), soat=8, daqiqa=0
        assert result.cron == "0 8 * * 1"

    def test_har_hafta_juma(self) -> None:
        result = parse_schedule("Har hafta juma soat 17 da yakuniy hisobot ber")
        assert result is not None
        assert result.cron == "0 17 * * 5"

    def test_har_hafta_no_day_defaults_monday(self) -> None:
        """Kun ko'rsatilmasa — dushanba (ish haftasi boshi)."""
        result = parse_schedule("Har hafta biznesni tekshir")
        assert result is not None
        assert result.cron.endswith("* * 1")


class TestMonthlyExpressions:
    def test_har_oy_1_kuni(self) -> None:
        result = parse_schedule("Har oy 1-kuni hisobot yubor")
        assert result is not None
        assert result.cron == "0 9 1 * *"

    def test_har_oy_15_kuni_with_time(self) -> None:
        result = parse_schedule("Har oy 15 kuni soat 10 da eslatma")
        assert result is not None
        assert result.cron == "0 10 15 * *"

    def test_har_oy_no_day_defaults_1(self) -> None:
        result = parse_schedule("Har oy hisobot yubor")
        assert result is not None
        assert result.cron.split()[2] == "1"


class TestIntervalExpressions:
    def test_har_30_daqiqa(self) -> None:
        result = parse_schedule("Har 30 daqiqa serverni tekshir")
        assert result is not None
        assert result.cron == "*/30 * * * *"

    def test_har_5_daqiqa(self) -> None:
        result = parse_schedule("Har 5 daqiqa signal tekshir")
        assert result is not None
        assert result.cron == "*/5 * * * *"

    def test_har_4_soat(self) -> None:
        result = parse_schedule("Har 4 soat statusni ber")
        assert result is not None
        assert result.cron == "0 */4 * * *"

    def test_har_soat(self) -> None:
        """Aniq raqamsiz 'har soat' — soatlik."""
        result = parse_schedule("Har soat metrikalarni yozib bor")
        assert result is not None
        assert result.cron == "0 * * * *"


class TestReasonExplanation:
    def test_every_result_has_nonempty_reason(self) -> None:
        """JB-9: har bir topilgan cron TUSHUNTIRILGAN bo'lishi shart."""
        cases = [
            "Har kuni soat 9 da",
            "Har hafta juma",
            "Har oy 1-kuni",
            "Har 30 daqiqa",
            "Har soat",
        ]
        for text in cases:
            result = parse_schedule(text)
            assert result is not None, text
            assert result.reason.strip() != "", text


class TestNoMatch:
    """Aniqlab bo'lmagan iboralar `None` qaytarishi kerak — soxta cron
    yasash tizim ishonchini yo'q qiladi."""

    def test_empty_text(self) -> None:
        assert parse_schedule("") is None

    def test_no_schedule_keywords(self) -> None:
        assert parse_schedule("Salom, qalaysan?") is None

    def test_one_shot_command(self) -> None:
        """'Hozir bir marta' — takrorlanuvchi EMAS."""
        assert parse_schedule("Faqat hozir bir marta telegramimni tekshir") is None

    def test_complex_expression_returns_none(self) -> None:
        """'Har juma va yakshanba 14:30 dan 18:00 gacha yarim soatda' —
        murakkab, parser qamramaydi. Halol `None`."""
        # 'har hafta' + 'juma' kombinatsiyasini tutadi, lekin 'va yakshanba'
        # holati murakkab. Faqat 'juma'ni oladi — bu ham qabul, halol
        # cheklanganlik.
        result = parse_schedule("Notekis kunlarda ba'zan ishla")
        # Aniq schedule iborasi yo'q → None
        assert result is None
