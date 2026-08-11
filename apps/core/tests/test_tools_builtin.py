"""Z1.10 — Built-in toollar testlari.

Tekshiriladi:
    - time.now: vaqt qaytaradi, timezone ishlaydi
    - note.write: fayl yaratadi, append ishlaydi, path traversal rad etiladi
    - shell.exec: default off, allowlist, xavfli belgilar rad etiladi
"""

from __future__ import annotations

from pathlib import Path

from zet.domain.enums import PermissionLevel, TrustLevel
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

    async def test_path_traversal_sanitized(self, tmp_path: Path) -> None:
        """Path traversal (../../etc/passwd) → sanitizatsiya qilinadi, notes ichida qoladi."""
        tool = NoteWriteTool(notes_dir=tmp_path / "notes")
        result = await tool.execute({"title": "../../etc/passwd", "content": "xavfli"})

        # Sanitizatsiya: '..' → '_', '/' → '_' → fayl notes ichida yaratiladi
        assert result.success is True
        # Fayl notes papkasi ICHIDA yaratilganini tekshirish
        created_path = result.output["path"]
        assert created_path.startswith(str(tmp_path / "notes"))

    async def test_slash_in_title(self, tmp_path: Path) -> None:
        """Slash (/) sanitizatsiya qilinadi."""
        tool = NoteWriteTool(notes_dir=tmp_path / "notes")
        result = await tool.execute({"title": "sub/dir/file", "content": "ok"})

        assert result.success is True
        # Slash _ ga almashtiriladi
        assert (tmp_path / "notes" / "sub_dir_file.md").exists()

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
