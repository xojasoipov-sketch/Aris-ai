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
    CRMDealListTool,
    CRMLeadCreateTool,
    CRMLeadListTool,
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


async def test_lead_list_and_deal_list(crm_scope: CRMScope) -> None:
    """JB-17 audit topilmasi tuzatishi — o'qish tool'i endi mavjud."""
    contact = await CRMContactCreateTool(scope=crm_scope).execute({"name": "Dilnoza"})
    lead = await CRMLeadCreateTool(scope=crm_scope).execute(
        {"contact_id": contact.output["contact"]["id"], "source": "web", "score": 40}
    )
    await CRMDealCreateTool(scope=crm_scope).execute(
        {"lead_id": lead.output["lead"]["id"], "title": "Test bitim", "amount": 250_000}
    )

    leads = await CRMLeadListTool(scope=crm_scope).execute({})
    assert leads.success
    assert len(leads.output["leads"]) == 1
    assert leads.output["leads"][0]["source"] == "web"

    deals = await CRMDealListTool(scope=crm_scope).execute({})
    assert deals.success
    assert len(deals.output["deals"]) == 1
    assert deals.output["deals"][0]["title"] == "Test bitim"


async def test_lead_list_filters_by_status(crm_scope: CRMScope) -> None:
    contact = await CRMContactCreateTool(scope=crm_scope).execute({"name": "Eldor"})
    await CRMLeadCreateTool(scope=crm_scope).execute(
        {"contact_id": contact.output["contact"]["id"]}
    )

    matched = await CRMLeadListTool(scope=crm_scope).execute({"status": "new"})
    assert matched.success
    assert len(matched.output["leads"]) == 1

    unmatched = await CRMLeadListTool(scope=crm_scope).execute({"status": "qualified"})
    assert unmatched.success
    assert unmatched.output["leads"] == []


async def test_lead_list_and_deal_list_no_scope_returns_clear_error() -> None:
    lead_tool = CRMLeadListTool(scope=None)
    result = await lead_tool.execute({})
    assert result.success is False
    assert "ulanmagan" in (result.error or "").lower()

    deal_tool = CRMDealListTool(scope=None)
    result = await deal_tool.execute({})
    assert result.success is False
    assert "ulanmagan" in (result.error or "").lower()


class TestReadWriteDescriptionsDisambiguate:
    """JB-17: crm.lead_create/deal_create O'ZI HAM 'bu YARATADI, RO'YXATLASH
    uchun EMAS' deb aytadi — LLM Planner nomga qarab chalkashmasin."""

    def test_lead_create_points_to_lead_list(self) -> None:
        desc = CRMLeadCreateTool(scope=None).description
        assert "YOZISH" in desc
        assert "crm.lead_list" in desc

    def test_deal_create_points_to_deal_list(self) -> None:
        desc = CRMDealCreateTool(scope=None).description
        assert "YOZISH" in desc
        assert "crm.deal_list" in desc

    def test_lead_list_description_says_read(self) -> None:
        assert "O'QISH" in CRMLeadListTool(scope=None).description

    def test_deal_list_description_says_read(self) -> None:
        assert "O'QISH" in CRMDealListTool(scope=None).description


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
    assert "crm.lead_list" in names
    assert "crm.deal_create" in names
    assert "crm.deal_list" in names
    assert "crm.stats" in names
