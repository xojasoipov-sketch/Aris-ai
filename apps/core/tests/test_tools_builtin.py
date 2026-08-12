"""Z1.10 — Built-in toollar testlari.

Tekshiriladi:
    - time.now: vaqt qaytaradi, timezone ishlaydi
    - note.write: fayl yaratadi, append ishlaydi, path traversal rad etiladi
    - shell.exec: default off, allowlist, xavfli belgilar rad etiladi
"""

from __future__ import annotations

from pathlib import Path

from zet.domain.enums import PermissionLevel, TrustLevel
from zet.tools.builtin.note_list import NoteListTool
from zet.tools.builtin.note_read import NoteReadTool
from zet.tools.builtin.note_write import NoteWriteTool
from zet.tools.builtin.shell_exec import ShellExecTool
from zet.tools.builtin.time_now import TimeNowTool


class TestTimeNow:
    """time.now testlari."""

    async def test_returns_time(self) -> None:
        """Hozirgi vaqtni qaytaradi."""
        tool = TimeNowTool()
        result = await tool.execute({})

        assert result.success is True
        assert "datetime" in result.output
        assert "date" in result.output
        assert "time" in result.output
        assert "timezone" in result.output
        assert "weekday" in result.output
        assert "unix_timestamp" in result.output

    async def test_default_timezone(self) -> None:
        """Default timezone — Asia/Tashkent."""
        tool = TimeNowTool(default_tz="UTC")
        result = await tool.execute({})

        assert result.output["timezone"] == "UTC"

    async def test_custom_timezone(self) -> None:
        """Boshqa timezone berilsa, o'sha ishlatiladi."""
        tool = TimeNowTool()
        result = await tool.execute({"timezone": "Europe/London"})

        assert result.output["timezone"] == "Europe/London"

    async def test_properties(self) -> None:
        """Tool xususiyatlari to'g'ri."""
        tool = TimeNowTool()
        assert tool.name == "time.now"
        assert tool.permission_level == PermissionLevel.READ
        assert tool.output_trust_level == TrustLevel.SYSTEM
        assert tool.idempotent is False
        assert tool.timeout_s == 5

    async def test_invalid_timezone(self) -> None:
        """Noto'g'ri timezone → xato."""
        tool = TimeNowTool()
        result = await tool.execute({"timezone": "Invalid/Zone"})

        assert result.success is False
        assert result.error is not None

    async def test_dry_run(self) -> None:
        """dry_run da haqiqiy vaqt qaytarmaydi."""
        tool = TimeNowTool()
        result = await tool.execute({}, dry_run=True)

        assert result.success is True
        assert result.output["dry_run"] is True


