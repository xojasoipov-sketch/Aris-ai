"""Bo'lim 2 — profil fayli ingest testlari.

Ikkita qism:
    1. `split_sections()` (umumiy modul, `zet.memory.profile_ingest`) —
       sof matn mantiqni sinaydi, HTTP'ga bog'liq emas.
    2. `POST /api/v1/memory/ingest-profile` — HTTP orqali fayl yuklash,
       natijani `POST /memory/search` orqali real DB'da tasdiqlash.

`scripts/ingest_profile.py` ham xuddi shu `split_sections()`dan
foydalanadi — bu yerdagi testlar ikkalasi uchun ham amal qiladi.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.testclient import TestClient

from zet.api.app import create_app
from zet.api.deps import get_db_session, get_memory_store
from zet.memory.profile_ingest import MAX_SECTION_CHARS, SOURCE_TAG, _slug, split_sections
from zet.memory.store import MemoryStore


class TestSplitSections:
    """`split_sections()` — sof matn funksiyasi."""

    def test_simple_section(self) -> None:
        """Oddiy `##` bo'limi — bitta yozuv, sarlavha bilan boshlanadi."""
        markdown = "# Profil\n\n## Loyihalar\n\nMen ZET ustida ishlayapman.\n"
        sections = split_sections(markdown)
        assert len(sections) == 1
        title, content = sections[0]
        assert title == "Loyihalar"
        assert content.startswith("Loyihalar")
        assert "Men ZET ustida ishlayapman." in content

    def test_multiple_sections(self) -> None:
        """Bir nechta `##` bo'limi — har biri alohida yozuv."""
        markdown = (
            "# Profil\n\n"
            "## Loyihalar\n\nMatn 1.\n\n"
            "## Texnik Stek\n\nMatn 2.\n"
        )
        sections = split_sections(markdown)
        titles = [t for t, _ in sections]
        assert titles == ["Loyihalar", "Texnik Stek"]

    def test_empty_section_skipped(self) -> None:
        """Mazmuni bo'sh bo'lim qo'shilmaydi."""
        markdown = "# Profil\n\n## Bo'sh Bo'lim\n\n## Mazmunli\n\nBor narsa.\n"
        sections = split_sections(markdown)
        assert len(sections) == 1
        assert sections[0][0] == "Mazmunli"

    def test_long_section_is_split(self) -> None:
        """`MAX_SECTION_CHARS`dan uzun bo'lim `###` bo'yicha bo'linadi."""
        long_text_a = "Gap. " * 700  # ancha uzun, MAX_SECTION_CHARS'dan katta
        long_text_b = "Boshqa gap. " * 700
        markdown = (
            "# Profil\n\n"
            "## Katta Bo'lim\n\n"
            f"### Sub A\n\n{long_text_a}\n\n"
            f"### Sub B\n\n{long_text_b}\n"
        )
        assert len(markdown) > MAX_SECTION_CHARS

        sections = split_sections(markdown)
        # `###` bo'yicha bo'linadi — har sarlavha o'z bo'lagini oladi
        # (ichki `###` bo'lak MAX_SECTION_CHARS'dan oshishi mumkin — bu
        # mavjud xatti-harakat, faqat sarlavhasiz bo'lim paragraf bo'yicha
        # qat'iy chegaralanadi, quyidagi testga qarang).
        assert len(sections) == 2
        titles = [t for t, _ in sections]
        assert titles == ["Katta Bo'lim (1)", "Katta Bo'lim (2)"]
        assert "Katta Bo'lim — Sub A" in sections[0][1]
        assert "Katta Bo'lim — Sub B" in sections[1][1]
        assert long_text_a.strip() in sections[0][1]
        assert long_text_b.strip() in sections[1][1]

    def test_long_section_without_subheadings_splits_by_paragraph(self) -> None:
        """`###` bo'lmasa — paragraf bo'yicha bo'linadi, har bo'lak chegaradan oshmaydi."""
        paragraphs = "\n\n".join(f"Paragraf {i} " * 60 for i in range(20))
        markdown = f"# Profil\n\n## Uzun Bo'lim\n\n{paragraphs}\n"
        assert len(markdown) > MAX_SECTION_CHARS

        sections = split_sections(markdown)
        assert len(sections) >= 2
        for _title, content in sections:
            assert len(content) <= MAX_SECTION_CHARS


class TestSlug:
    def test_slug_basic(self) -> None:
        assert _slug("Active Projects") == "active-projects"

    def test_slug_truncates(self) -> None:
        assert len(_slug("a" * 100)) <= 40


