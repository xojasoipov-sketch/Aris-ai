"""Agent domen modellari (Bo'lim 3, A-02).

Agent = ma'lumot, kod emas. Har bir agent DB yozuvi sifatida saqlanadi.
Uning xatti-harakati system_prompt, tool_allowlist va model_policy
bilan boshqariladi — yangi Python kodi yozilmaydi.

Bog'liq qarorlar:
    A-02 — Agent Factory kod generatsiya QILMAYDI
    V-11 — lifecycle avtomati
    V-31 — ruxsat darajalari
    A-05 — ishonch darajalari
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from zet.domain.enums import AgentStatus, ModelTier, PermissionLevel, TrustLevel
from zet.domain.tool import ToolResult


class AgentSpec(BaseModel, frozen=True):
    """Agent spetsifikatsiyasi — nima qilishini belgilaydigan yozuv (A-02).

    Agent qurish uchun yangi Python kodi yozilmaydi.
    Hamma narsa shu kontraktda — system_prompt, tool_allowlist, model_policy.
    """

    name: str = Field(min_length=1, max_length=64)
    """Unikal agent nomi (masalan: 'research', 'ceo', 'smm')."""

    description: str = Field(min_length=1, max_length=500)
    """Agent qisqa tavsifi."""

    division: str = Field(default="general", max_length=64)
    """Bo'lim (masalan: 'ops', 'marketing', 'finance')."""

    role: str = Field(default="assistant", max_length=64)
    """Rol (masalan: 'researcher', 'analyst', 'manager')."""

    goal: str = Field(default="", max_length=1000)
    """Agent asosiy maqsadi."""

    system_prompt: str = Field(min_length=1)
    """Tizim prompti — agent xatti-harakatini belgilaydi."""

    tool_allowlist: list[str] = Field(default_factory=list)
    """Ruxsat etilgan toollar ro'yxati (bo'sh = hech narsa)."""

    model_policy: ModelTier = ModelTier.T1_FREE
    """Default model tier (marshrut)."""

    permission_level: PermissionLevel = PermissionLevel.READ
    """Agent ruxsat darajasi — bu orqali qaysi toollarni chaqirishi mumkin."""

    trust_level: TrustLevel = TrustLevel.SYSTEM
    """Agent chiqishi ishonch darajasi."""

    max_steps: int = Field(default=10, ge=1, le=50)
    """Bitta run uchun maksimal qadam soni (A-07 tormoz)."""

    max_tool_calls: int = Field(default=20, ge=1, le=100)
    """Bitta run uchun maksimal tool chaqiruvlari (A-07 tormoz)."""

    timeout_s: int = Field(default=120, ge=10, le=600)
    """Bitta run uchun maksimal vaqt (sekundda)."""

    version: int = Field(default=1, ge=1)
    """Agent versiyasi."""


class AgentState(BaseModel, frozen=True):
    """Agent holati — runtime'da ishlatiladi."""

    spec: AgentSpec
    """Agent spetsifikatsiyasi."""

    status: AgentStatus = AgentStatus.DRAFT
    """Hozirgi holat (V-11)."""

    id: str = ""
    """DB dagi ID (UUID string)."""

    created_at: datetime | None = None
    """Yaratilgan vaqt."""

    updated_at: datetime | None = None
    """Oxirgi yangilangan vaqt."""

    # Metrikalar
    total_runs: int = 0
    """Jami run soni."""

    successful_runs: int = 0
    """Muvaffaqiyatli runlar."""

    failed_runs: int = 0
    """Muvaffaqiyatsiz runlar."""

    total_tool_calls: int = 0
    """Jami tool chaqiruvlari."""

    @property
    def success_rate(self) -> float:
        """Muvaffaqiyat foizi (0.0 - 1.0)."""
        if self.total_runs == 0:
            return 0.0
        return self.successful_runs / self.total_runs


class AgentRunResult(BaseModel, frozen=True):
    """Agent run natijasi — hisobot."""

    agent_name: str
    """Agent nomi."""

    success: bool
    """Muvaffaqiyatli bajarildi."""

    output: str = ""
    """Chiqish matni (hisobot)."""

    sources: list[str] = Field(default_factory=list)
    """Foydalanilgan manbalar (URL, fayl nomi va h.k.)."""

    tool_calls_count: int = 0
    """Tool chaqiruvlari soni."""

    steps_count: int = 0
    """Qadamlar soni."""

    error: str | None = None
    """Xato xabari (agar success=False)."""

    metadata: dict[str, Any] = Field(default_factory=dict)
    """Qo'shimcha ma'lumot."""

    tool_results: list[ToolResult] = Field(default_factory=list)
    """JB-15 — run davomida bajarilgan HAR bir tool chaqiruvining XOM
    (raw) natijasi, tartibda.

    NEGA kerak (audit topilmasi): `output` — agentning O'ZI yozgan
    YAKUNIY matn xulosasi (LLM tool natijasini o'z so'zi bilan qayta
    aytib beradi), tool'ning haqiqiy strukturaviy qaytish qiymati
    (masalan `{"message_id": 123, "path": "...", "number": 42}`) UNDA
    YO'Q. `EvidenceProvider` (`core/evidence.py`) HAQIQIY tashqi holat
    dalili uchun aynan shu XOM qiymatga muhtoj — agentning matn
    paraphrase'iga emas ("agent shunday deb aytdi" ≠ "dalil"). Additive
    maydon — default bo'sh ro'yxat, mavjud chaqiruvchilarga ta'sir yo'q."""
