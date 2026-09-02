"""Suhbat tarixi endpoint'i (Z47.1).

    GET /api/v1/conversations/{channel}/messages

NEGA KERAK BO'LDI.

`/messages` sahifasi to'rtta TO'LIQ O'YLAB TOPILGAN suhbatni
ko'rsatardi — o'ylab topilgan vaqt tamg'alari va mazmun bilan
("PR #42 ko'rib chiqildi, CI yashil"). Yozish maydoni ham bor edi,
lekin yuborish tugmasi matnni shunchaki TASHLAB YUBORARDI: hech
qayerga qo'shilmasdi, hech qayerga yuborilmasdi.

Haqiqiy suhbat esa `conversation`/`message` jadvallarida yotardi va
uni o'qish uchun HTTP yo'li yo'q edi.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from zet.api.deps import get_config, get_db_session
from zet.config import Settings
from zet.db.bootstrap import get_or_create_owner
from zet.db.models.owner import Message
from zet.domain.enums import MessageRole
from zet.memory.conversation import ConversationStore

router = APIRouter(prefix="/conversations", tags=["conversations"])

MAX_LIMIT = 200


class MessageResponse(BaseModel):
    id: str
    role: MessageRole
    content: str
    created_at: datetime


@router.get("/{channel}/messages", response_model=list[MessageResponse])
async def list_messages(
    channel: str,
    limit: int = Query(default=50, ge=1, le=MAX_LIMIT),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_config),
) -> list[MessageResponse]:
    """Kanal suhbatidagi oxirgi xabarlar (eng eskisi birinchi).

    `recent_history()` domen formatini (rol + matn) qaytaradi va
    vaqt tamg'asini tashlab yuboradi — UI uchun esa u kerak, shuning
    uchun bu yerda jadval to'g'ridan-to'g'ri o'qiladi.
    """
    owner = await get_or_create_owner(session, external_id=settings.owner_id)
    conversation = await ConversationStore(session, owner_id=owner.id).get_or_create(
        channel=channel
    )

    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    rows.reverse()

    return [
        MessageResponse(
            id=str(row.id),
            role=row.role,
            content=row.content,
            created_at=row.created_at,
        )
        for row in rows
        # TOOL/SYSTEM — ichki mexanika, ega bilan suhbatning qismi emas.
        if row.role in {MessageRole.USER, MessageRole.ASSISTANT}
    ]
