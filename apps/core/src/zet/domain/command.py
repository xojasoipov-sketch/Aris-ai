"""Buyruq va intent domen modellari.

Bu Pydantic modellar — toza domen qatlami: DB'ga bog'liq emas, immutable (`frozen=True`),
va JSON serializatsiya qilish mumkin. DB modellariga o'girish `to_db()`/`from_db()`
yordamida bo'ladi.

Bog'liq qarorlar:
    A-05 — trust level chegaralari
    V-29 — task_class → model marshrutlash
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from zet.domain.enums import MessageRole, TaskClass, TrustLevel


class ConversationTurn(BaseModel, frozen=True):
    """Suhbatdagi bitta oldingi almashinuv.

    ATAYLAB `llm.base.ChatMessage` EMAS. `domain` qatlami `llm` qatlamiga
    bog'lanmasligi kerak — bir marta urinib ko'rilganda aylanma import
    chiqdi (`domain.command → llm.base → llm.__init__ → llm.budget →
    db.models → db.base`). Konvertatsiya `core/executor.py` da, ya'ni
    ikkala qatlamni ham biladigan joyda bo'ladi.
    """

    role: MessageRole
    """Kim aytdi — ega (USER) yoki ZET (ASSISTANT)."""

    content: str
    """Xabar matni."""


class Command(BaseModel, frozen=True):
    """Egadan kelgan xom buyruq.

    Hali tahlil qilinmagan — faqat matn va metama'lumot.
    """

    text: str = Field(min_length=1, max_length=4096)
    """Buyruq matni (masalan: "Ertaga 10:00 uchrashuv haqida eslatma yoz")."""

    trust_level: TrustLevel = TrustLevel.OWNER
    """Buyruq kim tomonidan yuborilgan (A-05)."""

    channel: str = "cli"
    """Qaysi kanal orqali keldi: cli, telegram, api, ..."""

    timestamp: datetime | None = None
    """Buyruq kelib tushgan vaqt (UTC)."""

    metadata: dict[str, Any] = Field(default_factory=dict)
    """Kanalga xos qo'shimcha ma'lumot (masalan: telegram chat_id)."""

    history: list[ConversationTurn] = Field(default_factory=list)
    """Shu suhbatdagi oldingi xabarlar (eng eskisi birinchi).

    Ilgari bu maydon yo'q edi va HAR BIR xabar mustaqil run sifatida
    bajarilardi — ya'ni ZET oldingi gapni eslamasdi. Jonli misol:

        ega:  "Nimalar qilolasan?"
        ZET:  <imkoniyatlar haqida javob>
        ega:  "Tushuntir"
        ZET:  "Nimani tushuntirib berishimni xohlaysiz?"   ← kontekst yo'q

    Tarix `Executor`ning fikrlash qadamiga uzatiladi, shuning uchun
    "tushuntir", "davom et", "u haqida batafsil" kabi ergash buyruqlar
    ishlaydi.

    Chegara: `TelegramSession` faqat oxirgi bir necha almashinuvni
    saqlaydi — token narxi va kontekst uzunligi cheklangan.
    """


class Intent(BaseModel, frozen=True):
    """Buyruqdan ajratilgan strukturalangan niyat (Z1.7).

    Intent Recognizer matn → `Intent` o'giradi;
    bu Planner uchun kirish bo'ladi.
    """

    action: str
    """Asosiy harakat fe'li (masalan: "reminder.create", "file.delete", "note.write")."""

    objects: list[str] = Field(default_factory=list)
    """Harakat obyektlari (masalan: ["ertangi uchrashuv", "10:00"])."""

    constraints: list[str] = Field(default_factory=list)
    """Qo'shimcha cheklovlar (masalan: ["o'zbek tilida", "qisqa bo'lsin"])."""

    urgency: str = "normal"
    """Shoshilinchlik darajasi: low, normal, high, critical."""

    task_class: TaskClass = TaskClass.NORMAL
    """Vazifa sinfi — Model Router shu asosda tier tanlaydi (V-29, ADR-0006)."""

    requires_tools: list[str] = Field(default_factory=list)
    """Kerakli tool nomlari (masalan: ["time.now", "note.write"])."""

    ambiguity: str = "low"
    """Noaniqlik darajasi: low, medium, high. high → aniqlashtirish savoli."""

    clarification_question: str | None = None
    """Agar ambiguity=high bo'lsa, foydalanuvchiga beriladigan savol."""

    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    """LLM ning o'z bahosi (0.0—1.0)."""

    original_text: str = ""
    """Asl buyruq matni (debug uchun saqlanadi)."""

    raw_llm_output: dict[str, Any] = Field(default_factory=dict)
    """LLM qaytargan xom javob (debug/audit)."""
