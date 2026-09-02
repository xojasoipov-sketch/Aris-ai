"""Commerce agent tool'lari — mahsulot/buyurtma boshqaruvi (E-commerce agent).

CommerceRepository ilgari REST API'da va shop bot'da ishlagan-u,
ega bilan gaplashadigan asosiy ZET agenti mahsulot yoki buyurtmani
boshqara olmasdi. Bu tool'lar shu bo'shliqni yopadi.

Naqsh: `crm_tools.py`/`workspace_tools.py` bilan bir xil — CommerceScope
factory har chaqiruvda qisqa DB sessiya beradi.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Any

from zet.domain.commerce import OrderItem, OrderStatus
from zet.domain.enums import PermissionLevel
from zet.tools.base import Tool, ToolError

if TYPE_CHECKING:
    from zet.commerce.repository import CommerceRepository

CommerceScope = Callable[[], "AbstractAsyncContextManager[CommerceRepository]"]


class _CommerceTool(Tool):
    def __init__(self, *, scope: CommerceScope | None = None) -> None:
        self._scope = scope

    @property
    def connected(self) -> bool:
        return self._scope is not None

    def _require_scope(self) -> CommerceScope:
        if self._scope is None:
            raise ToolError("Commerce bazasi ulanmagan — mahsulot/buyurtma tool'lari ishlamaydi")
        return self._scope


class ProductSearchTool(_CommerceTool):
    """Mahsulotni nom/tavsifda qidiradi."""

    @property
    def name(self) -> str:
        return "product.search"

    @property
    def description(self) -> str:
        return "Mahsulot katalogidan nom/tavsif bo'yicha qidirish."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 200},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "required": ["query"],
            "additionalProperties": False,
        }

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        scope = self._require_scope()
        limit = params.get("limit", 10)
        async with scope() as commerce:
            products = await commerce.search_products(params["query"], limit=limit)
        return {"products": [_product_dict(p) for p in products]}


class ProductListTool(_CommerceTool):
    """Barcha faol mahsulotlar ro'yxati."""

    @property
    def name(self) -> str:
        return "product.list"

    @property
    def description(self) -> str:
        return "Mahsulot katalogini ko'rsatish (default: faqat faol)."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "active_only": {"type": "boolean"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500},
            },
            "additionalProperties": False,
        }

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        scope = self._require_scope()
        active_only = params.get("active_only", True)
        limit = params.get("limit", 100)
        async with scope() as commerce:
            products = await commerce.list_products(active_only=active_only, limit=limit)
        return {"products": [_product_dict(p) for p in products]}


class ProductCreateTool(_CommerceTool):
    """Yangi mahsulot qo'shish."""

    @property
    def name(self) -> str:
        return "product.create"

    @property
    def description(self) -> str:
        return "Katalogga yangi mahsulot qo'shish."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "minLength": 1, "maxLength": 200},
                "description": {"type": "string", "maxLength": 2000},
                "price_uzs": {"type": "number", "minimum": 0},
                "stock_qty": {"type": "integer", "minimum": 0},
                "sku": {"type": "string", "maxLength": 64},
            },
            "required": ["name"],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.WRITE

    @property
    def idempotent(self) -> bool:
        return False

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        scope = self._require_scope()
        async with scope() as commerce:
            product = await commerce.create_product(**params)
        return {"product": _product_dict(product)}


class OrdersListTool(_CommerceTool):
    """Buyurtmalar ro'yxati (ixtiyoriy holat filtri)."""

    @property
    def name(self) -> str:
        return "order.list"

    @property
    def description(self) -> str:
        return (
            "O'QISH: Buyurtmalar ro'yxati (yangi birinchi), holat bo'yicha "
            "filtr bilan — har bir buyurtmaning JORIY holatini shu yerdan "
            "bilib olasiz. Holatni O'ZGARTIRISH uchun EMAS — buning uchun "
            "order.set_status."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["new", "confirmed", "shipped", "delivered", "cancelled"],
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            "additionalProperties": False,
        }

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        scope = self._require_scope()
        status = OrderStatus(params["status"]) if params.get("status") else None
        limit = params.get("limit", 50)
        async with scope() as commerce:
            orders = await commerce.list_orders(status=status, limit=limit)
        return {"orders": [_order_dict(o) for o in orders]}


