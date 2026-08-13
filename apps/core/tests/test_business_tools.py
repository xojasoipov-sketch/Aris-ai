"""Business Registry agent tool'lari testlari — C2 (KONSOLIDATSIYA v2,
tungi reja Bo'lim C).

`test_crm_tools.py` bilan bir xil naqsh: `crm_scope` orqali real
(in-memory sqlite) DB'ga yozadi/o'qiydi, faqat `PgCRM` fabrikasi
orqali (bir xil sessiya, bir xil CRM birligi — bizneslar CRM'ning
bir qismi).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.business.pg_crm import PgCRM
from zet.db.bootstrap import get_or_create_owner
from zet.db.session import session_scope
from zet.tools.builtin.business_tools import (
    BusinessContactLinkTool,
    BusinessCreateTool,
    BusinessListTool,
    BusinessScope,
)
from zet.tools.builtin.crm_tools import CRMContactCreateTool


@pytest.fixture()
def crm_scope(session_factory: async_sessionmaker[AsyncSession]) -> BusinessScope:
    @asynccontextmanager
    async def _scope() -> AsyncIterator[PgCRM]:
        async with session_scope(session_factory) as session:
            owner = await get_or_create_owner(session, external_id="business-tools-test")
            yield PgCRM(session, owner_id=owner.id)

    return _scope


async def test_business_create_then_list(crm_scope: BusinessScope) -> None:
    create = BusinessCreateTool(scope=crm_scope)
    result = await create.execute({"name": "ZET Lab", "aliases": ["Zetlab"]})
    assert result.success
    assert result.output["business"]["name"] == "ZET Lab"

    listed = await BusinessListTool(scope=crm_scope).execute({})
    assert listed.success
    assert len(listed.output["businesses"]) == 1


async def test_business_list_with_query_filters_by_alias(crm_scope: BusinessScope) -> None:
    await BusinessCreateTool(scope=crm_scope).execute({"name": "ZET Lab", "aliases": ["Zetlab"]})
    await BusinessCreateTool(scope=crm_scope).execute({"name": "Boshqa Kompaniya"})

    result = await BusinessListTool(scope=crm_scope).execute({"query": "zetlab"})
    assert result.success
    assert len(result.output["businesses"]) == 1
    assert result.output["businesses"][0]["name"] == "ZET Lab"


async def test_contact_link_to_business(crm_scope: BusinessScope) -> None:
    contact = await CRMContactCreateTool(scope=crm_scope).execute({"name": "Ali"})
    business = await BusinessCreateTool(scope=crm_scope).execute({"name": "ZET Lab"})

    link = await BusinessContactLinkTool(scope=crm_scope).execute(
        {
            "contact_id": contact.output["contact"]["id"],
            "business_id": business.output["business"]["id"],
        }
    )
    assert link.success
    assert link.output["contact"]["business_id"] == business.output["business"]["id"]


async def test_link_unknown_contact_returns_tool_error(crm_scope: BusinessScope) -> None:
    business = await BusinessCreateTool(scope=crm_scope).execute({"name": "ZET Lab"})
    result = await BusinessContactLinkTool(scope=crm_scope).execute(
        {
            "contact_id": "00000000-0000-0000-0000-000000000000",
            "business_id": business.output["business"]["id"],
        }
    )
    assert result.success is False


async def test_no_scope_returns_clear_error() -> None:
    """Scope berilmasa — jimgina bo'sh emas, aniq xato (crm_tools.py bilan bir xil naqsh)."""
    tool = BusinessCreateTool(scope=None)
    assert tool.connected is False

    result = await tool.execute({"name": "X"})
    assert result.success is False
    assert "ulanmagan" in (result.error or "").lower()


async def test_registered_in_default_registry(tmp_path) -> None:
    """`build_default_registry` business tool'larini ro'yxatga oladi."""
    from zet.tools.builtin import build_default_registry

    registry = build_default_registry(notes_dir=tmp_path)
    names = set(registry.tool_names())
    assert "business.create" in names
    assert "business.list" in names
    assert "business.contact_link" in names


async def test_risk_levels_match_crm_pattern() -> None:
    """C2 reja: `business.create`/`business.contact_link` — MEDIUM (CRM
    yozuvlari bilan bir xil daraja); `business.list` READ, MEDIUM'da YO'Q."""
    from zet.security.risk import RiskLevel, risk_for

    assert risk_for("business.create") == RiskLevel.MEDIUM
    assert risk_for("business.contact_link") == RiskLevel.MEDIUM
    assert risk_for("business.list") == RiskLevel.LOW
