"""ContextEngine — yig'ma retrieval qatlami (Bo'lim 2, §2.3, Master Spec PART 4).

NEGA bu qatlam kerak. Ilgari LLM promptga har xil manba (memory, notes,
CRM, workspace, GitHub, telegram, kalendar, fayllar, suhbat tarixi)
alohida-alohida qatalar bilan uzatilardi — bir joyda "kim nimani biladi"
tasavvuri yo'q edi. Master Spec PART 4 aynan buni "targeted retrieval,
never a full dump" deb belgilagan: bitta `UserRequest` uchun 8 manba
ustidan aniq nishonli qidiruv, va konflikt bo'lsa — hech qachon "jimjit
qayta yozish" emas.

Ilgari sinf umuman mavjud emas edi (`MissionEngine.discover()` yolg'iz
`ContextDiscoveryEngineLike` protokoli bo'yicha soxta obyekt bilan
ishlardi). Bu modul REAL implementatsiyani beradi va uning shakli:

    UserRequest  →  ContextEngine.discover(...)  →  RelevantContext
                       │
                       ├── _query_memory
                       ├── _query_obsidian
                       ├── _query_workspace
                       ├── _query_crm
                       ├── _query_github         (optional)
                       ├── _query_telegram       (optional)
                       ├── _query_calendar
                       ├── _query_files
                       └── _query_conversation

Barcha manbalar `asyncio.gather` bilan PARALLEL chaqiriladi. Xato bo'lgan
manba fail-open (warning + bo'sh natija), butun `discover()` hech qachon
yiqilmaydi.

Har bir fragment `ContextFragment` sifatida packaged:
    (source, kind, content, tokens, priority, trust, origin_id, ...)

Source-of-Truth Priority Resolver:
    USER_INSTRUCTION(100) > CURRENT_PROJECT(80) > AUTHORITATIVE_SOURCE(60)
    > RECENT_MEMORY(40) > OLDER_MEMORY(20) > INFERENCE(5)

Bir xil `conflict_key` bo'lgan fragmentlar orasida eng yuqori priority
yutadi; yutqizganlar `dropped` ro'yxatiga `labels=['conflict-loser']`
bilan tushadi, `conflicts` ro'yxatiga winner/losers yoziladi — hech
qachon jimjit qayta yozilmaydi (Master Spec PART 4 invariant).

Budget: `MAX_CONTEXT_TOKENS = 8000` (env `ZET_CONTEXT_BUDGET_TOKENS`
bilan sozlanadi). Fragmentlar (priority DESC, similarity DESC, recency
DESC) tartibida saralanadi va budget ichida greedy to'ldiriladi;
oshib ketganlar `dropped`ga o'tadi.

Bog'liq qarorlar:
    Bo'lim 2 §2.3 — kontekst topish qatlami
    Master Spec PART 4 — "no full dump", "never silently overwrite"
    A-05 — UNTRUSTED tashqi matn
    V-14 — trust darajasi (owner/system/external)
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import os
import re
import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import structlog
from pydantic import BaseModel, ConfigDict, Field

from zet.domain.memory import MemoryLayer, MemoryQuery, MemorySearchResult

log = structlog.get_logger(__name__)


# ── Konfiguratsiya konstantalari ────────────────────────────────────


def _env_int(name: str, default: int) -> int:
    """`ZET_*` env o'zgaruvchisidan `int` — noto'g'ri qiymatga default."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _env_float(name: str, default: float) -> float:
    """`ZET_*` env o'zgaruvchisidan `float` — noto'g'ri qiymatga default."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


MAX_CONTEXT_TOKENS: int = _env_int("ZET_CONTEXT_BUDGET_TOKENS", 8000)
"""Kontekst uchun jami token budjeti (Master Spec PART 4: no full dump).

