"""Mission DB modellari — strategiya qatlami (Bo'lim 2, §2.2).

NEGA Mission Run'dan alohida. Mavjud Run/Plan mashinasi bitta bajarish
siklini bildiradi (intent → reja → bajarish → tekshirish). Ega esa "sayt
qur", "biznesni ochish" kabi ko'p bosqichli maqsad beradi — bu bir
Run'ga sig'maydi va tashqi kontekst (Obsidian, memory, GitHub, jonli
manba) topilishini talab qiladi.

Ilgari agentlar shu vazifani hech qanday umumiy holat bo'lmagan holda
ketma-ket runlar bilan bajarardi: retry qilingan urinishlar bir-biriga
bog'liq emasdi, va "kecha qilgan ishni davom ettir" iltimosi to'g'ri
kontekstni topib olmagan bo'lardi. Mission jadvali shu davomiylikni
saqlaydi.

Bog'liq qarorlar:
    A-01 — holat bazaga saqlanadi (Mission ham davomli holat mashinasi)
    V-32 — majburiy tasdiq (RiskLevel + WAITING_APPROVAL)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from zet.db.base import Base, JSONType, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin
from zet.domain.enums import MissionStatus, RiskLevel


class Mission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Mission — ega bergan maqsad va uning konteksti/rejasi/xotirasi.

    Bir Mission 1..N Run tug'diradi: birinchisi asosiy urinish,
    keyingilari `RecoveryEngine` qayta urinishlari (§2.5). Barcha
    urinishlar `mission_run` join jadvali orqali bog'lanadi.
    """

    __tablename__ = "mission"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("owner.id", ondelete="CASCADE"), index=True
    )
    objective: Mapped[str] = mapped_column(Text)
    """Egadan kelgan tabiiy tildagi maqsad ("sayt qur", "biznesni ochamiz")."""

    outcome_criteria: Mapped[str] = mapped_column(Text, default="")
    """"Bajarildi" nima ekanligini ta'riflaydi — Verifier shundan foydalanadi."""

    context: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    """ContextDiscoveryEngine (§2.3) topgan tegishli kontekst (`RelevantContext.to_dict()`)."""

    constraints: Mapped[list[str]] = mapped_column(JSONType, default=list)
    tasks: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    """`MissionTask[]` — DAG tugunlari (Pydantic model'lar JSON'ga serializatsiya qilingan)."""

    agents: Mapped[list[str]] = mapped_column(JSONType, default=list)
    tools: Mapped[list[str]] = mapped_column(JSONType, default=list)
    capabilities: Mapped[list[str]] = mapped_column(JSONType, default=list)
    permissions_required: Mapped[list[str]] = mapped_column(JSONType, default=list)

    risk_level: Mapped[RiskLevel] = mapped_column(default=RiskLevel.LOW, index=True)
    approval_requirements: Mapped[list[str]] = mapped_column(JSONType, default=list)

    deadline: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None, index=True)
    verification_rules: Mapped[list[str]] = mapped_column(JSONType, default=list)
    memory_updates: Mapped[list[str]] = mapped_column(JSONType, default=list)

    status: Mapped[MissionStatus] = mapped_column(default=MissionStatus.RECEIVED, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=5, index=True)

    pending_approval_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    """Aktiv approval so'rovi ID'si. ApprovalService in-memory bo'lgani uchun
    FK qo'ymaymiz — u restart'da yo'qoladi va FK yiqilardi."""

    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, default=None)

    claimed_by: Mapped[str | None] = mapped_column(String(128), default=None)
    """JB-11 — restart-recovery egalik lease'i. Bir process/worker mission'ni
    `run_to_completion()` bilan haydashdan OLDIN shu maydonni O'ZINING
    identifikatoriga o'rnatadi (atomik `UPDATE ... WHERE claimed_by IS
    NULL OR claim_expires_at < now()`). Boshqa worker bir xil mission'ni
    parallel haydab ketmasligi shu bilan ta'minlanadi — `asyncio.Lock`
    faqat BITTA process ichida ishlaydi, bu esa DB-native va ko'p
    worker/pod holatida ham ishlaydi."""

    claim_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    """`claimed_by` lease'ining tugash vaqti. CRASH bo'lgan worker
    mission'ni ABADIY qulflab qo'ymasligi uchun — lease muddati
    o'tgach, boshqa worker qayta da'vo qila oladi (§13 "recovery
    lease")."""

    __table_args__ = (
        Index("ix_mission_owner_status", "owner_id", "status"),
        Index("ix_mission_owner_deadline", "owner_id", "deadline"),
        Index("ix_mission_owner_priority", "owner_id", "priority"),
    )


class MissionRunLink(TimestampMixin, Base):
    """Mission ↔ Run join jadvali.

    NEGA join jadvali: bir Mission 1..N Run tug'diradi (asosiy + recovery
    urinishlar). Run jadvaliga majburiy `mission_id` FK qo'yish mavjud
    Orchestrator/executor oqimini buzardi — Runlar Mission'siz ham
    ishlaydi (masalan tez "vaqt necha bo'ldi" so'rovi Mission qatlamiga
    kirmaydi).
    """

    __tablename__ = "mission_run"

    mission_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mission.id", ondelete="CASCADE"), primary_key=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("run.id", ondelete="CASCADE"), primary_key=True
    )
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    """1 — asosiy urinish, 2..N — recovery qayta urinishlari."""

    __table_args__ = (Index("ix_mission_run_run_id", "run_id"),)