class TestIngestProfileEndpoint:
    """`POST /api/v1/memory/ingest-profile` — fayl-yuklash."""

    @pytest.fixture
    def store(self) -> MemoryStore:
        return MemoryStore()

    @pytest.fixture
    def client(self, store: MemoryStore) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_memory_store] = lambda: store
        return TestClient(app)

    def _markdown(self) -> bytes:
        return (
            b"# Ega Profili\n\n"
            b"## Bo'lim 1\n\nBirinchi bo'lim matni.\n\n"
            b"## Bo'lim 2\n\nIkkinchi bo'lim matni.\n"
        )

    def test_ingest_adds_sections(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/memory/ingest-profile",
            files={"file": ("test.md", self._markdown(), "text/markdown")},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["sections_found"] == 2
        assert data["added"] == 2
        assert data["failed"] == 0
        assert data["errors"] == []

    def test_ingest_entries_are_searchable(self, client: TestClient) -> None:
        """Yozilgan bo'limlar `POST /memory/search` orqali topiladi."""
        resp = client.post(
            "/api/v1/memory/ingest-profile",
            files={"file": ("test.md", self._markdown(), "text/markdown")},
        )
        assert resp.status_code == 201
        assert resp.json()["added"] >= 1

        search_resp = client.post(
            "/api/v1/memory/search",
            json={"text": "Birinchi bo'lim", "layers": ["personal"], "min_similarity": 0.0},
        )
        assert search_resp.status_code == 200
        results = search_resp.json()
        assert len(results) >= 1
        assert any(SOURCE_TAG in r["entry"]["tags"] for r in results)
        assert all(r["entry"]["layer"] == "personal" for r in results)

    def test_empty_file_returns_400(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/memory/ingest-profile",
            files={"file": ("empty.md", b"", "text/markdown")},
        )
        assert resp.status_code == 400

    def test_non_utf8_file_returns_400(self, client: TestClient) -> None:
        resp = client.post(
            "/api/v1/memory/ingest-profile",
            files={"file": ("bad.md", b"\xff\xfe\x00\xff", "text/markdown")},
        )
        assert resp.status_code == 400

    def test_oversized_file_returns_413(self, client: TestClient) -> None:
        too_big = b"# Profil\n\n## Bo'lim\n\n" + b"a" * 2_000_001
        resp = client.post(
            "/api/v1/memory/ingest-profile",
            files={"file": ("big.md", too_big, "text/markdown")},
        )
        assert resp.status_code == 413

    def test_untrusted_cannot_write_personal(self, client: TestClient) -> None:
        """`untrusted` trust PERSONAL qatlamga yoza olmaydi — 403."""
        resp = client.post(
            "/api/v1/memory/ingest-profile",
            headers={"X-Trust-Level": "untrusted"},
            files={"file": ("test.md", self._markdown(), "text/markdown")},
        )
        assert resp.status_code == 403

    def test_no_sections_found_returns_zero(self, client: TestClient) -> None:
        """`##` sarlavhasi yo'q fayl — 0 bo'lim, lekin 400/500 emas."""
        resp = client.post(
            "/api/v1/memory/ingest-profile",
            files={"file": ("flat.md", b"# Sarlavha\n\nSarlavhasiz matn.\n", "text/markdown")},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["sections_found"] == 0
        assert data["added"] == 0


class TestIngestProfileRealDB:
    """Default `get_memory_store` (PgMemoryStore, in-memory sqlite) — real DB'ga yozadi."""

    @pytest.fixture()
    def pg_client(self, session: AsyncSession) -> TestClient:
        app = create_app()

        async def _session_override():  # type: ignore[no-untyped-def]
            yield session

        app.dependency_overrides[get_db_session] = _session_override
        return TestClient(app)

    async def test_ingest_then_search_via_pg_store(self, pg_client: TestClient) -> None:
        markdown = "# Profil\n\n## Ish Uslubi\n\nAniq va qisqa javob beraman.\n"
        resp = pg_client.post(
            "/api/v1/memory/ingest-profile",
            files={"file": ("profile.md", markdown.encode("utf-8"), "text/markdown")},
        )
        assert resp.status_code == 201
        assert resp.json()["added"] == 1

        search_resp = pg_client.post(
            "/api/v1/memory/search",
            json={"text": "Ish Uslubi", "layers": ["personal"], "min_similarity": 0.0},
        )
        assert search_resp.status_code == 200
        results = search_resp.json()
        assert len(results) >= 1
        assert any("Aniq va qisqa javob beraman." in r["entry"]["content"] for r in results)