class TestNoteWrite:
    """note.write testlari."""

    async def test_create_note(self, tmp_path: Path) -> None:
        """Yangi eslatma yaratadi."""
        tool = NoteWriteTool(notes_dir=tmp_path / "notes")
        result = await tool.execute({"title": "test-note", "content": "# Salom\nMatn"})

        assert result.success is True
        assert result.output["action"] == "created"

        note_path = tmp_path / "notes" / "test-note.md"
        assert note_path.exists()
        assert note_path.read_text() == "# Salom\nMatn"

    async def test_overwrite_note(self, tmp_path: Path) -> None:
        """Mavjud eslatma ustiga yozadi."""
        tool = NoteWriteTool(notes_dir=tmp_path / "notes")
        await tool.execute({"title": "test", "content": "eski"})
        result = await tool.execute({"title": "test", "content": "yangi"})

        assert result.output["action"] == "updated"
        assert (tmp_path / "notes" / "test.md").read_text() == "yangi"

    async def test_append_note(self, tmp_path: Path) -> None:
        """Mavjud eslatmaga qo'shadi."""
        tool = NoteWriteTool(notes_dir=tmp_path / "notes")
        await tool.execute({"title": "test", "content": "birinchi"})
        result = await tool.execute({"title": "test", "content": "ikkinchi", "append": True})

        assert result.output["action"] == "appended"
        content = (tmp_path / "notes" / "test.md").read_text()
        assert "birinchi" in content
        assert "ikkinchi" in content

    async def test_path_traversal_rejected(self, tmp_path: Path) -> None:
        """Path traversal (../../etc/passwd) → rad etiladi (jimgina tozalanmaydi)."""
        tool = NoteWriteTool(notes_dir=tmp_path / "notes")
        result = await tool.execute({"title": "../../etc/passwd", "content": "xavfli"})

        assert result.success is False
        assert not (tmp_path / "etc").exists()

    async def test_slash_creates_subfolder(self, tmp_path: Path) -> None:
        """Slash (/) haqiqiy ichki papka yaratadi — Obsidian vault'i shunday tuzilgan."""
        tool = NoteWriteTool(notes_dir=tmp_path / "notes")
        result = await tool.execute({"title": "Loyihalar/ZET", "content": "ok"})

        assert result.success is True
        assert (tmp_path / "notes" / "Loyihalar" / "ZET.md").exists()
        assert result.output["title"] == "Loyihalar/ZET"

    async def test_content_too_large(self, tmp_path: Path) -> None:
        """100 KB dan katta matn → xato."""
        tool = NoteWriteTool(notes_dir=tmp_path / "notes")
        result = await tool.execute({"title": "big", "content": "x" * (101 * 1024)})

        assert result.success is False
        assert "katta" in (result.error or "")

    async def test_properties(self, tmp_path: Path) -> None:
        """Tool xususiyatlari to'g'ri."""
        tool = NoteWriteTool(notes_dir=tmp_path)
        assert tool.name == "note.write"
        assert tool.permission_level == PermissionLevel.WRITE
        assert tool.idempotent is True

    async def test_empty_title_rejected(self, tmp_path: Path) -> None:
        """Bo'sh nom → xato."""
        tool = NoteWriteTool(notes_dir=tmp_path / "notes")
        result = await tool.execute({"title": "   ", "content": "matn"})

        assert result.success is False

    async def test_dry_run(self, tmp_path: Path) -> None:
        """dry_run da fayl yaratilmaydi."""
        tool = NoteWriteTool(notes_dir=tmp_path / "notes")
        result = await tool.execute(
            {"title": "test", "content": "matn"},
            dry_run=True,
        )

        assert result.success is True
        assert result.output["dry_run"] is True
        assert not (tmp_path / "notes" / "test.md").exists()

    async def test_frontmatter_written(self, tmp_path: Path) -> None:
        """frontmatter berilsa — YAML fenc bilan saqlanadi."""
        tool = NoteWriteTool(notes_dir=tmp_path / "notes")
        result = await tool.execute(
            {"title": "test", "content": "Tana", "frontmatter": {"tags": ["a"]}}
        )

        assert result.success is True
        content = (tmp_path / "notes" / "test.md").read_text()
        assert content.startswith("---\n")
        assert "tags:" in content
        assert content.endswith("Tana")

    async def test_frontmatter_with_append_rejected(self, tmp_path: Path) -> None:
        """frontmatter + append birga → xato."""
        tool = NoteWriteTool(notes_dir=tmp_path / "notes")
        await tool.execute({"title": "test", "content": "birinchi"})
        result = await tool.execute(
            {
                "title": "test",
                "content": "ikkinchi",
                "append": True,
                "frontmatter": {"tags": ["a"]},
            }
        )
        assert result.success is False


class TestNoteRead:
    """note.read testlari."""

    async def test_read_plain_note(self, tmp_path: Path) -> None:
        write_tool = NoteWriteTool(notes_dir=tmp_path / "notes")
        await write_tool.execute({"title": "test", "content": "# Salom"})

        read_tool = NoteReadTool(notes_dir=tmp_path / "notes")
        result = await read_tool.execute({"title": "test"})

        assert result.success is True
        assert result.output["content"] == "# Salom"
        assert result.output["frontmatter"] == {}

    async def test_read_with_frontmatter(self, tmp_path: Path) -> None:
        write_tool = NoteWriteTool(notes_dir=tmp_path / "notes")
        await write_tool.execute(
            {"title": "test", "content": "Tana", "frontmatter": {"status": "active"}}
        )

        read_tool = NoteReadTool(notes_dir=tmp_path / "notes")
        result = await read_tool.execute({"title": "test"})

        assert result.output["frontmatter"] == {"status": "active"}
        assert result.output["content"] == "Tana"

    async def test_read_extracts_outgoing_links(self, tmp_path: Path) -> None:
        write_tool = NoteWriteTool(notes_dir=tmp_path / "notes")
        await write_tool.execute({"title": "a", "content": "Qarang [[b]]"})

        read_tool = NoteReadTool(notes_dir=tmp_path / "notes")
        result = await read_tool.execute({"title": "a"})

        assert result.output["links"] == ["b"]

    async def test_read_finds_backlinks(self, tmp_path: Path) -> None:
        write_tool = NoteWriteTool(notes_dir=tmp_path / "notes")
        await write_tool.execute({"title": "a", "content": "Salom"})
        await write_tool.execute({"title": "b", "content": "Qarang [[a]]"})
        await write_tool.execute({"title": "c", "content": "Bog'liq emas"})

        read_tool = NoteReadTool(notes_dir=tmp_path / "notes")
        result = await read_tool.execute({"title": "a"})

        assert result.output["backlinks"] == ["b"]

    async def test_read_missing_note_fails(self, tmp_path: Path) -> None:
        read_tool = NoteReadTool(notes_dir=tmp_path / "notes")
        result = await read_tool.execute({"title": "yoq"})

        assert result.success is False
        assert "topilmadi" in (result.error or "")

    async def test_properties(self, tmp_path: Path) -> None:
        tool = NoteReadTool(notes_dir=tmp_path)
        assert tool.name == "note.read"
        assert tool.permission_level == PermissionLevel.READ


