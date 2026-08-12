"""Suhbat tarixi — ZET oldingi gapni eslab qolishi uchun (Z44).

MUAMMO. `conversation` va `message` jadvallari sxemada bor edi, lekin
ularga HECH KIM YOZMASDI. Natijada har bir Telegram xabari mustaqil run
bo'lardi va ZET oldingi gapni eslamasdi:

    ega:  "Nimalar qilolasan?"
    ZET:  <imkoniyatlar haqida javob>
    ega:  "Tushuntir"
    ZET:  "Nimani tushuntirib berishimni xohlaysiz?"   ← kontekst yo'q

Ega buni haqli ravishda "meni tanimayapti" deb baholadi.

Bu modul o'sha jadvallarni ishga soladi: har bir xabar (ega va ZET
javobi) yoziladi, keyingi run esa oxirgi almashinuvlarni kontekst
sifatida oladi.

NEGA DB, XOTIRA EMAS. Railway konteyneri har deploy'da qayta ishga
tushadi. Xotiradagi tarix o'shanda yo'qolardi — ya'ni ZET har
yangilanishdan keyin egani "unutardi". Postgres endi volume'da
(Z39), shuning uchun tarix omon qoladi.

CHEGARA: `DEFAULT_HISTORY_LIMIT` ta oxirgi xabar olinadi. Butun tarixni
uzatish token narxini va kechikishni cheksiz o'stirardi.

Bog'liq qarorlar:
    V-13 — 7 qatlamli xotira (bu CONVERSATION qatlami)
    A-05 — har xabarning `trust_level`i saqlanadi
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zet.db.models.owner import Conversation, Message
from zet.domain.command import ConversationTurn
from zet.domain.enums import MessageRole, TrustLevel

log = structlog.get_logger(__name__)

DEFAULT_HISTORY_LIMIT = 10
"""Kontekstga qo'shiladigan oxirgi xabarlar soni (5 ta almashinuv).

Ko'paytirish kontekstni boyitadi, lekin har run narxini oshiradi —
free tier kvotalari uchun 10 oqilona muvozanat.
"""

MAX_CONTENT_CHARS = 4000
"""Bitta xabarning saqlanadigan maksimal uzunligi."""


class ConversationStore:
    """Suhbat tarixini `conversation`/`message` jadvallarida saqlaydi."""

    def __init__(self, session: AsyncSession, *, owner_id: uuid.UUID) -> None:
        self._session = session
        self._owner_id = owner_id

    async def get_or_create(self, *, channel: str) -> Conversation:
        """Kanal uchun suhbatni topadi yoki yaratadi.

        Bitta kanal = bitta uzluksiz suhbat. ZET bitta egaga tegishli
        (V-02), shuning uchun Telegram'da bir nechta parallel suhbat
        tushunchasi yo'q — ega bilan muloqot uzluksiz oqim.
        """
        stmt = (
            select(Conversation)
            .where(Conversation.owner_id == self._owner_id, Conversation.channel == channel)
            .order_by(Conversation.created_at.desc())
            .limit(1)
        )
        existing = (await self._session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            return existing

        conversation = Conversation(owner_id=self._owner_id, channel=channel)
        self._session.add(conversation)
        await self._session.flush()
        log.info("conversation.created", id=str(conversation.id), channel=channel)
        return conversation

    async def append(
        self,
        conversation: Conversation,
        *,
        role: MessageRole,
        content: str,
        trust_level: TrustLevel = TrustLevel.OWNER,
    ) -> Message:
        """Suhbatga xabar qo'shadi."""
        message = Message(
            conversation_id=conversation.id,
            role=role,
            content=content[:MAX_CONTENT_CHARS],
            trust_level=trust_level,
        )
        self._session.add(message)
        await self._session.flush()
        return message

    async def recent_history(
        self,
        conversation: Conversation,
        *,
        limit: int = DEFAULT_HISTORY_LIMIT,
    ) -> list[ConversationTurn]:
        """Oxirgi xabarlarni domen formatida qaytaradi (eng eskisi birinchi).

        `TOOL` va `SYSTEM` rollari o'tkazib yuboriladi — ular ichki
        mexanika, ega bilan suhbatning bir qismi emas.
        """
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
        rows = list((await self._session.execute(stmt)).scalars().all())
        rows.reverse()  # eng eskisi birinchi — LLM shu tartibni kutadi

        return [
            ConversationTurn(role=row.role, content=row.content)
            for row in rows
            if row.role in {MessageRole.USER, MessageRole.ASSISTANT}
        ]


__all__ = ["DEFAULT_HISTORY_LIMIT", "MAX_CONTENT_CHARS", "ConversationStore"]