class OrderStatusUpdateTool(_CommerceTool):
    """Buyurtma holatini yangilash (yangi→tasdiq→jo'natildi→yetkazildi)."""

    @property
    def name(self) -> str:
        return "order.set_status"

    @property
    def description(self) -> str:
        return (
            "YOZISH: Buyurtma HOLATINI O'ZGARTIRADI (yangi→tasdiq→"
            "jo'natildi→yetkazildi). SHIPPED holatiga o'tsa mijozga "
            "avtomatik xabar boradi. DIQQAT: nomida 'status' so'zi bor, "
            "lekin bu YOZISH tool'i — buyurtma holatini shunchaki BILISH/"
            "KO'RISH uchun EMAS (buning uchun order.list). order_id VA "
            "yangi status ikkalasi ham majburiy."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "minLength": 1},
                "status": {
                    "type": "string",
                    "enum": ["new", "confirmed", "shipped", "delivered", "cancelled"],
                },
            },
            "required": ["order_id", "status"],
            "additionalProperties": False,
        }

    @property
    def permission_level(self) -> PermissionLevel:
        return PermissionLevel.WRITE

    @property
    def idempotent(self) -> bool:
        # Status idempotent EMAS: agar SHIPPED'ga qayta o'tkazsak,
        # shipped_notified_at reset bo'lmaydi (repository himoyalaydi),
        # lekin `updated_at` yangilanadi va foydalanuvchiga ikkilanish
        # tuyg'usini beradi — shuning uchun False.
        return False

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        import uuid

        scope = self._require_scope()
        try:
            order_id = uuid.UUID(params["order_id"])
        except ValueError as exc:
            raise ToolError(f"Noto'g'ri order_id: {params['order_id']}") from exc
        status = OrderStatus(params["status"])
        async with scope() as commerce:
            order = await commerce.update_order_status(order_id, status)
        return {"order": _order_dict(order)}


class SalesStatsTool(_CommerceTool):
    """Berilgan davrdagi sotuv jami (faqat DELIVERED)."""

    @property
    def name(self) -> str:
        return "sales.stats"

    @property
    def description(self) -> str:
        return "Sotuv statistikasi — oxirgi N kun ichida yetkazilgan buyurtmalar summasi."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 365, "default": 7}},
            "additionalProperties": False,
        }

    async def _execute(self, params: dict[str, Any]) -> dict[str, Any]:
        from datetime import UTC, datetime, timedelta

        scope = self._require_scope()
        days = params.get("days", 7)
        since = datetime.now(tz=UTC) - timedelta(days=days)
        async with scope() as commerce:
            total = await commerce.sales_total_uzs(since=since)
            orders = await commerce.list_orders(since=since, limit=500)
        status_counts: dict[str, int] = {}
        for o in orders:
            key = o.status.value if hasattr(o.status, "value") else str(o.status)
            status_counts[key] = status_counts.get(key, 0) + 1
        return {
            "days": days,
            "sales_uzs": total,
            "orders_total": len(orders),
            "by_status": status_counts,
        }


def _product_dict(product: object) -> dict[str, Any]:
    return {
        "id": str(product.id),  # type: ignore[attr-defined]
        "name": product.name,  # type: ignore[attr-defined]
        "sku": product.sku,  # type: ignore[attr-defined]
        "price_uzs": product.price_uzs,  # type: ignore[attr-defined]
        "stock_qty": product.stock_qty,  # type: ignore[attr-defined]
        "active": product.active,  # type: ignore[attr-defined]
    }


def _order_dict(order: object) -> dict[str, Any]:
    status = order.status  # type: ignore[attr-defined]
    return {
        "id": str(order.id),  # type: ignore[attr-defined]
        "status": status.value if isinstance(status, OrderStatus) else str(status),
        "total_uzs": order.total_uzs,  # type: ignore[attr-defined]
        "items": [_item_dict(it) for it in order.items],  # type: ignore[attr-defined]
        "contact_id": (
            str(order.contact_id) if order.contact_id is not None else None  # type: ignore[attr-defined]
        ),
    }


def _item_dict(item: dict[str, Any] | OrderItem) -> dict[str, Any]:
    if isinstance(item, OrderItem):
        return item.model_dump(mode="json")
    return dict(item)


__all__ = [
    "CommerceScope",
    "OrderStatusUpdateTool",
    "OrdersListTool",
    "ProductCreateTool",
    "ProductListTool",
    "ProductSearchTool",
    "SalesStatsTool",
]
