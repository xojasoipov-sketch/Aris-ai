"""CRM agent tool'lari testlari (GAP_ANALYSIS §5 — CRM as agent tool).

Ilgari Sales/Support agentlarga CRM'ga to'g'ridan-to'g'ri kirish yo'li
yo'q edi. Endi `crm.contact_search`/`contact_create`/`lead_create`/
`deal_create`/`stats` tool'lari registryda va PgCRM bilan bog'langan.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.business.pg_crm import PgCRM
from zet.db.bootstrap import get_or_create_owner
from zet.db.session import session_scope
from zet.tools.builtin.crm_tools import (
    CRMContactCreateTool,
    CRMContactSearchTool,
    CRMDealCreateTool,
    CRMLeadCreateTool,
    CRMScope,
    CRMStatsTool,
)


@pytest.fixture()
def crm_scope(session_factory: async_sessionmaker[AsyncSession]) -> CRMScope:
    @asynccontextmanager
    async def _scope() -> AsyncIterator[PgCRM]:
        async with session_scope(session_factory) as session:
            owner = await get_or_create_owner(session, external_id="crm-tools-test")
            yield PgCRM(session, owner_id=owner.id)

    return _scope


async def test_contact_create_then_search(crm_scope: CRMScope) -> None:
    create = CRMContactCreateTool(scope=crm_scope)
    result = await create.execute({"name": "Aziz", "company": "Zeta"})
    assert result.success
    assert result.output["contact"]["name"] == "Aziz"

    search = CRMContactSearchTool(scope=crm_scope)
    found = await search.execute({"query": "Aziz"})
    assert found.success
    assert len(found.output["contacts"]) == 1
    assert found.output["contacts"][0]["company"] == "Zeta"


async def test_lead_and_deal_chain(crm_scope: CRMScope) -> None:
    contact = await CRMContactCreateTool(scope=crm_scope).execute({"name": "Bek"})
    lead = await CRMLeadCreateTool(scope=crm_scope).execute(
        {"contact_id": contact.output["contact"]["id"], "source": "instagram", "score": 60}
    )
    deal = await CRMDealCreateTool(scope=crm_scope).execute(
        {"lead_id": lead.output["lead"]["id"], "title": "Krossovka 3 juft", "amount": 750000}
    )
    assert deal.success
    assert deal.output["deal"]["amount"] == 750000


async def test_stats_reflects_created(crm_scope: CRMScope) -> None:
    contact = await CRMContactCreateTool(scope=crm_scope).execute({"name": "X"})
    lead = await CRMLeadCreateTool(scope=crm_scope).execute(
        {"contact_id": contact.output["contact"]["id"]}
    )
    await CRMDealCreateTool(scope=crm_scope).execute(
        {"lead_id": lead.output["lead"]["id"], "title": "test", "amount": 100_000}
    )

    stats = await CRMStatsTool(scope=crm_scope).execute({})
    assert stats.success
    assert stats.output["contacts"] == 1
    assert stats.output["leads"] == 1
    assert stats.output["deals"] == 1


async def test_no_scope_returns_clear_error() -> None:
    """Scope berilmasa — jimgina bo'sh emas, aniq xato."""
    tool = CRMContactSearchTool(scope=None)
    assert tool.connected is False

    result = await tool.execute({"query": "hi"})
    assert result.success is False
    assert "ulanmagan" in (result.error or "").lower()


async def test_registered_in_default_registry(tmp_path) -> None:
    """`build_default_registry` CRM tool'larini ro'yxatga oladi."""
    from zet.tools.builtin import build_default_registry

    registry = build_default_registry(notes_dir=tmp_path)
    names = set(registry.tool_names())
    assert "crm.contact_search" in names
    assert "crm.contact_create" in names
    assert "crm.lead_create" in names
    assert "crm.deal_create" in names
    assert "crm.stats" in names
