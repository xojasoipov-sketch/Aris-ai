"""Inline klaviaturalar — approval tugmalari va boshqa interaktiv elementlar.

V-32 tasdiq oqimi:
    1. Run AWAITING_APPROVAL holatiga o'tadi
    2. Egasiga inline tugmali xabar yuboriladi
    3. Ega ✅ yoki ❌ tugmasini bosadi
    4. Callback handler natijani qayta ishlaydi

Callback data formati: "approve:{run_id}" yoki "reject:{run_id}"

Bog'liq qarorlar:
    V-32 — yuqori xavfli amallar uchun majburiy tasdiq
    V-17 — Telegram inline tugmalari
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class InlineButton:
    """Inline tugma — matn va callback_data."""

    text: str
    callback_data: str


@dataclass(frozen=True)
class InlineKeyboard:
    """Inline klaviatura — tugmalar qatorlari."""

    rows: list[list[InlineButton]]


class ApprovalKeyboard:
    """Tasdiq tugmalari yaratuvchi (V-32).

    Callback data formati:
        approve:{run_id}  — tasdiqlash
        reject:{run_id}   — rad etish
    """

    @staticmethod
    def for_run(run_id: str) -> InlineKeyboard:
        """Run uchun tasdiq/rad tugmalari.

        Args:
            run_id: run identifikatori

        Returns:
            InlineKeyboard — ✅ / ❌ tugmali klaviatura
        """
        return InlineKeyboard(
            rows=[
                [
                    InlineButton(text="✅ Tasdiqlash", callback_data=f"approve:{run_id}"),
                    InlineButton(text="❌ Rad etish", callback_data=f"reject:{run_id}"),
                ],
            ]
        )

    @staticmethod
    def for_step(run_id: str, step_position: int) -> InlineKeyboard:
        """Qadam uchun tasdiq/rad/barchasi tugmalari.

        Args:
            run_id: run identifikatori
            step_position: qadam raqami

        Returns:
            InlineKeyboard — ✅ / ❌ / ✅✅ tugmali klaviatura
        """
        return InlineKeyboard(
            rows=[
                [
                    InlineButton(
                        text="✅ Qadam",
                        callback_data=f"approve_step:{run_id}:{step_position}",
                    ),
                    InlineButton(
                        text="❌ Rad",
                        callback_data=f"reject_step:{run_id}:{step_position}",
                    ),
                ],
                [
                    InlineButton(
                        text="✅✅ Barchasini tasdiqlash",
                        callback_data=f"approve_all:{run_id}",
                    ),
                ],
            ]
        )

    @staticmethod
    def parse_callback(data: str) -> dict[str, str]:
        """Callback data ni tahlil qilish.

        Args:
            data: callback_data matn

        Returns:
            dict — action, run_id, va ixtiyoriy step_position

        Raises:
            ValueError: noto'g'ri format
        """
        parts = data.split(":")
        if len(parts) < 2:
            raise ValueError(f"Noto'g'ri callback data: {data}")

        action = parts[0]
        run_id = parts[1]
        result: dict[str, str] = {"action": action, "run_id": run_id}

        if len(parts) >= 3:
            result["step_position"] = parts[2]

        return result

    @staticmethod
    def confirm_action(action: str) -> InlineKeyboard:
        """Umumiy tasdiqlash tugmalari.

        Args:
            action: tasdiqlanishi kerak bo'lgan amal nomi

        Returns:
            InlineKeyboard — Ha / Yo'q tugmali klaviatura
        """
        return InlineKeyboard(
            rows=[
                [
                    InlineButton(text="✅ Ha", callback_data=f"confirm:{action}"),
                    InlineButton(text="❌ Yo'q", callback_data=f"cancel:{action}"),
                ],
            ]
        )
