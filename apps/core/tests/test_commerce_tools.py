"""Commerce agent tool'lari testlari (E-commerce agent uchun)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from zet.commerce.repository import CommerceRepository
from zet.db.bootstrap import get_or_create_owner
from zet.db.session import session_scope
from zet.domain.commerce import OrderItem
from zet.tools.builtin.commerce_tools import (
    CommerceScope,
    OrdersListTool,
    OrderStatusUpdateTool,
    ProductCreateTool,
    ProductListTool,
    ProductSearchTool,
    SalesStatsTool,
)


@pytest.fixture()
def commerce_scope(session_factory: async_sessionmaker[AsyncSession]) -> CommerceScope:
    @asynccontextmanager
    async def _scope() -> AsyncIterator[CommerceRepository]:
        async with session_scope(session_factory) as session:
            owner = await get_or_create_owner(session, external_id="commerce-tools-test")
            yield CommerceRepository(session, owner_id=owner.id)

    return _scope


async def test_product_create_then_search(commerce_scope: CommerceScope) -> None:
    create = ProductCreateTool(scope=commerce_scope)
    result = await create.execute({"name": "Krossovka", "price_uzs": 250_000, "stock_qty": 5})
    assert result.success
    assert result.output["product"]["price_uzs"] == 250_000

    search = ProductSearchTool(scope=commerce_scope)
    found = await search.execute({"query": "Kross"})
    assert found.success
    assert len(found.output["products"]) == 1


async def test_product_list_defaults_to_active_only(commerce_scope: CommerceScope) -> None:
    await ProductCreateTool(scope=commerce_scope).execute({"name": "Faol"})
    result = await ProductListTool(scope=commerce_scope).execute({})
    assert result.success
    assert len(result.output["products"]) == 1
    assert result.output["products"][0]["active"] is True


async def test_orders_list_and_status_update(
    commerce_scope: CommerceScope,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # Seed one order directly (agent order-create tool'i yo'q, deliberatly)
    async with session_scope(session_factory) as session:
        owner = await get_or_create_owner(session, external_id="commerce-tools-test")
        commerce = CommerceRepository(session, owner_id=owner.id)
        order = await commerce.create_order(
            items=[OrderItem(name="X", quantity=1, unit_price_uzs=100_000)]
        )
        order_id = str(order.id)
        await session.commit()

    listed = await OrdersListTool(scope=commerce_scope).execute({})
    assert listed.success
    assert len(listed.output["orders"]) == 1

    updated = await OrderStatusUpdateTool(scope=commerce_scope).execute(
        {"order_id": order_id, "status": "confirmed"}
    )
    assert updated.success
    assert updated.output["order"]["status"] == "confirmed"


async def test_sales_stats_returns_zero_when_no_delivered(commerce_scope: CommerceScope) -> None:
    result = await SalesStatsTool(scope=commerce_scope).execute({"days": 30})
    assert result.success
    assert result.output["sales_uzs"] == 0
    assert result.output["orders_total"] == 0


async def test_no_scope_returns_clear_error() -> None:
    tool = ProductSearchTool(scope=None)
    assert tool.connected is False
    result = await tool.execute({"query": "x"})
    assert result.success is False
    assert "ulanmagan" in (result.error or "").lower()


async def test_registered_in_default_registry(tmp_path) -> None:
    from zet.tools.builtin import build_default_registry

    registry = build_default_registry(notes_dir=tmp_path)
    names = set(registry.tool_names())
    for expected in (
        "product.search",
        "product.list",
        "product.create",
        "order.list",
        "order.set_status",
        "sales.stats",
    ):
        assert expected in names, expected


def test_ecommerce_agent_spec_uses_commerce_tools() -> None:
    from zet.agents.builtin.ecommerce import ECOMMERCE_AGENT_SPEC

    for expected in ("product.search", "order.list", "order.set_status", "sales.stats"):
        assert expected in ECOMMERCE_AGENT_SPEC.tool_allowlist, expected


def test_qa_agent_spec_uses_github() -> None:
    from zet.agents.builtin.qa import QA_AGENT_SPEC

    assert "github.read" in QA_AGENT_SPEC.tool_allowlist
    assert "github.write" in QA_AGENT_SPEC.tool_allowlist


def test_new_specs_pass_eval() -> None:
    """QA va E-commerce yangi spec'lari static eval'dan o'tadi."""
    from zet.agents.builtin.ecommerce import ECOMMERCE_AGENT_SPEC
    from zet.agents.builtin.qa import QA_AGENT_SPEC
    from zet.agents.eval import EvalRunner

    for spec in (QA_AGENT_SPEC, ECOMMERCE_AGENT_SPEC):
        result = EvalRunner().run_eval(spec)
        assert result.success, f"{spec.name} eval failed: {result.cases}"