class TestVaultFolders:
    """Haqiqiy Obsidian vault'i ichki papkalarga ega — ZET ularni ko'rishi shart."""

    async def test_list_finds_nested_notes(self, tmp_path: Path) -> None:
        write_tool = NoteWriteTool(notes_dir=tmp_path / "notes")
        await write_tool.execute({"title": "yuza", "content": "a"})
        await write_tool.execute({"title": "Loyihalar/ZET", "content": "b"})
        await write_tool.execute({"title": "Kundalik/2026-08-12", "content": "c"})

        list_tool = NoteListTool(notes_dir=tmp_path / "notes")
        result = await list_tool.execute({})

        titles = {n["title"] for n in result.output["notes"]}
        assert titles == {"yuza", "Loyihalar/ZET", "Kundalik/2026-08-12"}

    async def test_list_skips_obsidian_internals(self, tmp_path: Path) -> None:
        notes = tmp_path / "notes"
        (notes / ".obsidian").mkdir(parents=True)
        (notes / ".obsidian" / "workspace.md").write_text("config", encoding="utf-8")
        (notes / "haqiqiy.md").write_text("eslatma", encoding="utf-8")

        result = await NoteListTool(notes_dir=notes).execute({})
        assert [n["title"] for n in result.output["notes"]] == ["haqiqiy"]

    async def test_read_nested_note(self, tmp_path: Path) -> None:
        write_tool = NoteWriteTool(notes_dir=tmp_path / "notes")
        await write_tool.execute({"title": "Loyihalar/ZET", "content": "Loyiha matni"})

        result = await NoteReadTool(notes_dir=tmp_path / "notes").execute(
            {"title": "Loyihalar/ZET"}
        )
        assert result.success is True
        assert result.output["title"] == "Loyihalar/ZET"
        assert result.output["content"] == "Loyiha matni"

    async def test_backlink_across_folders_by_basename(self, tmp_path: Path) -> None:
        """Obsidian semantikasi: `[[ZET]]` boshqa papkadagi `Loyihalar/ZET` ga ishora qiladi."""
        write_tool = NoteWriteTool(notes_dir=tmp_path / "notes")
        await write_tool.execute({"title": "Loyihalar/ZET", "content": "Asosiy"})
        await write_tool.execute({"title": "Kundalik/bugun", "content": "Bugun [[ZET]] ustida"})

        result = await NoteReadTool(notes_dir=tmp_path / "notes").execute(
            {"title": "Loyihalar/ZET"}
        )
        assert result.output["backlinks"] == ["Kundalik/bugun"]

    async def test_backlink_with_full_path_link(self, tmp_path: Path) -> None:
        write_tool = NoteWriteTool(notes_dir=tmp_path / "notes")
        await write_tool.execute({"title": "Loyihalar/ZET", "content": "Asosiy"})
        await write_tool.execute({"title": "reja", "content": "[[Loyihalar/ZET]] ni ko'r"})

        result = await NoteReadTool(notes_dir=tmp_path / "notes").execute(
            {"title": "Loyihalar/ZET"}
        )
        assert result.output["backlinks"] == ["reja"]


class TestNoteList:
    """note.list testlari."""

    async def test_list_empty_vault(self, tmp_path: Path) -> None:
        tool = NoteListTool(notes_dir=tmp_path / "notes")
        result = await tool.execute({})

        assert result.success is True
        assert result.output["notes"] == []
        assert result.output["total"] == 0

    async def test_list_all_notes(self, tmp_path: Path) -> None:
        write_tool = NoteWriteTool(notes_dir=tmp_path / "notes")
        await write_tool.execute({"title": "a", "content": "matn a"})
        await write_tool.execute({"title": "b", "content": "matn b"})

        list_tool = NoteListTool(notes_dir=tmp_path / "notes")
        result = await list_tool.execute({})

        assert result.output["total"] == 2
        titles = {n["title"] for n in result.output["notes"]}
        assert titles == {"a", "b"}

    async def test_query_filters_by_title(self, tmp_path: Path) -> None:
        write_tool = NoteWriteTool(notes_dir=tmp_path / "notes")
        await write_tool.execute({"title": "loyiha-x", "content": "matn"})
        await write_tool.execute({"title": "boshqa", "content": "matn"})

        list_tool = NoteListTool(notes_dir=tmp_path / "notes")
        result = await list_tool.execute({"query": "loyiha"})

        assert result.output["total"] == 1
        assert result.output["notes"][0]["title"] == "loyiha-x"

    async def test_query_filters_by_content(self, tmp_path: Path) -> None:
        write_tool = NoteWriteTool(notes_dir=tmp_path / "notes")
        await write_tool.execute({"title": "a", "content": "noyob-kalit-so'z"})
        await write_tool.execute({"title": "b", "content": "boshqa matn"})

        list_tool = NoteListTool(notes_dir=tmp_path / "notes")
        result = await list_tool.execute({"query": "noyob-kalit"})

        assert result.output["total"] == 1

    async def test_limit_applied(self, tmp_path: Path) -> None:
        write_tool = NoteWriteTool(notes_dir=tmp_path / "notes")
        for i in range(5):
            await write_tool.execute({"title": f"note-{i}", "content": "matn"})

        list_tool = NoteListTool(notes_dir=tmp_path / "notes")
        result = await list_tool.execute({"limit": 2})

        assert len(result.output["notes"]) == 2
        assert result.output["total"] == 5

    async def test_properties(self, tmp_path: Path) -> None:
        tool = NoteListTool(notes_dir=tmp_path)
        assert tool.name == "note.list"
        assert tool.permission_level == PermissionLevel.READ


