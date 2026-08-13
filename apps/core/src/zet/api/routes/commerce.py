"""Savdo API — mahsulot katalogi va buyurtmalar (Z51).

    GET/POST         /api/v1/products
    GET/PATCH        /api/v1/products/{id}
    GET/POST         /api/v1/orders
    GET/PATCH        /api/v1/orders/{id}
    PATCH            /api/v1/orders/{id}/status

`workspace.py` bilan bir xil naqsh — route'lar SQL yozmaydi, butun
mantiq `CommerceRepository`da.

Bog'liq qarorlar:
    A-01 — holat bazaga saqlanadi
    Z51 — domain/commerce.py: nega Order CRMDeal'dan ajratilgan
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from zet.api.deps import get_commerce
from zet.commerce.repository import CommerceNotFoundError, CommerceRepository
from zet.domain.commerce import OrderItem, OrderStatus

router = APIRouter(tags=["commerce"])


# ── Javob modellari ──────────────────────────────────────────────


class ProductResponse(BaseModel):
    id: str
    name: str
    sku: str
    description: str
    price_uzs: float
    stock_qty: int
    active: bool
    created_at: datetime


class OrderResponse(BaseModel):
    id: str
    contact_id: str | None
    status: OrderStatus
    items: list[OrderItem]
    total_uzs: float
    notes: str
    shipped_notified_at: datetime | None
    created_at: datetime


# ── So'rov modellari ─────────────────────────────────────────────


class ProductCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    price_uzs: float = Field(default=0.0, ge=0)
    stock_qty: int = Field(default=0, ge=0)
    sku: str = ""


class ProductUpdateRequest(BaseModel):
    """Faqat berilgan maydonlar o'zgaradi (`None` = tegilmaydi)."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    price_uzs: float | None = Field(default=None, ge=0)
    stock_qty: int | None = Field(default=None, ge=0)
    sku: str | None = None
    active: bool | None = None


class OrderCreateRequest(BaseModel):
    items: list[OrderItem] = Field(..., min_length=1)
    contact_id: str | None = None
    notes: str = ""


class OrderStatusUpdateRequest(BaseModel):
    status: OrderStatus


# ── Yordamchilar ─────────────────────────────────────────────────


def _require_uuid(value: str, *, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Noto'g'ri {field}: {value}") from exc


def _optional_uuid(value: str | None, *, field: str) -> uuid.UUID | None:
    if value is None or value == "":
        return None
    return _require_uuid(value, field=field)


def _product_response(product: object) -> ProductResponse:
    return ProductResponse(
        id=str(product.id),  # type: ignore[attr-defined]
        name=product.name,  # type: ignore[attr-defined]
        sku=product.sku,  # type: ignore[attr-defined]
        description=product.description,  # type: ignore[attr-defined]
        price_uzs=product.price_uzs,  # type: ignore[attr-defined]
        stock_qty=product.stock_qty,  # type: ignore[attr-defined]
        active=product.active,  # type: ignore[attr-defined]
        created_at=product.created_at,  # type: ignore[attr-defined]
    )


def _order_response(order: object) -> OrderResponse:
    return OrderResponse(
        id=str(order.id),  # type: ignore[attr-defined]
        contact_id=str(order.contact_id) if order.contact_id else None,  # type: ignore[attr-defined]
        status=order.status,  # type: ignore[attr-defined]
        items=[OrderItem.model_validate(item) for item in order.items],  # type: ignore[attr-defined]
        total_uzs=order.total_uzs,  # type: ignore[attr-defined]
        notes=order.notes,  # type: ignore[attr-defined]
        shipped_notified_at=order.shipped_notified_at,  # type: ignore[attr-defined]
        created_at=order.created_at,  # type: ignore[attr-defined]
    )


# ── Mahsulotlar ──────────────────────────────────────────────────


@router.get("/products", response_model=list[ProductResponse])
async def list_products(
    active_only: bool = True,
    repo: CommerceRepository = Depends(get_commerce),
) -> list[ProductResponse]:
    products = await repo.list_products(active_only=active_only)
    return [_product_response(p) for p in products]


@router.post("/products", response_model=ProductResponse, status_code=201)
async def create_product(
    request: ProductCreateRequest,
    repo: CommerceRepository = Depends(get_commerce),
) -> ProductResponse:
    product = await repo.create_product(**request.model_dump())
    return _product_response(product)


@router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: str,
    repo: CommerceRepository = Depends(get_commerce),
) -> ProductResponse:
    try:
        product = await repo.get_product(_require_uuid(product_id, field="product_id"))
    except CommerceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _product_response(product)


@router.patch("/products/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: str,
    request: ProductUpdateRequest,
    repo: CommerceRepository = Depends(get_commerce),
) -> ProductResponse:
    try:
        product = await repo.update_product(
            _require_uuid(product_id, field="product_id"), **request.model_dump()
        )
    except CommerceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _product_response(product)


# ── Buyurtmalar ──────────────────────────────────────────────────


@router.get("/orders", response_model=list[OrderResponse])
async def list_orders(
    status: OrderStatus | None = None,
    repo: CommerceRepository = Depends(get_commerce),
) -> list[OrderResponse]:
    orders = await repo.list_orders(status=status)
    return [_order_response(o) for o in orders]


@router.post("/orders", response_model=OrderResponse, status_code=201)
async def create_order(
    request: OrderCreateRequest,
    repo: CommerceRepository = Depends(get_commerce),
) -> OrderResponse:
    order = await repo.create_order(
        items=request.items,
        contact_id=_optional_uuid(request.contact_id, field="contact_id"),
        notes=request.notes,
    )
    return _order_response(order)


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: str,
    repo: CommerceRepository = Depends(get_commerce),
) -> OrderResponse:
    try:
        order = await repo.get_order(_require_uuid(order_id, field="order_id"))
    except CommerceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _order_response(order)


@router.patch("/orders/{order_id}/status", response_model=OrderResponse)
async def update_order_status(
    order_id: str,
    request: OrderStatusUpdateRequest,
    repo: CommerceRepository = Depends(get_commerce),
) -> OrderResponse:
    try:
        order = await repo.update_order_status(
            _require_uuid(order_id, field="order_id"), request.status
        )
    except CommerceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _order_response(order)
