"""Xavf darajasi jadvali — tool nomi bo'yicha risk klassifikatsiya (V-32 kengaytmasi).

NEGA: `PermissionLevel` savoli "kim chaqirishga haqli?" — READ/WRITE/EXECUTE/ADMIN.
`RiskLevel` savoli boshqa: "ega tasdig'i kerakmi?". Ikki o'q bir-birini
almashtirmaydi — WRITE toolning risk'i LOW ham (masalan `note.write`
xususiy vault'ga) bo'lishi mumkin, HIGH ham (masalan `github.write`
tashqi jamoat repozitoriyga). PermissionPolicy ikkalasini birlashtirib
qaror qiladi.

Ilgari faqat `HIGH_RISK_TOOLS` frozenset bor edi — "yuqori xavfli"
degan tekis ro'yxat. Bu MEDIUM darajani bermas edi (business writes
"nima qilyapti — konfiguratsiya qilaman" degan tanlovsiz avtomatik
o'tardi yoki umuman rad etilardi). Endi uch daraja:

    LOW     — avtomatik (research, draft, private files, read-only)
    MEDIUM  — sozlanadi (default: tasdiq; ega
              `auto_approve_medium=True` yoqishi mumkin)
    HIGH    — DOIM tasdiq (delete, publish, tashqi yuborish,
              moliya, kredensial, permission o'zgarishi)

`TOOL_RISK_LEVELS` bu — tool nomi bo'yicha markazlashtirilgan jadval.
Har bir mavjud tool subclass'ini o'zgartirmay turib klassifikatsiya
qo'shish uchun. `Tool.risk_level` property default sifatida shu
jadvalga qaraydi va topilmasa `LOW` qaytaradi; subclass o'zi
override qilsa — o'z qarori ustuvor.

Bog'liq qarorlar:
    V-32 — majburiy tasdiq (kengaytirilgan)
    ZET_ASS_MASTER PART 5 — LOW/MEDIUM/HIGH risk qoidalari
    ZET_ASS_AUTONOMY_AUDIT §2.8 — risk-based approval oqimi
"""

from __future__ import annotations

from typing import Final

from zet.domain.enums import RiskLevel

__all__ = ["TOOL_RISK_LEVELS", "RiskLevel", "risk_for"]


# ── Yuqori xavf: DOIM tasdiq, hech bir siyosat/daraja chetlab o'ta olmaydi ──
_HIGH: Final[frozenset[str]] = frozenset(
    {
        # Ixtiyoriy kod bajarish — buzg'unchi server amali
        "shell.exec",
        # Ma'lumot yo'qotish — qaytarib bo'lmaydi
        "file.delete",
        # Ixtiyoriy SQL — buzg'unchi
        "db.execute",
        # Buzg'unchi
        "system.shutdown",
        # Xavfsizlik konfiguratsiyasi o'zgarishi
        "config.modify",
        # Ixtiyoriy chiquvchi so'rov — ma'lumot chiqarib yuborish xavfi
        "network.request",
        # Tashqi holatni o'zgartirish + jamoat — orqaga qaytarish qiyin
        "github.write",
        # Tashqi jamoat xabari
        "telegram.channel_post",
        # Buzg'unchi tashqi holat o'zgarishi
        "telegram.delete_message",
        # Kontent nashr etish — jamoatga
        "instagram.publish_photo",
        "youtube.publish",
        # Boshqa agentning imkoniyati/ruxsatini o'zgartirish — eskalatsiya
        "agent.disable",
        # Haqiqiy desktop'da ixtiyoriy UI kiritish — buzg'unchi
        "desktop.type_text",
        "desktop.key_press",
        "desktop.mouse_click",
    }
)

# ── O'rta xavf: default tasdiq, `auto_approve_medium=True` bilan avtomatik ──
_MEDIUM: Final[frozenset[str]] = frozenset(
    {
        # Buyurtma holati (SHIPPED bo'lsa mijozga xabar) — biznesga
        # ko'rinadi, lekin qaytarish mumkin
        "order.set_status",
        # Katalog qo'shish — delete bilan qaytarish mumkin
        "product.create",
        # Biznes holati o'zgarishi — qaytariladigan
        "task.create",
        "task.update",
        "project.create",
        # CRM yozuvlari — mijoz ma'lumotini o'zgartiradi
        "crm.contact_create",
        "crm.lead_create",
        "crm.deal_create",
        # Umumiy vault'ga yozuv — bilim bazasini o'zgartiradi
        "note.write",
        # Agentning uzoq muddatli xotirasiga — orqaga qaytarish qiyin
        "memory.write",
        # Agent hayoti — qaytariladigan
        "agent.pause",
        "agent.resume",
    }
)


TOOL_RISK_LEVELS: Final[dict[str, RiskLevel]] = {
    **dict.fromkeys(_HIGH, RiskLevel.HIGH),
    **dict.fromkeys(_MEDIUM, RiskLevel.MEDIUM),
}
"""Nom bo'yicha jadval. Yo'q bo'lsa — default LOW (`risk_for` yordamchisi).

MUHIM: bu jadvalda `LOW` toollarni sanamaymiz — puxta ro'yxatlash tez
eskiradigan bo'ladi va yangi qo'shilgan tool avtomatik LOW bo'lishi
kifoya. HIGH va MEDIUM esa aniq belgilanishi kerak — noto'g'ri qoldirilsa
xavfsizlik teshigi.
"""


def risk_for(tool_name: str | None) -> RiskLevel:
    """Tool nomi bo'yicha xavf darajasini qaytaradi.

    Ilgari (`HIGH_RISK_TOOLS` bilan) faqat "yuqori xavflimi?" degan
    boolean bor edi. Endi uch daraja. Nom noma'lum yoki `None` bo'lsa —
    LOW (default: xatoni ko'tarmay, eng past tortish).
    """
    if not tool_name:
        return RiskLevel.LOW
    return TOOL_RISK_LEVELS.get(tool_name, RiskLevel.LOW)