8k — hozirgi asosiy LLM (Mistral Large / Claude Sonnet) uchun system +
history + context + response o'rtasidagi tenglashuv budjeti. Kattaroq
model uchun `ZET_CONTEXT_BUDGET_TOKENS=16000` kabi env orqali oshiriladi.
"""

DEFAULT_SOURCE_TIMEOUT_S: float = _env_float("ZET_CONTEXT_SOURCE_TIMEOUT_S", 3.0)
"""Bitta manba uchun maksimal kutish. Uzoq manba — fail-open (bo'sh)."""

DEFAULT_MAX_FRAGMENTS_PER_SOURCE: int = _env_int("ZET_CONTEXT_MAX_FRAGMENTS_PER_SOURCE", 8)
"""Bitta manbadan olinadigan maksimal fragment. "No full dump" invarianti:
notes/xotira soni qancha bo'lsa ham, bu chegara hech qachon oshirilmaydi."""


# ── Enum'lar ───────────────────────────────────────────────────────


class SourceKind(StrEnum):
    """Fragment qaysi manbadan kelganini belgilaydi.

    Master Spec PART 4 dagi 8+1 manba ro'yxatiga to'g'ri keladi:
    memory + obsidian + workspace + crm + github + telegram + calendar +
    files + conversation.
    """

    MEMORY = "memory"
    OBSIDIAN = "obsidian"
    WORKSPACE = "workspace"
    CRM = "crm"
    GITHUB = "github"
    TELEGRAM = "telegram"
    CALENDAR = "calendar"
    FILES = "files"
    CONVERSATION = "conversation"


class SourcePriority(IntEnum):
    """Source-of-Truth priority — raqamli darajalar.

    Kattaroq son = ustunroq manba. Konflikt bo'lganda `max(priority)`
    yutadi; ties → eng yangi `retrieved_at`. Master Spec PART 4:
    "Never silently overwrite conflicting facts" — yutqizganlar
    `RelevantContext.conflicts` ro'yxatida yoziladi.
    """

    USER_INSTRUCTION = 100
    """Ega joriy so'zi (conversation history'ning oxirgi USER turi).
    Har doim ustun — ega o'z ma'lumotini yangilaganda eski yozuvlarni
    to'g'ridan-to'g'ri qayta yozadi (lekin eski yozuv `conflicts`
    ro'yxatiga tushadi, o'chirilmaydi)."""

    CURRENT_PROJECT = 80
    """Joriy loyihaga aloqador fragment (`hinted_project_id` bilan mos)."""

    AUTHORITATIVE_SOURCE = 60
    """Obsidian, workspace, CRM, kalendar — biznes bilim manbalari."""

    RECENT_MEMORY = 40
    """So'nggi 7 kun ichida yozilgan xotira / telegram / task."""

    OLDER_MEMORY = 20
    """Eski xotira yozuvlari (7 kundan avval)."""

    INFERENCE = 5
    """LLM'ning taxminlari — har doim boshqa manbadan pastroq."""


# ── Domen modellari ────────────────────────────────────────────────


class ContextFragment(BaseModel):
    """Bitta kontekst bo'lagi — retrieval'ning eng kichik birligi.

    `frozen=True` — bir marta yaratilgach, o'zgarmaydi. Bu resolver
    va budget hisoblarida taxmin qilinadi (fragment ID orqali
    identifikatsiya).
    """

    model_config = ConfigDict(frozen=True)

    source: SourceKind
    """Qaysi manbadan olindi."""

    kind: str
    """Fragment turi: 'note' | 'memory_entry' | 'project' | 'task' |
    'event' | 'contact' | 'deal' | 'repo' | 'message' | 'file'."""

    content: str
    """Model-ready kanonik matn (qisqartma yoki to'liq)."""

    tokens: int = Field(ge=0)
    """Token soni (tiktoken yoki `len//4` fallback)."""

    priority: SourcePriority
    """Source-of-Truth darajasi."""

    trust: str = "system"
    """`owner` | `system` | `external` — `MemoryEntry.trust_level`ga mos.

    Default `system` — ContextEngine o'zi yig'gan fragmentlar tizim
    tomonidan tayyorlanadi. Xom `external` matn (GitHub issue, telegram)
    alohida belgilanadi."""

    origin_id: str | None = None
    """Yozuv identifikatori (note path, memory id, project uuid, ...)."""

    similarity: float = Field(default=0.0, ge=0.0, le=1.0)
    """Retriever bergan o'xshashlik balli (0..1). Manba bermasa 0."""

    retrieved_at: datetime
    """Qachon olindi (saralash uchun ham ishlatiladi)."""

    labels: tuple[str, ...] = ()
    """Belgilar: `'inferred'`, `'stale'`, `'conflict-loser'` va h.k.

    `tuple` (list emas) — chunki `frozen=True` model muhrlangan
    mutatsiyaga ruxsat bermaydi. Pydantic v2 `list` default bilan
    frozen modelda hashablikni buzadi (`unhashable type: list`)."""

    conflict_key: str | None = None
    """Bir xil fakt haqidagi fragmentlar bir xil kalitga ega. Masalan
    `contact.phone:<uuid>` — Obsidian va CRM'dagi ikkita telefon
    yozuvi bir kalitda uchrashadi va resolver yutqizganini
    `conflicts`ga yozadi."""


class SourceReport(BaseModel):
    """Bitta manbaning `discover` chaqiruvida qanday chiqqani.

    Telemetriya uchun: qaysi manba nechta fragment berdi, qancha vaqt
    ketdi, xato bo'lganmi.
    """

    model_config = ConfigDict(frozen=True)

    source: SourceKind
    ok: bool
    count: int = Field(default=0, ge=0)
    elapsed_ms: int = Field(default=0, ge=0)
    error: str | None = None


class UserRequest(BaseModel):
    """ContextEngine'ga kiruvchi so'rov.

    `frozen=True` — request yaratilgach, uni o'zgartirib bo'lmaydi
    (idempotentlik). `now` — testda vaqtni injection qilish uchun.
    """

    model_config = ConfigDict(frozen=True)

    request_id: str
    """So'rov identifikatori — telemetriya va conflicts kalitlarida."""

    owner_id: uuid.UUID
    """Ega ID. ContextEngine ham owner-scoped, lekin bu maydon
    telemetriya va auditga kerak."""

    text: str
    """Ega yozgan xom matn — qidiruv so'zlarini shu yerdan olamiz."""

    channel: str = "api"
    """`api` | `telegram` | `cli` | `voice`."""

    conversation_history: tuple[dict[str, str], ...] = ()
    """So'nggi N turlar. Har biri `{"role": "user|assistant", "content": "..."}`.

    `tuple` (list emas) — frozen model hashablikni saqlashi uchun."""

    hinted_project_id: uuid.UUID | None = None
    """Reference resolver bergan loyiha ID (2.6 bilan integratsiya)."""

    hinted_mission_id: uuid.UUID | None = None
    """Reference resolver bergan mission ID."""

    locale: str = "uz"
    """Yozuv tili — kelajakda til-spetsifik retrieval uchun."""

    now: datetime | None = None
    """Test injection uchun. `None` — `datetime.now(UTC)`."""


class RelevantContext(BaseModel):
    """`ContextEngine.discover()` chiqishi — LLM promptga tayyor kontekst.

    `fragments` — budget ichida, priority DESC/similarity DESC/recency
    DESC saralangan. `dropped` — budget'dan tashqarida qolganlar
    (debug/telemetriya). `conflicts` — jimjit qayta yozilmagan faktlar.
    """

    model_config = ConfigDict(frozen=True)

    request_id: str
    owner_id: uuid.UUID
    query: str
    fragments: tuple[ContextFragment, ...]
    dropped: tuple[ContextFragment, ...] = ()
    conflicts: tuple[dict[str, Any], ...] = ()
    reports: tuple[SourceReport, ...]
    total_tokens: int = Field(ge=0)
    budget_tokens: int = Field(ge=0)
    truncated: bool = False
    resolved_project_id: uuid.UUID | None = None
    generated_at: datetime

    # ── Yordamchi metodlar ───────────────────────────────────────

    def by_source(self, source: SourceKind) -> list[ContextFragment]:
        """Faqat tanlangan manbadan kelgan fragmentlar."""
        return [f for f in self.fragments if f.source is source]

    def as_prompt_block(self, *, sections: bool = True) -> str:
        """LLM promptga qo'shish uchun matn.

        `sections=True` — har bir manba uchun `## MEMORY` kabi markdown
        sarlavha; `False` — chiziqli fragmentlar. Fragmentlar `discover`
        saralashida turadi (yuqori priority birinchi).
        """
        if not self.fragments:
            return ""

        if not sections:
            return "\n\n".join(f.content for f in self.fragments)

        parts: list[str] = []
        current_source: SourceKind | None = None
        for frag in self.fragments:
            if frag.source is not current_source:
                current_source = frag.source
                parts.append(f"## {frag.source.value.upper()}")
            parts.append(frag.content)
        return "\n\n".join(parts)


# ── Bog'liq komponentlar uchun protokollar ─────────────────────────


@runtime_checkable
class MemoryStoreLike(Protocol):
    """`PgMemoryStore.search()` uchun minimal shakl."""

    async def search(
        self,
        query: MemoryQuery,
        *,
        now: datetime | None = ...,
    ) -> list[MemorySearchResult]: ...


@runtime_checkable
class WorkspaceRepositoryLike(Protocol):
    """`WorkspaceRepository`ning discover uchun kerakli qismi."""

    async def list_projects(self, *, status: Any = ..., limit: int = ...) -> Sequence[Any]: ...

    async def get_project(self, project_id: uuid.UUID) -> Any: ...

    async def list_tasks(
        self,
        *,
        status: Any = ...,
        project_id: uuid.UUID | None = ...,
        limit: int = ...,
    ) -> Sequence[Any]: ...

    async def list_events(
        self,
        *,
        start: datetime | None = ...,
        end: datetime | None = ...,
        limit: int = ...,
    ) -> Sequence[Any]: ...


@runtime_checkable
class CRMLike(Protocol):
    """`PgCRM`ning discover uchun kerakli qismi."""

    async def find_contacts(self, query: str) -> list[Any]: ...

    async def list_deals(self, stage: Any = ...) -> list[Any]: ...


@runtime_checkable
class NoteListToolLike(Protocol):
    """`NoteListTool.execute` shakli."""

    async def execute(self, params: dict[str, Any], *, dry_run: bool = ...) -> Any: ...


@runtime_checkable
class NoteReadToolLike(Protocol):
    """`NoteReadTool.execute` shakli."""

    async def execute(self, params: dict[str, Any], *, dry_run: bool = ...) -> Any: ...


@runtime_checkable
class GitHubToolLike(Protocol):
    """`GitHubReadTool.execute` shakli.

    Fail-open uchun `is_real` bayrog'i o'qiladi — token yo'q bo'lsa
    stub emas, umuman chaqirilmaydi (stub natijasi kontekstga zarar
    qiladi)."""

    @property
    def is_real(self) -> bool: ...

    async def execute(self, params: dict[str, Any], *, dry_run: bool = ...) -> Any: ...


@runtime_checkable
class TelegramClientLike(Protocol):
    """Telegram adapter — `recent_messages` bilan cheklangan interfeys.

    Master Spec §2.3: telegram ham manbalar ro'yxatida. Hozircha
    optional — client bo'lmasa manba `ok=True, count=0` bilan
    o'tkazib yuboriladi."""

    async def recent_messages(
        self, *, chat_id: int | str, limit: int = ...
    ) -> list[dict[str, Any]]: ...


@runtime_checkable
class CalendarProviderLike(Protocol):
    """Kalendar adapter — `WorkspaceRepository.list_events` ni to'ldiruvchi
    (masalan Google Calendar). Optional."""

    async def upcoming_events(
        self, *, start: datetime, end: datetime, limit: int = ...
    ) -> list[dict[str, Any]]: ...


# ── Token hisoblagich (tiktoken fallback) ─────────────────────────


_tiktoken_encoder: Any = None
_tiktoken_probed = False
_tiktoken_warned = False


def _get_tiktoken_encoder() -> Any:
    """`tiktoken` mavjud bo'lsa `cl100k_base` encoder qaytaradi.

    Bir marta probelanadi (`_tiktoken_probed`), keyingi chaqiruvlar
    kesh natijasidan foydalanadi. `filterwarnings = ["error"]`ni
    buzmaslik uchun `logging.warning` (Python warnings emas) chiqadi.
    """
    global _tiktoken_encoder, _tiktoken_probed, _tiktoken_warned
    if _tiktoken_probed:
        return _tiktoken_encoder

    _tiktoken_probed = True
    try:
        import tiktoken  # type: ignore[import-not-found]

        _tiktoken_encoder = tiktoken.get_encoding("cl100k_base")
    except Exception:
        if not _tiktoken_warned:
            log.warning("context.tiktoken_unavailable", fallback="len//4")
            _tiktoken_warned = True
        _tiktoken_encoder = None
    return _tiktoken_encoder


def _reset_tiktoken_probe_for_tests() -> None:
    """Test helper — tiktoken probe holatini tozalash."""
    global _tiktoken_encoder, _tiktoken_probed, _tiktoken_warned
    _tiktoken_encoder = None
    _tiktoken_probed = False
    _tiktoken_warned = False


# ── ContextEngine ─────────────────────────────────────────────────


_WORD_RE = re.compile(r"[\w']+", re.UNICODE)


def _keywords(text: str, *, min_len: int = 3, max_words: int = 12) -> list[str]:
    """Xom matndan qidiruv so'zlari (past registr, `min_len`dan uzunlari)."""
    words = _WORD_RE.findall(text.lower())
    seen: dict[str, None] = {}
    for w in words:
        if len(w) >= min_len and w not in seen:
            seen[w] = None
        if len(seen) >= max_words:
            break
    return list(seen)


def _normalize_content_key(content: str) -> str:
    """Content'ni conflict_key uchun kanonizatsiya qiladi.

    Regexp orqali telefon/email kabi identifikatorlarni maxsus ishlaymiz:
    `+998-90-123-45-67` va `+998 90 1234567` bir xil kalitga tushadi.
    Aks holda bosh harflar/oraliqlar konflikt aniqlashni buzardi.
    """
    lowered = content.lower().strip()
    # Faqat harf, raqam va `+@.` — qolgan hammasi tashlab yuboriladi
    return re.sub(r"[^0-9a-z@.+]", "", lowered)


class ContextEngine:
    """8 manba bo'ylab nishonli retrieval — `RelevantContext` qaytaradi.

    Master Spec PART 4 invariantlari:
        1. "targeted retrieval, never a full dump"
           → har manba `max_fragments_per_source` chegarasida
        2. "never silently overwrite conflicting facts"
           → `_resolve_conflicts` yutqizganlarni `conflicts`ga yozadi
        3. "fail-open"
           → bitta manba yiqilsa `SourceReport.ok=False`, qolgan manbalar
             normal ishlaydi; butun `discover()` hech qachon yiqilmaydi
        4. "parallel"
           → barcha `_query_*` `asyncio.gather` bilan bir vaqtda ishga
             tushiriladi (sekvensial 9x sekinroq bo'lardi)
    """

    def __init__(
        self,
        *,
        owner_id: uuid.UUID,
        memory_store: MemoryStoreLike | None = None,
        workspace_repo: WorkspaceRepositoryLike | None = None,
        crm: CRMLike | None = None,
        notes_dir: Path | None = None,
        note_list: NoteListToolLike | None = None,
        note_read: NoteReadToolLike | None = None,
        github_tool: GitHubToolLike | None = None,
        telegram_client: TelegramClientLike | None = None,
        telegram_chat_id: int | str | None = None,
        calendar_provider: CalendarProviderLike | None = None,
        budget_tokens: int = MAX_CONTEXT_TOKENS,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        logger: structlog.BoundLogger | None = None,
    ) -> None:
        self._owner_id = owner_id
        self._memory = memory_store
        self._workspace = workspace_repo
        self._crm = crm
        self._notes_dir = notes_dir
        self._note_list = note_list
        self._note_read = note_read
        self._github = github_tool
        self._telegram = telegram_client
        self._telegram_chat_id = telegram_chat_id
        self._calendar = calendar_provider
        self._budget_tokens = max(0, int(budget_tokens))
        self._clock = clock
        self._log = logger or log

    # ── Ochiq API ────────────────────────────────────────────────

    async def discover(
        self,
        request: UserRequest,
        *,
        max_fragments_per_source: int = DEFAULT_MAX_FRAGMENTS_PER_SOURCE,
        source_timeout_s: float = DEFAULT_SOURCE_TIMEOUT_S,
    ) -> RelevantContext:
        """Bitta request uchun kontekst topadi va yig'ib qaytaradi.

        Args:
            request: xom foydalanuvchi so'rovi.
            max_fragments_per_source: bitta manbadan olinadigan max
                fragment (Master Spec "no full dump").
            source_timeout_s: bitta manba uchun kutish. Undan uzoq
                javob berilsa fail-open (bo'sh natija + xato reporti).

        Returns:
            `RelevantContext` — fragmentlar priority DESC saralangan,
            budget ichida; konfliktlar va per-source telemetriya bilan.
        """
        text_hash = hashlib.sha256(request.text.encode("utf-8")).hexdigest()[:12]
        self._log.info(
            "context.discover.start",
            request_id=request.request_id,
            owner_id=str(request.owner_id),
            text_hash=text_hash,
        )

        # 1. Barcha manbalarni parallel ishga tushiramiz.
        queries: list[tuple[SourceKind, Awaitable[list[ContextFragment]]]] = [
            (SourceKind.MEMORY, self._query_memory(request, limit=max_fragments_per_source)),
            (SourceKind.OBSIDIAN, self._query_obsidian(request, limit=max_fragments_per_source)),
            (SourceKind.WORKSPACE, self._query_workspace(request, limit=max_fragments_per_source)),
            (SourceKind.CRM, self._query_crm(request, limit=max_fragments_per_source)),
            (SourceKind.GITHUB, self._query_github(request, limit=max_fragments_per_source)),
            (SourceKind.TELEGRAM, self._query_telegram(request, limit=max_fragments_per_source)),
            (SourceKind.CALENDAR, self._query_calendar(request, limit=max_fragments_per_source)),
            (SourceKind.FILES, self._query_files(request, limit=max_fragments_per_source)),
            (
                SourceKind.CONVERSATION,
                self._query_conversation(request, limit=max_fragments_per_source),
            ),
        ]

        reports: list[SourceReport] = []
        all_fragments: list[ContextFragment] = []

        # `asyncio.gather` uchun har birini timeout bilan o'raymiz
        async def _run_one(
            kind: SourceKind, coro: Awaitable[list[ContextFragment]]
        ) -> tuple[SourceKind, list[ContextFragment], int, str | None]:
            start = self._clock()
            try:
                fragments = await asyncio.wait_for(coro, timeout=source_timeout_s)
                elapsed_ms = _elapsed_ms(start, self._clock())
                return kind, fragments, elapsed_ms, None
            except TimeoutError:
                elapsed_ms = _elapsed_ms(start, self._clock())
                return kind, [], elapsed_ms, f"timeout after {source_timeout_s}s"
            except Exception as exc:
                elapsed_ms = _elapsed_ms(start, self._clock())
                return kind, [], elapsed_ms, f"{type(exc).__name__}: {exc}"

        results = await asyncio.gather(
            *[_run_one(kind, coro) for kind, coro in queries],
            return_exceptions=False,  # _run_one o'zi barcha exception'larni yutadi
        )

        for kind, fragments, elapsed_ms, error in results:
            ok = error is None
            report = SourceReport(
                source=kind, ok=ok, count=len(fragments), elapsed_ms=elapsed_ms, error=error
            )
            reports.append(report)
            self._log.info(
                "context.source.completed",
                source=kind.value,
                ok=ok,
                count=len(fragments),
                elapsed_ms=elapsed_ms,
                error=error,
            )
            all_fragments.extend(fragments)

        # 2. Konflikt aniqlash va yutqizganlarni ajratish.
        resolved, conflicts, conflict_losers = self._resolve_conflicts(all_fragments)

        # 3. Saralash: (priority DESC, similarity DESC, retrieved_at DESC).
        resolved.sort(
            key=lambda f: (int(f.priority), f.similarity, f.retrieved_at),
            reverse=True,
        )

        # 4. Budget ichida greedy to'ldirish.
        kept, dropped_budget = self._apply_budget(resolved, self._budget_tokens)

        dropped = tuple(dropped_budget) + tuple(conflict_losers)
        total_tokens = sum(f.tokens for f in kept)
        truncated = len(dropped_budget) > 0

        resolved_project_id = request.hinted_project_id

        context = RelevantContext(
            request_id=request.request_id,
            owner_id=request.owner_id,
            query=request.text,
            fragments=tuple(kept),
            dropped=dropped,
            conflicts=tuple(conflicts),
            reports=tuple(reports),
            total_tokens=total_tokens,
            budget_tokens=self._budget_tokens,
            truncated=truncated,
            resolved_project_id=resolved_project_id,
            generated_at=self._clock(),
        )

        self._log.info(
            "context.discovered",
            request_id=request.request_id,
            total_fragments=len(kept),
            dropped=len(dropped),
            conflicts=len(conflicts),
            total_tokens=total_tokens,
            budget_tokens=self._budget_tokens,
            truncated=truncated,
        )
        return context

    # ── Manba-spetsifik yordamchilar ─────────────────────────────

    async def _query_memory(self, request: UserRequest, *, limit: int) -> list[ContextFragment]:
        """PgMemoryStore.search — gibrid (kalit + vektor) qidiruv.

        Layers: PROJECT/BUSINESS/PERSONAL/KNOWLEDGE/TASK/CONVERSATION —
        SHORT_TERM chiqarilgan (u faqat joriy run ichida yashaydi).
        """
        if self._memory is None:
            return []

        query = MemoryQuery(
            text=request.text or " ",
            layers=[
                MemoryLayer.PROJECT,
                MemoryLayer.BUSINESS,
                MemoryLayer.PERSONAL,
                MemoryLayer.KNOWLEDGE,
                MemoryLayer.TASK,
                MemoryLayer.CONVERSATION,
            ],
            limit=limit,
            min_similarity=0.0,  # rerank + budget o'zi tanlaydi
        )
        results = await self._memory.search(query)
        now = request.now or self._clock()

        fragments: list[ContextFragment] = []
        for res in results:
            entry = res.entry
            priority = self._priority_for_memory(entry, now=now)
            content = self._memory_content(entry)
            fragments.append(
                ContextFragment(
                    source=SourceKind.MEMORY,
                    kind="memory_entry",
                    content=content,
                    tokens=self._count_tokens(content),
                    priority=priority,
                    trust=entry.trust_level or "system",
                    origin_id=entry.id,
                    similarity=res.similarity,
                    retrieved_at=now,
                    conflict_key=self._conflict_key_for_entry(entry),
                )
            )
        return fragments

    async def _query_obsidian(self, request: UserRequest, *, limit: int) -> list[ContextFragment]:
        """NoteListTool + top-N NoteReadTool.

        Master Spec "no full dump" — biz vault'dagi 500 notani ham
        emas, faqat `limit` (default 8) donasini o'qiymiz. `note.read`
        `limit` marta chaqiriladi, ko'proq emas.
        """
        if self._note_list is None:
            return []

        list_result = await self._note_list.execute({"query": request.text or "", "limit": limit})
        notes = _tool_output(list_result).get("notes", []) or []
        now = request.now or self._clock()

        # Fayl nomi ishoralari ham asos bo'la oladi — barcha topilganlarni
        # limitga qadar o'qiymiz.
        read_targets = notes[:limit]

        fragments: list[ContextFragment] = []
        for note in read_targets:
            title_or_path = note.get("title") or note.get("path")
            if not title_or_path:
                continue
            content = ""
            origin_id = note.get("path") or note.get("title") or None
            if self._note_read is not None:
                with contextlib.suppress(Exception):
                    read_result = await self._note_read.execute(
                        {"title": note.get("title") or title_or_path}
                    )
                    body = _tool_output(read_result)
                    content = _render_note(body)
                    origin_id = body.get("path", origin_id)
            if not content:
                content = f"# {note.get('title', title_or_path)}"

            fragments.append(
                ContextFragment(
                    source=SourceKind.OBSIDIAN,
                    kind="note",
                    content=content,
                    tokens=self._count_tokens(content),
                    priority=SourcePriority.AUTHORITATIVE_SOURCE,
                    trust="owner",
                    origin_id=str(origin_id) if origin_id else None,
                    retrieved_at=now,
                    conflict_key=_conflict_key_from_content("note", content),
                )
            )
        return fragments

    async def _query_workspace(self, request: UserRequest, *, limit: int) -> list[ContextFragment]:
        """Loyihalar + faol vazifalar (hinted_project_id bilan).

        `hinted_project_id` berilgan bo'lsa faqat shu loyiha va uning
        vazifalari; aks holda ega'ning barcha faol loyihalari + kalit-so'z
        bo'yicha mos vazifalar.
        """
        if self._workspace is None:
            return []

        now = request.now or self._clock()
        fragments: list[ContextFragment] = []
        keywords = set(_keywords(request.text))
        hinted = request.hinted_project_id

        projects: list[Any] = []
        if hinted is not None:
            with contextlib.suppress(Exception):
                project = await self._workspace.get_project(hinted)
                projects.append(project)
        else:
            listed = await self._workspace.list_projects(limit=limit)
            projects.extend(list(listed))

        for project in projects[:limit]:
            is_current = hinted is not None and getattr(project, "id", None) == hinted
            priority = (
                SourcePriority.CURRENT_PROJECT
                if is_current
                else SourcePriority.AUTHORITATIVE_SOURCE
            )
            content = _render_project(project)
            if not is_current and not _matches_keywords(content, keywords):
                # Loyiha ega'ning katta ro'yxatidan — mavzuga bog'liq emas
                continue
            pid = getattr(project, "id", None)
            fragments.append(
                ContextFragment(
                    source=SourceKind.WORKSPACE,
                    kind="project",
                    content=content,
                    tokens=self._count_tokens(content),
                    priority=priority,
                    trust="owner",
                    origin_id=str(pid) if pid else None,
                    retrieved_at=now,
                    conflict_key=(f"project:{pid}" if pid else None),
                )
            )

        # Vazifalar — faqat hinted_project_id bo'lsa (aks holda shovqin)
        if hinted is not None:
            with contextlib.suppress(Exception):
                tasks = await self._workspace.list_tasks(project_id=hinted, limit=limit)
                for task in list(tasks)[:limit]:
                    content = _render_task(task)
                    tid = getattr(task, "id", None)
                    fragments.append(
                        ContextFragment(
                            source=SourceKind.WORKSPACE,
                            kind="task",
                            content=content,
                            tokens=self._count_tokens(content),
                            priority=SourcePriority.CURRENT_PROJECT,
                            trust="owner",
                            origin_id=str(tid) if tid else None,
                            retrieved_at=now,
                            conflict_key=(f"task:{tid}" if tid else None),
                        )
                    )

        return fragments

    async def _query_crm(self, request: UserRequest, *, limit: int) -> list[ContextFragment]:
        """Kontakt + faol deal'lar (LIKE + faol stage)."""
        if self._crm is None:
            return []

        now = request.now or self._clock()
        fragments: list[ContextFragment] = []

        with contextlib.suppress(Exception):
            contacts = await self._crm.find_contacts(request.text or "")
            for contact in list(contacts)[:limit]:
                content = _render_contact(contact)
                cid = getattr(contact, "id", None)
                fragments.append(
                    ContextFragment(
                        source=SourceKind.CRM,
                        kind="contact",
                        content=content,
                        tokens=self._count_tokens(content),
                        priority=SourcePriority.AUTHORITATIVE_SOURCE,
                        trust="owner",
                        origin_id=str(cid) if cid else None,
                        retrieved_at=now,
                        conflict_key=_contact_conflict_key(contact),
                    )
                )

        with contextlib.suppress(Exception):
            deals = await self._crm.list_deals()
            for deal in list(deals)[:limit]:
                content = _render_deal(deal)
                did = getattr(deal, "id", None)
                fragments.append(
                    ContextFragment(
                        source=SourceKind.CRM,
                        kind="deal",
                        content=content,
                        tokens=self._count_tokens(content),
                        priority=SourcePriority.AUTHORITATIVE_SOURCE,
                        trust="owner",
                        origin_id=str(did) if did else None,
                        retrieved_at=now,
                        conflict_key=(f"deal:{did}" if did else None),
                    )
                )

        return fragments

    async def _query_github(self, request: UserRequest, *, limit: int) -> list[ContextFragment]:
        """GitHub repo README — faqat matnda "github.com/x/y" ishorasi bo'lsa.

        Token berilmagan bo'lsa (`is_real=False`) — umuman chaqirmaymiz:
        stub javob kontekstga zarar qiladi (soxta REAMDE matni yolg'on
        "faktlar" olib keladi)."""
        if self._github is None:
            return []
        if not getattr(self._github, "is_real", False):
            return []

        repo = _extract_repo(request.text)
        if repo is None:
            return []

        now = request.now or self._clock()
        result = await self._github.execute(
            {"action": "get_file", "repo": repo, "path": "README.md"}
        )
        output = _tool_output(result)
        content = output.get("content", "") or ""
        if not content:
            return []
        # Master Spec "no full dump" — README qisqartiladi
        content = content[:4000]
        return [
            ContextFragment(
                source=SourceKind.GITHUB,
                kind="repo",
                content=f"# github:{repo}\n{content}",
                tokens=self._count_tokens(content),
                priority=SourcePriority.AUTHORITATIVE_SOURCE,
                trust="external",  # tashqi kod muallifi yozgan (A-05)
                origin_id=repo,
                retrieved_at=now,
                conflict_key=f"repo:{repo}",
            )
        ][:limit]

    async def _query_telegram(self, request: UserRequest, *, limit: int) -> list[ContextFragment]:
        """So'nggi telegram xabarlari — kalit-so'z filtri bilan."""
        if self._telegram is None or self._telegram_chat_id is None:
            return []

        now = request.now or self._clock()
        messages = await self._telegram.recent_messages(chat_id=self._telegram_chat_id, limit=20)
        keywords = set(_keywords(request.text))

        fragments: list[ContextFragment] = []
        for msg in messages:
            text = str(msg.get("text", ""))
            if not text:
                continue
            if keywords and not _matches_keywords(text, keywords):
                continue
            msg_id = msg.get("id")
            fragments.append(
                ContextFragment(
                    source=SourceKind.TELEGRAM,
                    kind="message",
                    content=text,
                    tokens=self._count_tokens(text),
                    priority=SourcePriority.RECENT_MEMORY,
                    trust="external",
                    origin_id=str(msg_id) if msg_id is not None else None,
                    retrieved_at=now,
                )
            )
            if len(fragments) >= limit:
                break
        return fragments

    async def _query_calendar(self, request: UserRequest, *, limit: int) -> list[ContextFragment]:
        """Kelgusi 7 kun ichidagi hodisalar (workspace_repo.list_events)."""
        if self._workspace is None:
            return []

        now = request.now or self._clock()
        events = await self._workspace.list_events(
            start=now, end=now + timedelta(days=7), limit=limit
        )
        fragments: list[ContextFragment] = []
        for event in list(events)[:limit]:
            content = _render_event(event)
            eid = getattr(event, "id", None)
            fragments.append(
                ContextFragment(
                    source=SourceKind.CALENDAR,
                    kind="event",
                    content=content,
                    tokens=self._count_tokens(content),
                    priority=SourcePriority.AUTHORITATIVE_SOURCE,
                    trust="owner",
                    origin_id=str(eid) if eid else None,
                    retrieved_at=now,
                    conflict_key=(f"event:{eid}" if eid else None),
                )
            )
        return fragments

    async def _query_files(self, request: UserRequest, *, limit: int) -> list[ContextFragment]:
        """`notes_dir` ichidagi fayllar — FAQAT nomga qarab.

        Tarkib O'QILMAYDI (arzon skan). Bu — biror faylning MAVJUDLIGINI
        eslatib qo'yish uchun; tarkib kerak bo'lsa `_query_obsidian`
        allaqachon `.md` ni to'liq o'qigan.
        """
        if self._notes_dir is None:
            return []

        keywords = set(_keywords(request.text))
        now = request.now or self._clock()
        fragments: list[ContextFragment] = []

        try:
            for path in _iter_all_files(self._notes_dir):
                name = path.name
                if keywords and not _matches_keywords(name, keywords):
                    continue
                content = f"[file] {path.relative_to(self._notes_dir)}"
                fragments.append(
                    ContextFragment(
                        source=SourceKind.FILES,
                        kind="file",
                        content=content,
                        tokens=self._count_tokens(content),
                        priority=SourcePriority.AUTHORITATIVE_SOURCE,
                        trust="owner",
                        origin_id=str(path),
                        retrieved_at=now,
                    )
                )
                if len(fragments) >= limit:
                    break
        except OSError:
            return []

        return fragments

    async def _query_conversation(
        self, request: UserRequest, *, limit: int
    ) -> list[ContextFragment]:
        """`conversation_history[-limit:]` → fragmentlar.

        Oxirgi USER turi — `USER_INSTRUCTION` (eng yuqori priority);
        qolganlari `RECENT_MEMORY`. Master Spec: "current instruction
        overrides everything" — foydalanuvchi hozir aytgani har qanday
        eski yozuvdan ustunroq.
        """
        history = list(request.conversation_history)
        if not history:
            return []

        now = request.now or self._clock()
        recent = history[-limit:]
        fragments: list[ContextFragment] = []

        # Oxirgi USER turini topamiz (list oxiridan boshlab qidiramiz)
        last_user_idx = -1
        for i in range(len(recent) - 1, -1, -1):
            if recent[i].get("role") == "user":
                last_user_idx = i
                break

        for i, turn in enumerate(recent):
            role = turn.get("role", "user")
            content = str(turn.get("content", ""))
            if not content:
                continue
            is_last_user = i == last_user_idx and role == "user"
            priority = (
                SourcePriority.USER_INSTRUCTION if is_last_user else SourcePriority.RECENT_MEMORY
            )
            fragments.append(
                ContextFragment(
                    source=SourceKind.CONVERSATION,
                    kind="message",
                    content=f"[{role}] {content}",
                    tokens=self._count_tokens(content),
                    priority=priority,
                    trust="owner" if role == "user" else "system",
                    origin_id=f"conv:{i}",
                    retrieved_at=now,
                    conflict_key=_conflict_key_from_content("conversation", content)
                    if is_last_user
                    else None,
                )
            )
        return fragments

    # ── Yordamchi: konflikt va budget ────────────────────────────

    def _resolve_conflicts(
        self, fragments: list[ContextFragment]
    ) -> tuple[list[ContextFragment], list[dict[str, Any]], list[ContextFragment]]:
        """Bir xil `conflict_key` bo'lgan fragmentlar orasidan yagona
        g'olibni tanlaydi.

        Returns:
            winners — g'oliblar + `conflict_key=None` bo'lganlar
            conflict_rows — [{key, winner, losers}] plain dict ro'yxati
            losers — yutqizgan fragmentlar (labels='conflict-loser' bilan);
                chaqiruvchi ularni `dropped`ga qo'shadi.

        NEGA hech qachon jimjit qayta yozmaydi. Master Spec PART 4:
        "conflicting facts must be surfaced" — foydalanuvchi keyingi
        so'rovda "aslida qaysi biri to'g'ri?" deb so'rashi mumkin. Agar
        yutqizganlarni jim tashlab yuborsak, yozuvlar rekonsiliatsiyasi
        (§2.5) sinadi.
        """
        groups: dict[str, list[ContextFragment]] = {}
        no_key: list[ContextFragment] = []

        for frag in fragments:
            if frag.conflict_key is None:
                no_key.append(frag)
                continue
            groups.setdefault(frag.conflict_key, []).append(frag)

        winners: list[ContextFragment] = list(no_key)
        conflict_rows: list[dict[str, Any]] = []
        losers_out: list[ContextFragment] = []

        for key, group in groups.items():
            if len(group) == 1:
                winners.append(group[0])
                continue

            # Bir xil kalit ostida bir nechta variant — resolver
            group_sorted = sorted(
                group,
                key=lambda f: (int(f.priority), f.retrieved_at),
                reverse=True,
            )
            winner = group_sorted[0]
            losers = group_sorted[1:]

            winners.append(winner)
            conflict_rows.append(
                {
                    "key": key,
                    "winner": {
                        "id": winner.origin_id,
                        "source": winner.source.value,
                        "priority": int(winner.priority),
                    },
                    "losers": [
                        {
                            "id": loser.origin_id,
                            "source": loser.source.value,
                            "priority": int(loser.priority),
                            "reason": "lower_priority"
                            if int(loser.priority) < int(winner.priority)
                            else "older",
                        }
                        for loser in losers
                    ],
                }
            )
            for loser in losers:
                losers_out.append(
                    loser.model_copy(update={"labels": (*loser.labels, "conflict-loser")})
                )
        return winners, conflict_rows, losers_out

    def _apply_budget(
        self, fragments: list[ContextFragment], budget: int
    ) -> tuple[list[ContextFragment], list[ContextFragment]]:
        """Greedy — priority tartibida budget'ga sig'guncha to'ldiradi.

        `fragments` allaqachon saralangan (yuqori priority birinchi) deb
        taxmin qilinadi. Bitta fragment tokens > budget bo'lsa —
        umuman qo'shilmaydi (bo'lakni bo'lish yolg'on kontekst yaratardi).
        """
        kept: list[ContextFragment] = []
        dropped: list[ContextFragment] = []
        used = 0
        for frag in fragments:
            if used + frag.tokens <= budget:
                kept.append(frag)
                used += frag.tokens
            else:
                dropped.append(frag)
        return kept, dropped

    # ── Yordamchi: token va priority ─────────────────────────────

    def _count_tokens(self, text: str) -> int:
        """`tiktoken` (`cl100k_base`) mavjud bo'lsa aniq son; aks holda
        `len(text) // 4` heuristikasi (GPT-4 tokenlashuvining o'rtacha
        koeffitsienti). Fallback ham budgetni sindirmaydi — quyi/yuqori
        farq kichik, greedy resolver o'zi jarayonni bosadi."""
        if not text:
            return 0
        encoder = _get_tiktoken_encoder()
        if encoder is not None:
            try:
                return len(encoder.encode(text))
            except Exception as exc:
                log.warning("context.tiktoken_encode_failed", error=str(exc))
        return max(1, len(text) // 4)

    def _priority_for_memory(self, entry: Any, *, now: datetime) -> SourcePriority:
        """Memory qatlamiga qarab priority.

        PROJECT/BUSINESS/PERSONAL → AUTHORITATIVE_SOURCE (biznes bilim).
        TASK/CONVERSATION (<=7d) → RECENT_MEMORY.
        Boshqasi → OLDER_MEMORY.
        """
        layer = getattr(entry, "layer", None)
        if layer in {MemoryLayer.PROJECT, MemoryLayer.BUSINESS, MemoryLayer.PERSONAL}:
            return SourcePriority.AUTHORITATIVE_SOURCE
        if layer in {MemoryLayer.TASK, MemoryLayer.CONVERSATION}:
            created = getattr(entry, "created_at", None)
            if created is not None and (now - created) <= timedelta(days=7):
                return SourcePriority.RECENT_MEMORY
            return SourcePriority.OLDER_MEMORY
        if layer is MemoryLayer.KNOWLEDGE:
            return SourcePriority.OLDER_MEMORY
        return SourcePriority.OLDER_MEMORY

    def _memory_content(self, entry: Any) -> str:
        """Fragment matni — `summary` bo'lsa uni, aks holda `content`."""
        summary = getattr(entry, "summary", None)
        if summary:
            return str(summary)
        return str(getattr(entry, "content", "") or "")

    def _conflict_key_for_entry(self, entry: Any) -> str | None:
        """Memory yozuvi uchun konflikt kaliti.

        `phone`/`email` tegi yoki content'da mos so'z bo'lsa — obsidian/
        conversation bilan bir xil (`contact.phone:me` / `contact.email:me`)
        kalit chiqadi va resolver ularni bir guruhga yig'adi.
        """
        tags: list[str] = list(getattr(entry, "tags", None) or [])
        content = str(getattr(entry, "content", "") or "")
        if "phone" in tags:
            return "contact.phone:me"
        if "email" in tags:
            return "contact.email:me"
        return _conflict_key_from_content("memory", content)


# ── Modul-darajali yordamchilar ────────────────────────────────────


def _elapsed_ms(start: datetime, end: datetime) -> int:
    """Ikki `datetime` orasidagi millisekund (manfiy bo'lsa 0)."""
    delta = (end - start).total_seconds() * 1000
    return max(0, int(delta))


def _tool_output(result: Any) -> dict[str, Any]:
    """`Tool.execute` `ToolResult` yoki dict qaytarishi mumkin — normallashtiradi."""
    if isinstance(result, dict):
        return result
    output = getattr(result, "output", None)
    if isinstance(output, dict):
        return output
    return {}


def _matches_keywords(text: str, keywords: set[str]) -> bool:
    """Matnda kalit-so'zlarning kamida bittasi uchraydimi (past registrda)."""
    if not keywords:
        return True
    lowered = text.lower()
    return any(k in lowered for k in keywords)


def _render_project(project: Any) -> str:
    name = getattr(project, "name", "?")
    status = getattr(project, "status", "")
    status_str = getattr(status, "value", status) if status else ""
    desc = getattr(project, "description", "") or ""
    return f"[project:{name}] status={status_str}\n{desc}".strip()


def _render_task(task: Any) -> str:
    title = getattr(task, "title", "?")
    status = getattr(task, "status", "")
    status_str = getattr(status, "value", status) if status else ""
    desc = getattr(task, "description", "") or ""
    return f"[task:{title}] status={status_str}\n{desc}".strip()


def _render_contact(contact: Any) -> str:
    name = getattr(contact, "name", "?")
    company = getattr(contact, "company", "") or ""
    phone = getattr(contact, "phone", "") or ""
    email = getattr(contact, "email", "") or ""
    parts = [f"[contact:{name}]"]
    if company:
        parts.append(f"company={company}")
    if phone:
        parts.append(f"phone={phone}")
    if email:
        parts.append(f"email={email}")
    return " ".join(parts)


def _render_deal(deal: Any) -> str:
    title = getattr(deal, "title", "?")
    stage = getattr(deal, "stage", "")
    stage_str = getattr(stage, "value", stage) if stage else ""
    amount = getattr(deal, "amount", 0)
    return f"[deal:{title}] stage={stage_str} amount={amount}"


def _render_event(event: Any) -> str:
    title = getattr(event, "title", "?")
    starts_at = getattr(event, "starts_at", "")
    location = getattr(event, "location", "") or ""
    return f"[event:{title}] at={starts_at} loc={location}".strip()


def _render_note(body: dict[str, Any]) -> str:
    """Note read output → LLM-uchun kanonik matn (title + frontmatter + body)."""
    title = body.get("title", "")
    frontmatter = body.get("frontmatter") or {}
    content = body.get("content", "") or ""
    fm_lines = "\n".join(f"{k}: {v}" for k, v in frontmatter.items())
    parts = [f"# {title}"] if title else []
    if fm_lines:
        parts.append(fm_lines)
    if content:
        parts.append(content.strip())
    return "\n".join(parts)


def _iter_all_files(root: Path):
    """Yashirin bo'lmagan barcha fayllarni yig'adi (files manba uchun)."""
    if not root.exists():
        return
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        yield path


def _extract_repo(text: str) -> str | None:
    """Matnda `github.com/owner/name` yoki `owner/name` (bo'shliqda) ni topadi."""
    match = re.search(r"github\.com/([\w.-]+/[\w.-]+)", text)
    if match:
        return match.group(1).rstrip(".git")
    match = re.search(r"(?:^|\s)([\w-]+/[\w.-]+)(?=\s|$)", text)
    if match:
        candidate = match.group(1)
        # Faylga o'xshamasin (`a.md/b` emas)
        if "." not in candidate.split("/", 1)[0]:
            return candidate
    return None


def _contact_conflict_key(contact: Any) -> str | None:
    """Kontakt uchun konflikt kaliti.

    Ega'ning o'z profili (kontakt nomi `owner`/`self`/`me`) telefon fakti
    obsidian/xotira bilan uchrashishi uchun umumiy `contact.phone:me`
    kaliti chiqariladi. Boshqa kontakt uchun kalit shu kontakt ID'siga
    bog'lanadi — turli mijozlarning telefonlari o'zaro konflikt qilmaydi.
    """
    name = str(getattr(contact, "name", "") or "").strip().lower()
    is_owner = name in {"owner", "self", "me", "ega", "mening"}
    phone = getattr(contact, "phone", "") or ""
    email = getattr(contact, "email", "") or ""

    if is_owner:
        if phone:
            return "contact.phone:me"
        if email:
            return "contact.email:me"
        return None

    cid = getattr(contact, "id", None)
    if phone and cid is not None:
        return f"contact.phone:{cid}"
    if email and cid is not None:
        return f"contact.email:{cid}"
    return None


def _conflict_key_from_content(kind: str, content: str) -> str | None:  # noqa: ARG001 — `kind` chaqiruvchining o'z niyati uchun; kelajakda `text` va boshqa turdagi kalitlar uchun ajratilgan
    """Ochiq matnda telefon/email ko'ringan bo'lsa — FAKT KATEGORIYASI
    bo'yicha konflikt kaliti (qiymatga bog'liq emas).

    Master Spec: "same fact, different sources" — biz `contact.phone:me`
    kabi kalit qo'yamiz, chunki bir xil fakt haqidagi ikki yozuv har xil
    QIYMATga ega bo'lishi mumkin (aynan shu — konflikt bo'ladi). Kalit
    qiymatni o'ziga qo'shmasin, aks holda konflikt hech qachon
    aniqlanmasdi (har xil qiymat = har xil kalit = konflikt yo'q).

    "my phone" / "mening telefon" iboralari yoki `phone:` tegi
    ko'rilganda `contact.phone:me` beriladi — bu ega o'zining telefon
    fakti degani. Ega'ning shaxsiy telefonlari kontekst bo'ylab uchrasa,
    resolver eng ustunini tanlaydi. Boshqa odamning telefoni ega'ga
    tegishli emas — ular alohida `contact_id` orqali kalitlanadi.
    """
    lowered = content.lower()
    is_owner_phone = bool(
        re.search(r"\bmy phone\b|mening\s+telefon|phone:", lowered)
        or re.search(r"\+?\d[\d\s\-()]{7,}\d", content)
    ) and (
        "my phone" in lowered or "mening" in lowered or "phone:" in lowered or "telefon" in lowered
    )
    if is_owner_phone:
        return "contact.phone:me"

    if re.search(r"\bmy email\b|mening\s+email|email:", lowered):
        return "contact.email:me"

    return None


__all__ = [
    "DEFAULT_MAX_FRAGMENTS_PER_SOURCE",
    "DEFAULT_SOURCE_TIMEOUT_S",
    "MAX_CONTEXT_TOKENS",
    "CRMLike",
    "CalendarProviderLike",
    "ContextEngine",
    "ContextFragment",
    "GitHubToolLike",
    "MemoryStoreLike",
    "NoteListToolLike",
    "NoteReadToolLike",
    "RelevantContext",
    "SourceKind",
    "SourcePriority",
    "SourceReport",
    "TelegramClientLike",
    "UserRequest",
    "WorkspaceRepositoryLike",
]
