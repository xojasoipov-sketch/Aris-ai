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

Egaga TO'G'RIDAN-TO'G'RI javob ber. Sen bilan oddiy suhbat ketyapti —
Telegram orqali, oddiy odam yozgandek. Rasmiy xat yoki hisobot EMAS.

QAT'IY QOIDALAR:
- Javobni O'ZBEK tilida yoz (ega o'zbekcha gapiradi).
- Jarayon haqida hisobot BERMA. "Rejani bajardim", "qadam tugadi",
  "tahlil qildim" kabi gaplar TAQIQLANADI — ega natijani so'ragan,
  jarayonni emas.
- Qisqa jumlalar yoz. Ortiqcha rasmiylashtirish yo'q: "Albatta!",
  "Men sizga yordam bera olaman", "Xulosa qilib aytganda" kabi
  qoliplar TAQIQLANADI — to'g'ridan-to'g'ri javobdan boshla.
- Agar javob tabiiy ravishda bir nechta fikrga bo'linsa (masalan:
  natija + savol, yoki tasdiq + qo'shimcha taklif) — ularni BO'SH
  QATOR bilan ajrat. Har biri alohida Telegram xabari sifatida
  yuboriladi, xuddi odam ketma-ket yozganidek. Bitta fikrni sun'iy
  bo'laklarga bo'lib TASHLAMA — faqat haqiqatan alohida bo'lgan
  fikrlar shunday ajratiladi.
- Bullet/ro'yxat/sarlavha FAQAT haqiqatan ro'yxat kerak bo'lganda
  (masalan bir nechta vazifa/band sanalganda). Oddiy suhbat javobida
  formatlashdan saqlan.
- Emoji — kamdan-kam va faqat o'rinli bo'lsa, inson yozgandek
  (masalan haqiqiy quvonch yoki xushxabarda bitta emoji tabiiy
  bo'lishi mumkin). Har javobga emoji QO'YISH SHART EMAS — aksariyat
  javoblarda umuman kerak emas. Hech qachon xabar boshiga status
  belgisi sifatida qo'yma.
- Bilmasang — "bilmayman" deb ayt, to'qima.

Agar quyida oldingi qadamlar natijasi berilgan bo'lsa — javobni AYNAN
o'shanga asoslab yoz, o'zingdan qo'shma."""


def build_answer_prompt(
    command_text: str,
    *,
    step_description: str,
    prior_outputs: list[str] | None = None,
    recalled: list[str] | None = None,
) -> str:
    """Fikrlash qadami uchun foydalanuvchi xabarini yasaydi.

    Args:
        command_text: eganing asl buyrug'i/savoli
        step_description: rejadagi shu qadam nima qilishi kerakligi
        prior_outputs: oldingi qadamlar natijalari (tool chiqishlari ham)
        recalled: uzoq muddatli xotiradan topilgan tegishli yozuvlar

    Returns:
        LLM'ga yuboriladigan matn
    """
    parts = [f"EGANING SAVOLI/BUYRUG'I:\n{command_text}"]

    remembered = [r.strip() for r in (recalled or []) if r and r.strip()]
    if remembered:
        joined = "\n\n".join(f"— {r}" for r in remembered)
        parts.append(
            "EGA HAQIDA ESLAB QOLGANLARING (uzoq muddatli xotira):\n"
            f"{joined}\n\n"
            "Bulardan javobda foydalan. Ular ega haqida ALLAQACHON "
            "bilgan narsang — qayta so'rama."
        )

    if step_description and step_description.strip() != command_text.strip():
        parts.append(f"SHU QADAMDA NIMA QILISH KERAK:\n{step_description}")

    useful = [o.strip() for o in (prior_outputs or []) if o and o.strip()]
    if useful:
        joined = "\n\n".join(f"— {o}" for o in useful)
        parts.append(f"OLDINGI QADAMLAR NATIJASI:\n{joined}")

    parts.append("Endi egaga javobni yoz.")
    return "\n\n".join(parts)


__all__ = ["ANSWER_SYSTEM", "build_answer_prompt"]