class TestShellExec:
    """shell.exec testlari."""

    async def test_disabled_by_default(self) -> None:
        """Default holatda o'chirilgan."""
        tool = ShellExecTool()
        result = await tool.execute({"command": "date"})

        assert result.success is False
        assert "o'chirilgan" in (result.error or "")

    async def test_enabled_allowlisted_command(self) -> None:
        """Yoqilgan va allowlist'dagi buyruq — muvaffaqiyatli."""
        tool = ShellExecTool(enabled=True)
        result = await tool.execute({"command": "echo salom"})

        assert result.success is True
        assert result.output["stdout"] == "salom"
        assert result.output["exit_code"] == 0

    async def test_not_in_allowlist(self) -> None:
        """Allowlist'dan tashqari buyruq → xato."""
        tool = ShellExecTool(enabled=True)
        result = await tool.execute({"command": "rm -rf /"})

        assert result.success is False
        assert "ruxsat berilmagan" in (result.error or "")

    async def test_dangerous_chars_rejected(self) -> None:
        """Shell injection belgilari → xato."""
        tool = ShellExecTool(enabled=True)
        result = await tool.execute({"command": "echo test; rm -rf /"})

        assert result.success is False
        assert "Xavfli belgi" in (result.error or "")

    async def test_pipe_rejected(self) -> None:
        """Pipe (|) → xato."""
        tool = ShellExecTool(enabled=True)
        result = await tool.execute({"command": "echo test | cat"})

        assert result.success is False
        assert "Xavfli belgi" in (result.error or "")

    async def test_command_substitution_rejected(self) -> None:
        """Backtick command substitution → xato."""
        tool = ShellExecTool(enabled=True)
        result = await tool.execute({"command": "echo `whoami`"})

        assert result.success is False
        assert "Xavfli belgi" in (result.error or "")

    async def test_dollar_rejected(self) -> None:
        """$ (variable expansion) → xato."""
        tool = ShellExecTool(enabled=True)
        result = await tool.execute({"command": "echo $HOME"})

        assert result.success is False
        assert "Xavfli belgi" in (result.error or "")

    async def test_custom_allowlist(self) -> None:
        """Maxsus allowlist ishlaydi."""
        tool = ShellExecTool(enabled=True, allowlist=frozenset({"echo"}))
        result = await tool.execute({"command": "date"})

        assert result.success is False
        assert "ruxsat berilmagan" in (result.error or "")

    async def test_properties(self) -> None:
        """Tool xususiyatlari to'g'ri."""
        tool = ShellExecTool()
        assert tool.name == "shell.exec"
        assert tool.permission_level == PermissionLevel.EXECUTE
        assert tool.output_trust_level == TrustLevel.UNTRUSTED
        assert tool.idempotent is False

    async def test_dry_run(self) -> None:
        """dry_run da haqiqiy buyruq bajarilmaydi."""
        tool = ShellExecTool(enabled=True)
        result = await tool.execute({"command": "echo test"}, dry_run=True)

        assert result.success is True
        assert result.output["dry_run"] is True

    async def test_nonexistent_command(self) -> None:
        """Mavjud bo'lmagan buyruq (allowlist'da) → xato."""
        tool = ShellExecTool(
            enabled=True,
            allowlist=frozenset({"nonexistent_cmd_xyz"}),
        )
        result = await tool.execute({"command": "nonexistent_cmd_xyz"})

        assert result.success is False

    async def test_stderr_captured(self) -> None:
        """stderr ham ushlanadi."""
        tool = ShellExecTool(enabled=True)
        result = await tool.execute({"command": "ls /nonexistent_path_xyz"})

        assert result.output["exit_code"] != 0
        assert result.output["stderr"] != ""
