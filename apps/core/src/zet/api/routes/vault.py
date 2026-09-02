"""Obsidian vault endpoint'i — eslatmalar (Z47.2).

    GET /api/v1/vault/notes         — eslatmalar ro'yxati (ixtiyoriy qidiruv)
    GET /api/v1/vault/notes/{title} — bitta eslatma matni

NEGA KERAK BO'LDI.

`/files` sahifasi yagona halol placeholder edi — `ComingSoon`
ko'rsatardi va manba sifatida `note.write/read/list (vault)` deb
yozib qo'yilgandi. Tool'lar HAQIQATAN mavjud va ishlaydi (LLM ularni
chaqira oladi), lekin ega ularni interfeys orqali ko'ra olmasdi.

Bu route'lar `note.list`/`note.read` tool'larining AYNI mantiqini
qayta ishlatadi — vault bilan ikkinchi, mustaqil kod yo'li
yaratilmaydi.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from zet.api.deps import get_tool_registry
from zet.domain.enums import PermissionLevel
from zet.tools.registry import ToolRegistry

router = APIRouter(prefix="/vault", tags=["vault"])


class NoteSummary(BaseModel):
    title: str
    size_bytes: int
    modified_at: float


class NoteListResponse(BaseModel):
    notes: list[NoteSummary]
    total: int


class NoteContent(BaseModel):
    title: str
    content: str


@router.get("/notes", response_model=NoteListResponse)
async def list_notes(
    query: str = Query(default="", max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    registry: ToolRegistry = Depends(get_tool_registry),
) -> NoteListResponse:
    """Vault'dagi eslatmalar.

    `path` ATAYIN qaytarilmaydi: u serverning ichki fayl tuzilishini
    oshkor qiladi va brauzerga hech qanday foyda bermaydi.
    """
    result = await registry.execute(
        "note.list",
        {"query": query, "limit": limit},
        caller_permission=PermissionLevel.READ,
    )
    if not result.success:
        raise HTTPException(status_code=500, detail=result.error or "note.list yiqildi")

    output = result.output or {}
    return NoteListResponse(
        notes=[
            NoteSummary(
                title=note["title"],
                size_bytes=note["size_bytes"],
                modified_at=note["modified_at"],
            )
            for note in output.get("notes", [])
        ],
        total=output.get("total", 0),
    )


@router.get("/notes/{title}", response_model=NoteContent)
async def read_note(
    title: str,
    registry: ToolRegistry = Depends(get_tool_registry),
) -> NoteContent:
    """Bitta eslatma matni."""
    result = await registry.execute(
        "note.read",
        {"title": title},
        caller_permission=PermissionLevel.READ,
    )
    if not result.success:
        # Tool "topilmadi" va boshqa xatolarni bir xil qaytaradi —
        # bu yerda 404 aniqroq javob.
        raise HTTPException(status_code=404, detail=result.error or "Eslatma topilmadi")

    output = result.output or {}
    return NoteContent(title=output.get("title", title), content=output.get("content", ""))
