"""Javob prompti — fikrlash qadami uchun (Z44).

NEGA BU FAYL KERAK BO'LDI.

Pipeline `INTENT → PLANNER → EXECUTION → VERIFICATION` deb qurilgan
(V-04), lekin EXECUTION faqat **tool** qadamlarini bajarardi. Tool'siz
qadam ("fikrlash qadami") shunchaki DONE deb belgilanardi:

    if step.tool_name is None:
        return StepResult(step, status=StepStatus.DONE)   # hech narsa qilmaydi

Ya'ni "Nimalar qilolasan?" kabi oddiy savolga **javob umuman
yozilmasdi**. Ega ko'rgan yagona narsa jarayon hisoboti edi:

    "ZET imkoniyatlarini tushuntirish rejasi — 1/1 qadam bajarildi"

Reja bor, bajarildi degan belgi bor — javob yo'q. Ega buni haqli
ravishda "miyyasi ishlamayapti" deb baholadi.

Bu prompt shu bo'shliqni to'ldiradi: fikrlash qadami endi haqiqiy
LLM chaqiruvi bo'ladi va matn qaytaradi.

Bog'liq qarorlar:
    V-04 — markaziy pipeline
    V-01 — natija ega uchun, jarayon hisoboti emas
"""

from __future__ import annotations

ANSWER_SYSTEM = """Sen ZET — egasining shaxsiy AI operatsion tizimisan.

Egaga TO'G'RIDAN-TO'G'RI javob ber. Sen bilan oddiy suhbat ketyapti.

QAT'IY QOIDALAR:
- Javobni O'ZBEK tilida yoz (ega o'zbekcha gapiradi).
- Jarayon haqida hisobot BERMA. "Rejani bajardim", "qadam tugadi",
  "tahlil qildim" kabi gaplar TAQIQLANADI — ega natijani so'ragan,
  jarayonni emas.
- Qisqa va aniq yoz. Telegram xabari uzunligida (2-6 jumla), agar
  ega ro'yxat yoki batafsil tushuntirish so'ramagan bo'lsa.
- Bilmasang — "bilmayman" deb ayt, to'qima.
- Emoji ishlatma.

Agar quyida oldingi qadamlar natijasi berilgan bo'lsa — javobni AYNAN
o'shanga asoslab yoz, o'zingdan qo'shma."""


def build_answer_prompt(
    command_text: str,
    *,
    step_description: str,
    prior_outputs: list[str] | None = None,
) -> str:
    """Fikrlash qadami uchun foydalanuvchi xabarini yasaydi.

    Args:
        command_text: eganing asl buyrug'i/savoli
        step_description: rejadagi shu qadam nima qilishi kerakligi
        prior_outputs: oldingi qadamlar natijalari (tool chiqishlari ham)

    Returns:
        LLM'ga yuboriladigan matn
    """
    parts = [f"EGANING SAVOLI/BUYRUG'I:\n{command_text}"]

    if step_description and step_description.strip() != command_text.strip():
        parts.append(f"SHU QADAMDA NIMA QILISH KERAK:\n{step_description}")

    useful = [o.strip() for o in (prior_outputs or []) if o and o.strip()]
    if useful:
        joined = "\n\n".join(f"— {o}" for o in useful)
        parts.append(f"OLDINGI QADAMLAR NATIJASI:\n{joined}")

    parts.append("Endi egaga javobni yoz.")
    return "\n\n".join(parts)


__all__ = ["ANSWER_SYSTEM", "build_answer_prompt"]
