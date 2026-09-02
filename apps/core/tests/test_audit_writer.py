"""Audit log yozish testlari (V-33, SR-02).

`db/models/security.AuditLog` jadvali qurilgan-u hech qayerdan
yozilmasdi (audit was empty in prod). Bu testlar yozish real
ishlashini tekshiradi + fail-open (session_factory=None) qulaydi.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.db.models.security import AuditLog
from zet.domain.enums import PermissionLevel
from zet.security.audit_writer import write_audit


async def test_write_audit_persists_row(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await write_audit(
        session_factory,
        actor="owner",
        action="killswitch.engaged",
        detail={"reason": "test"},
    )

    async with session_factory() as session:
        rows = (await session.execute(select(AuditLog))).scalars().all()

    assert len(rows) == 1
    assert rows[0].actor == "owner"
    assert rows[0].action == "killswitch.engaged"
    assert rows[0].detail == {"reason": "test"}


async def test_write_audit_all_optional_fields(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    import uuid

    run_id = uuid.uuid4()
    await write_audit(
        session_factory,
        actor="agent:ceo",
        action="tool.execute",
        target="telegram.channel_post",
        permission_level=PermissionLevel.WRITE,
        run_id=run_id,
        detail={"step": 2},
    )

    async with session_factory() as session:
        row = (await session.execute(select(AuditLog))).scalar_one()

    assert row.target == "telegram.channel_post"
    assert row.permission_level == PermissionLevel.WRITE
    assert row.run_id == run_id
    assert row.detail == {"step": 2}


async def test_none_session_factory_is_noop() -> None:
    """`session_factory=None` — hech narsa qilmaydi, crash bermaydi (lean rejim)."""
    await write_audit(
        None,
        actor="owner",
        action="test",
    )
    # Xato yo'q — bo'ldi


async def test_write_audit_fail_open_on_db_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Xato bo'lganda audit `warning` log yozib, chaqiruvchini bloklamaydi."""

    class BrokenFactory:
        def __call__(self) -> AsyncSession:
            raise RuntimeError("DB down")

    # Bu chaqiruvchi tomondan crash bermasligi kerak
    await write_audit(
        BrokenFactory(),  # type: ignore[arg-type]
        actor="owner",
        action="test",
    )
