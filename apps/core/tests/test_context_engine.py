"""ContextEngine testlari (Bo'lim 2, §2.3, Master Spec PART 4).

NEGA. ContextEngine ilgari yo'q edi — bu testlar Master Spec PART 4
"no full dump" va "never silently overwrite" invariantlarini qulflaydi.

Soxta manbalar (`FakeMemoryStore`, `FakeWorkspace`, `FakeCRM`, ...) —
real DB/tarmoqqa bog'lanmasdan retrieval kompozitsiyasini sinash uchun.
Real PgMemoryStore/PgCRM allaqachon o'z testlarida ishlashi qulflangan.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from zet.core.context import (
    MAX_CONTEXT_TOKENS,
    ContextEngine,
    ContextFragment,
    RelevantContext,
    SourceKind,
    SourcePriority,
    UserRequest,
    _reset_tiktoken_probe_for_tests,
)
from zet.domain.memory import MemoryEntry, MemoryLayer, MemoryQuery, MemorySearchResult

# ── Soxta bog'liqliklar ──────────────────────────────────────────


@dataclass
class FakeMemoryStore:
    """Berilgan yozuvlarni qaytaradi. `search` chaqirilishini yozib boradi."""

    entries: list[MemoryEntry] = field(default_factory=list)
    similarity: float = 0.7
    last_query: MemoryQuery | None = None

    async def search(
        self, query: MemoryQuery, *, now: datetime | None = None
    ) -> list[MemorySearchResult]:
        self.last_query = query
        return [
            MemorySearchResult(entry=e, similarity=self.similarity, rank=i + 1)
            for i, e in enumerate(self.entries[: query.limit])
        ]


@dataclass
class FakeProject:
    id: uuid.UUID
    name: str
    description: str = ""
    status: str = "active"


@dataclass
class FakeTask:
    id: uuid.UUID
    title: str
    description: str = ""
    status: str = "todo"


@dataclass
class FakeEvent:
    id: uuid.UUID
    title: str
    starts_at: datetime
    location: str = ""


@dataclass
class FakeWorkspace:
    projects: list[FakeProject] = field(default_factory=list)
    tasks: list[FakeTask] = field(default_factory=list)
    events: list[FakeEvent] = field(default_factory=list)

    async def list_projects(self, *, status: Any = None, limit: int = 100) -> list[FakeProject]:
        return list(self.projects[:limit])

    async def get_project(self, project_id: uuid.UUID) -> FakeProject:
        for p in self.projects:
            if p.id == project_id:
                return p
        raise LookupError(f"project {project_id} not found")

    async def list_tasks(
        self,
        *,
        status: Any = None,
        project_id: uuid.UUID | None = None,
        limit: int = 200,
    ) -> list[FakeTask]:
        return list(self.tasks[:limit])

    async def list_events(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> list[FakeEvent]:
        return list(self.events[:limit])


@dataclass
class FakeContact:
    id: str
    name: str
    phone: str = ""
    email: str = ""
    company: str = ""


@dataclass
class FakeDeal:
    id: str
    title: str
    stage: str = "proposal"
    amount: float = 0.0


@dataclass
class FakeCRM:
    contacts: list[FakeContact] = field(default_factory=list)
    deals: list[FakeDeal] = field(default_factory=list)

    async def find_contacts(self, query: str) -> list[FakeContact]:
        return list(self.contacts)

    async def list_deals(self, stage: Any = None) -> list[FakeDeal]:
        return list(self.deals)


@dataclass
class RecordingNoteRead:
    """`note.read` chaqiruvlarini yozib boradi (T08 spy)."""

    contents: dict[str, str] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    async def execute(self, params: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
        title = params.get("title", "")
        self.calls.append(title)
        return {
            "title": title,
            "path": f"/vault/{title}.md",
            "frontmatter": {},
            "content": self.contents.get(title, f"# {title}\ntartkib"),
            "links": [],
            "backlinks": [],
        }


@dataclass
class DirectoryNoteList:
    """Haqiqiy `notes_dir` bo'yicha `note.list` shakli."""

    notes_dir: Path

    async def execute(self, params: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
        query = (params.get("query") or "").lower()
        limit = params.get("limit", 50)
        matches: list[dict[str, Any]] = []
        for path in sorted(self.notes_dir.rglob("*.md")):
            title = path.relative_to(self.notes_dir).with_suffix("").as_posix()
            text = path.read_text(encoding="utf-8") if query else ""
            if query and query not in title.lower() and query not in text.lower():
                continue
            matches.append({"title": title, "path": str(path)})
            if len(matches) >= limit:
                break
        return {"notes": matches, "total": len(matches)}


class RaisingGitHub:
    """T09 — har qanday chaqiruvda ConnectionError."""

    is_real = True

    async def execute(self, params: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
        raise ConnectionError("stub connection refused")


@dataclass
class SlowTelegram:
    """T10 — `sleep_s` sekund uxlaydi (timeout uchun)."""

    sleep_s: float

    async def recent_messages(self, *, chat_id: int | str, limit: int = 20) -> list[dict[str, Any]]:
        await asyncio.sleep(self.sleep_s)
        return [{"id": 1, "text": "hi"}]


@dataclass
class SleepyMemory:
    """T11 — barcha manbalar bir vaqtda ishlashini isbotlash uchun."""

    sleep_s: float

    async def search(
        self, query: MemoryQuery, *, now: datetime | None = None
    ) -> list[MemorySearchResult]:
        await asyncio.sleep(self.sleep_s)
        return []


class SleepyWorkspace(FakeWorkspace):
    def __init__(self, sleep_s: float) -> None:
        super().__init__()
        self.sleep_s = sleep_s

    async def list_projects(self, *, status: Any = None, limit: int = 100) -> list[FakeProject]:
        await asyncio.sleep(self.sleep_s)
        return []

    async def list_tasks(
        self,
        *,
        status: Any = None,
        project_id: uuid.UUID | None = None,
        limit: int = 200,
    ) -> list[FakeTask]:
        await asyncio.sleep(self.sleep_s)
        return []

    async def list_events(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> list[FakeEvent]:
        await asyncio.sleep(self.sleep_s)
        return []


class SleepyCRM(FakeCRM):
    def __init__(self, sleep_s: float) -> None:
        super().__init__()
        self.sleep_s = sleep_s

    async def find_contacts(self, query: str) -> list[FakeContact]:
        await asyncio.sleep(self.sleep_s)
        return []

    async def list_deals(self, stage: Any = None) -> list[FakeDeal]:
        await asyncio.sleep(self.sleep_s)
        return []


# ── Yordamchi funksiyalar ────────────────────────────────────────


def _request(text: str = "test so'rovi", **kwargs: Any) -> UserRequest:
    """Standart UserRequest — testlar `text` va bir nechta maydonni bekor qiladi."""
    payload: dict[str, Any] = {
        "request_id": "req-1",
        "owner_id": uuid.uuid4(),
        "text": text,
    }
    payload.update(kwargs)
    return UserRequest(**payload)


def _entry(
    *,
    content: str,
    layer: MemoryLayer = MemoryLayer.KNOWLEDGE,
    tags: list[str] | None = None,
    created_at: datetime | None = None,
    trust: str = "owner",
    entry_id: str | None = None,
) -> MemoryEntry:
    return MemoryEntry(
        id=entry_id or uuid.uuid4().hex,
        layer=layer,
        content=content,
        summary=None,
        tags=tags or [],
        created_at=created_at or datetime.now(UTC),
        trust_level=trust,
    )


def _make_engine(
    *,
    memory: FakeMemoryStore | None = None,
    workspace: FakeWorkspace | None = None,
    crm: FakeCRM | None = None,
    notes_dir: Path | None = None,
    note_list: Any = None,
    note_read: Any = None,
    github: Any = None,
    telegram: Any = None,
    telegram_chat_id: int | None = None,
    calendar: Any = None,
    budget: int = MAX_CONTEXT_TOKENS,
) -> ContextEngine:
    return ContextEngine(
        owner_id=uuid.uuid4(),
        memory_store=memory,
        workspace_repo=workspace,
        crm=crm,
        notes_dir=notes_dir,
        note_list=note_list,
        note_read=note_read,
        github_tool=github,
        telegram_client=telegram,
        telegram_chat_id=telegram_chat_id,
        calendar_provider=calendar,
        budget_tokens=budget,
    )


# ── T01. Umumiy shakl ────────────────────────────────────────────


async def test_discover_returns_relevant_context_shape() -> None:
    engine = _make_engine()
    ctx = await engine.discover(_request("hello"))

    assert isinstance(ctx, RelevantContext)
    assert isinstance(ctx.fragments, tuple)
    # 9 manba — barchasi report'da ko'rinishi shart (bo'sh bo'lsa ham)
    assert len(ctx.reports) == 9
    assert {r.source for r in ctx.reports} == set(SourceKind)
    assert ctx.total_tokens <= ctx.budget_tokens
    assert ctx.generated_at is not None
    assert ctx.request_id == "req-1"


# ── T02. Memory priority mapping ─────────────────────────────────


async def test_memory_search_produces_fragments_with_correct_priority() -> None:
    now = datetime.now(UTC)
    memory = FakeMemoryStore(
        entries=[
            _entry(content="loyiha faktlari", layer=MemoryLayer.PROJECT, created_at=now),
            _entry(content="vazifa eslatmasi", layer=MemoryLayer.TASK, created_at=now),  # <7d
            _entry(
                content="eski umumiy fakt",
                layer=MemoryLayer.KNOWLEDGE,
                created_at=now - timedelta(days=180),
            ),
        ]
    )
    engine = _make_engine(memory=memory)
    ctx = await engine.discover(_request("qidiruv matni"))

    assert memory.last_query is not None
    assert memory.last_query.text == "qidiruv matni"

    by_source = ctx.by_source(SourceKind.MEMORY)
    priorities = {frag.content: frag.priority for frag in by_source}
    assert priorities["loyiha faktlari"] is SourcePriority.AUTHORITATIVE_SOURCE
    assert priorities["vazifa eslatmasi"] is SourcePriority.RECENT_MEMORY
    assert priorities["eski umumiy fakt"] is SourcePriority.OLDER_MEMORY


# ── T03. Obsidian top-N notes ────────────────────────────────────


async def test_obsidian_top_notes_are_read_and_included(tmp_path: Path) -> None:
    (tmp_path / "kundalik.md").write_text("# Kundalik\nbugungi kun haqida", encoding="utf-8")
    (tmp_path / "loyiha-alpha.md").write_text(
        "# Alpha\nalpha loyihasi eslatmalari", encoding="utf-8"
    )
    (tmp_path / "loyiha-beta.md").write_text(
        "# Beta\nalpha bilan bog'liq eslatma", encoding="utf-8"
    )
    (tmp_path / "boshqa.md").write_text("# Boshqa\numuman boshqa mavzu", encoding="utf-8")
    (tmp_path / "yana.md").write_text("# Yana\nyana boshqa", encoding="utf-8")

    note_list = DirectoryNoteList(notes_dir=tmp_path)
    note_read = RecordingNoteRead(
        contents={
            "loyiha-alpha": "# Alpha\nalpha loyihasi eslatmalari",
            "loyiha-beta": "# Beta\nalpha bilan bog'liq eslatma",
        }
    )
    engine = _make_engine(notes_dir=tmp_path, note_list=note_list, note_read=note_read)
    ctx = await engine.discover(_request("alpha"))

    obsidian = ctx.by_source(SourceKind.OBSIDIAN)
    origins = {frag.origin_id for frag in obsidian}
    assert len(obsidian) == 2
    assert all(frag.kind == "note" for frag in obsidian)
    assert all(frag.priority is SourcePriority.AUTHORITATIVE_SOURCE for frag in obsidian)
    assert set(note_read.calls) == {"loyiha-alpha", "loyiha-beta"}
    assert "/vault/loyiha-alpha.md" in origins


# ── T04. Current project hint promotes priority ────────────────


async def test_current_project_hint_promotes_priority() -> None:
    p1 = FakeProject(id=uuid.uuid4(), name="Alpha", description="joriy loyiha")
    p2 = FakeProject(id=uuid.uuid4(), name="Beta", description="boshqa loyiha")
    workspace = FakeWorkspace(
        projects=[p1, p2],
        tasks=[FakeTask(id=uuid.uuid4(), title="Alpha vazifa", description="joriy")],
    )
    engine = _make_engine(workspace=workspace)
    ctx = await engine.discover(_request("alpha nima?", hinted_project_id=p1.id))

    ws = ctx.by_source(SourceKind.WORKSPACE)
    # Faqat p1 fragmenti (get_project) + uning tasklari qaytishi kutiladi.
    project_frags = [f for f in ws if f.kind == "project"]
    assert len(project_frags) == 1
    assert project_frags[0].priority is SourcePriority.CURRENT_PROJECT
    assert ctx.resolved_project_id == p1.id


# ── T05. Konflikt resolveri hech qachon jimjit qayta yozmaydi ──


async def test_conflict_resolver_never_silently_overwrites(tmp_path: Path) -> None:
    (tmp_path / "Contact.md").write_text("# Contact\nMy phone: +998-90-1", encoding="utf-8")
    note_list = DirectoryNoteList(notes_dir=tmp_path)
    note_read = RecordingNoteRead(contents={"Contact": "# Contact\nMy phone: +998-90-1"})
    now = datetime.now(UTC)
    memory = FakeMemoryStore(
        entries=[
            _entry(
                content="Owner phone: +998-90-2",
                layer=MemoryLayer.TASK,
                tags=["phone"],
                created_at=now,
                entry_id="mem-phone",
            )
        ]
    )
    engine = _make_engine(
        memory=memory,
        notes_dir=tmp_path,
        note_list=note_list,
        note_read=note_read,
    )
    ctx = await engine.discover(_request("phone"))

    kept_content = "\n".join(f.content for f in ctx.fragments)
    assert "+998-90-1" in kept_content
    assert "+998-90-2" not in kept_content

    # Yutqizgan `dropped`da bo'lishi va `conflict-loser` yorlig'iga ega bo'lishi shart
    loser_ids = [f.origin_id for f in ctx.dropped if "conflict-loser" in f.labels]
    assert "mem-phone" in loser_ids

    # Konflikt yozuvi mavjud, winner OBSIDIAN
    assert ctx.conflicts, "konflikt ro'yxati bo'sh bo'lmasligi kerak"
    row = ctx.conflicts[0]
    assert row["winner"]["source"] == SourceKind.OBSIDIAN.value
    assert any(loser["source"] == SourceKind.MEMORY.value for loser in row["losers"])


# ── T06. Foydalanuvchi buyrug'i har doim yutadi ────────────────


async def test_source_of_truth_current_instruction_beats_everything(tmp_path: Path) -> None:
    (tmp_path / "Contact.md").write_text("# Contact\nMy phone: +998-90-1", encoding="utf-8")
    note_list = DirectoryNoteList(notes_dir=tmp_path)
    note_read = RecordingNoteRead(contents={"Contact": "# Contact\nMy phone: +998-90-1"})
    crm = FakeCRM(contacts=[FakeContact(id="c-owner", name="owner", phone="+998-90-2")])
    request = _request(
        "eslaymanmi",
        conversation_history=(
            {"role": "assistant", "content": "salom"},
            {"role": "user", "content": "My phone is +998-90-9"},
        ),
    )
    engine = _make_engine(
        crm=crm,
        notes_dir=tmp_path,
        note_list=note_list,
        note_read=note_read,
    )
    ctx = await engine.discover(request)

    kept_content = "\n".join(f.content for f in ctx.fragments)
    assert "+998-90-9" in kept_content
    assert "+998-90-1" not in kept_content
    assert "+998-90-2" not in kept_content

    winner_source = ctx.conflicts[0]["winner"]["source"]
    assert winner_source == SourceKind.CONVERSATION.value
    assert ctx.conflicts[0]["winner"]["priority"] == int(SourcePriority.USER_INSTRUCTION)


# ── T07. Budget kesimi ────────────────────────────────────────


async def test_budget_truncation_moves_excess_to_dropped() -> None:
    # 10 ta xotira yozuvi, har bir content ~200 belgi (~50 token)
    entries = [
        _entry(
            content=f"fakt-{i} " + ("x" * 200),
            layer=MemoryLayer.KNOWLEDGE,
        )
        for i in range(10)
    ]
    memory = FakeMemoryStore(entries=entries)
    engine = _make_engine(memory=memory, budget=200)
    ctx = await engine.discover(_request("izlash"))

    assert ctx.total_tokens <= 200
    assert ctx.truncated is True
    assert len(ctx.dropped) > 0


# ── T08. "no full dump" invariant ────────────────────────────


async def test_no_full_dump_never_reads_all_notes(tmp_path: Path) -> None:
    for i in range(50):  # 500 real bo'lardi — CI'da tezroq
        (tmp_path / f"note-{i}.md").write_text(f"# Note {i}\nqidiruv-matni {i}", encoding="utf-8")
    note_list = DirectoryNoteList(notes_dir=tmp_path)
    note_read = RecordingNoteRead()
    engine = _make_engine(notes_dir=tmp_path, note_list=note_list, note_read=note_read)
    await engine.discover(_request("qidiruv-matni"), max_fragments_per_source=8)

    assert len(note_read.calls) == 8, (
        f"note.read {len(note_read.calls)} marta chaqirildi, 8 kutildi"
    )


# ── T09. Manba xatosi fail-open ────────────────────────────────


async def test_source_failure_is_fail_open() -> None:
    engine = _make_engine(github=RaisingGitHub())
    ctx = await engine.discover(_request("github.com/foo/bar haqida"))

    github_report = next(r for r in ctx.reports if r.source is SourceKind.GITHUB)
    assert github_report.ok is False
    assert github_report.error is not None
    assert "ConnectionError" in github_report.error

    # Boshqa manbalar buzilmagan
    other_reports = [r for r in ctx.reports if r.source is not SourceKind.GITHUB]
    assert all(r.ok for r in other_reports)


# ── T10. Timeout hurmat qilinadi ─────────────────────────────


async def test_source_timeout_is_respected() -> None:
    engine = _make_engine(telegram=SlowTelegram(sleep_s=5.0), telegram_chat_id=42)
    start = time.monotonic()
    ctx = await engine.discover(_request("salom"), source_timeout_s=0.1)
    elapsed = time.monotonic() - start

    assert elapsed < 1.0, f"discover {elapsed:.2f}s, timeout ishlamadi"
    telegram_report = next(r for r in ctx.reports if r.source is SourceKind.TELEGRAM)
    assert telegram_report.ok is False
    assert telegram_report.error is not None
    assert "timeout" in telegram_report.error.lower()


# ── T11. Parallel dispatch ──────────────────────────────────────


async def test_parallel_source_dispatch() -> None:
    engine = _make_engine(
        memory=SleepyMemory(sleep_s=0.3),
        workspace=SleepyWorkspace(sleep_s=0.3),
        crm=SleepyCRM(sleep_s=0.3),
    )
    start = time.monotonic()
    await engine.discover(_request("salom"), source_timeout_s=2.0)
    elapsed = time.monotonic() - start

    # 3 manba x 0.3s = seriya bo'lsa >=0.9s. Parallel bo'lsa ~0.3s.
    assert elapsed < 0.8, f"parallel emas, {elapsed:.2f}s"


# ── T12. Optional manbalar absent ─────────────────────────────


async def test_optional_sources_absent_do_not_error() -> None:
    engine = _make_engine(github=None, telegram=None, calendar=None)
    ctx = await engine.discover(_request("test"))

    for kind in (SourceKind.GITHUB, SourceKind.TELEGRAM, SourceKind.CALENDAR):
        rep = next(r for r in ctx.reports if r.source is kind)
        assert rep.ok is True
        assert rep.count == 0
        assert rep.error is None


# ── T13. Owner isolation ──────────────────────────────────────


async def test_owner_isolation_only_sees_own_repos() -> None:
    """ContextEngine faqat qurilganda berilgan repozitoriylarni chaqiradi.

    Real owner filtratsiyasi repozitoriyning O'ZIDA (`PgMemoryStore`,
    `PgCRM`, ...) qulflangan. Bu yerda ContextEngine hech qachon boshqa
    repozitoriyni chaqirmasligini tekshiramiz — bitta owner uchun
    qurilgan engine boshqa owner ma'lumotini olib kelolmaydi.
    """
    owner_a_workspace = FakeWorkspace(projects=[FakeProject(id=uuid.uuid4(), name="A-loyiha")])
    engine = ContextEngine(
        owner_id=uuid.uuid4(),
        workspace_repo=owner_a_workspace,
    )
    ctx = await engine.discover(_request("a-loyiha"))
    for frag in ctx.by_source(SourceKind.WORKSPACE):
        assert "A-loyiha" in frag.content


# ── T14. as_prompt_block sarlavhalar bilan ─────────────────────


async def test_as_prompt_block_groups_by_source() -> None:
    p1 = FakeProject(id=uuid.uuid4(), name="Alpha")
    workspace = FakeWorkspace(projects=[p1])
    memory = FakeMemoryStore(
        entries=[
            _entry(content="alpha fakt", layer=MemoryLayer.PROJECT),
        ]
    )
    engine = _make_engine(memory=memory, workspace=workspace)
    ctx = await engine.discover(_request("alpha"))
    block = ctx.as_prompt_block(sections=True)

    assert "## MEMORY" in block
    assert "## WORKSPACE" in block
    # Fragmentlarning kontenti ham chiqadi
    assert "Alpha" in block
    assert "alpha fakt" in block


# ── T15. Inference label eng past priority ─────────────────────


async def test_inference_label_and_lowest_priority() -> None:
    # ContextFragment'ni to'g'ridan-to'g'ri yaratamiz — INFERENCE priority
    # bilan boshqa manbadan kelgan ustunlik qilishi kerak.
    now = datetime.now(UTC)
    engine = _make_engine()

    high_frag = ContextFragment(
        source=SourceKind.OBSIDIAN,
        kind="note",
        content="phone: +998-90-1 (ishonchli manba)",
        tokens=10,
        priority=SourcePriority.AUTHORITATIVE_SOURCE,
        retrieved_at=now,
        conflict_key="contact.phone:me",
    )
    inferred_frag = ContextFragment(
        source=SourceKind.MEMORY,
        kind="memory_entry",
        content="inferred: phone might be +998-90-5",
        tokens=10,
        priority=SourcePriority.INFERENCE,
        labels=("inferred",),
        retrieved_at=now,
        conflict_key="contact.phone:me",
    )
    winners, conflicts, losers = engine._resolve_conflicts([inferred_frag, high_frag])
    assert high_frag in winners
    assert inferred_frag not in winners
    assert any("conflict-loser" in loser.labels for loser in losers)
    assert conflicts[0]["winner"]["source"] == SourceKind.OBSIDIAN.value


# ── T16. tiktoken fallback ────────────────────────────────────


async def test_token_counter_uses_tiktoken_when_available_and_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    _reset_tiktoken_probe_for_tests()
    original_import = builtins.__import__

    def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "tiktoken":
            raise ImportError("tiktoken unavailable in test")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    engine = _make_engine()
    tokens = engine._count_tokens("bu matn taxminan qancha token?")
    assert tokens >= 1
    # Fallback: len // 4
    expected = max(1, len("bu matn taxminan qancha token?") // 4)
    assert tokens == expected

    # Ikkinchi chaqiruvda ham warning takrorlanmasligi kerak (probe kesh)
    engine._count_tokens("boshqa matn")
    _reset_tiktoken_probe_for_tests()  # keyingi testlar uchun tozalash
