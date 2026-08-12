"""tools/builtin/_vault.py testlari — frontmatter va wikilink yordamchilari."""

from __future__ import annotations

from pathlib import Path

import pytest

from zet.tools.base import ToolError
from zet.tools.builtin._vault import (
    extract_wikilinks,
    iter_notes,
    note_title,
    render_frontmatter,
    resolve_note_path,
    sanitize_title,
    split_frontmatter,
    wikilink_targets,
)


class TestSanitizeTitle:
    def test_simple_title_unchanged(self) -> None:
        assert sanitize_title("Loyiha rejasi") == "Loyiha rejasi"

    def test_path_separators_become_folders(self) -> None:
        """Obsidian vault'ida ichki papkalar bor — `/` papka ajratuvchisi."""
        assert sanitize_title("a/b\\c") == "a/b/c"

    def test_collapses_empty_segments(self) -> None:
        assert sanitize_title("Loyihalar//ZET") == "Loyihalar/ZET"

    def test_rejects_parent_traversal(self) -> None:
        with pytest.raises(ToolError, match=r"\.\."):
            sanitize_title("../../etc/passwd")

    def test_rejects_too_deep(self) -> None:
        with pytest.raises(ToolError, match="chuqur"):
            sanitize_title("/".join(f"d{i}" for i in range(12)))

    def test_rejects_empty(self) -> None:
        with pytest.raises(ToolError):
            sanitize_title("   ")

    def test_rejects_unsafe_chars(self) -> None:
        with pytest.raises(ToolError):
            sanitize_title("bad<>name")


class TestResolveNotePath:
    def test_resolves_inside_vault(self, tmp_path: Path) -> None:
        path = resolve_note_path(tmp_path, "Mening eslatmam")
        assert path == (tmp_path / "Mening eslatmam.md").resolve()

    def test_resolves_nested_folder(self, tmp_path: Path) -> None:
        path = resolve_note_path(tmp_path, "Loyihalar/ZET")
        assert path == (tmp_path / "Loyihalar" / "ZET.md").resolve()

    def test_rejects_traversal(self, tmp_path: Path) -> None:
        with pytest.raises(ToolError):
            resolve_note_path(tmp_path, "../../etc/passwd")

    def test_result_always_inside_vault(self, tmp_path: Path) -> None:
        path = resolve_note_path(tmp_path, "Loyihalar/Ichki/Eslatma")
        assert path.is_relative_to(tmp_path.resolve())


class TestFrontmatter:
    def test_split_no_frontmatter(self) -> None:
        fm, body = split_frontmatter("Oddiy matn")
        assert fm == {}
        assert body == "Oddiy matn"

    def test_split_with_frontmatter(self) -> None:
        text = "---\ntags:\n  - loyiha\nstatus: active\n---\nTana matni"
        fm, body = split_frontmatter(text)
        assert fm == {"tags": ["loyiha"], "status": "active"}
        assert body == "Tana matni"

    def test_split_malformed_yaml_fails_open(self) -> None:
        text = "---\n{unbalanced: [1, 2\n---\nTana"
        fm, body = split_frontmatter(text)
        assert fm == {}
        assert body == text  # butun matn qaytadi, tana ajratilmaydi

    def test_split_non_dict_frontmatter_fails_open(self) -> None:
        text = "---\n- item1\n- item2\n---\nTana"
        fm, body = split_frontmatter(text)
        assert fm == {}
        assert body == text

    def test_render_empty_frontmatter_returns_body_only(self) -> None:
        assert render_frontmatter({}, "Tana") == "Tana"

    def test_render_roundtrip(self) -> None:
        rendered = render_frontmatter({"tags": ["a", "b"]}, "Tana matni")
        fm, body = split_frontmatter(rendered)
        assert fm == {"tags": ["a", "b"]}
        assert body == "Tana matni"


class TestWikilinks:
    def test_extract_simple(self) -> None:
        assert extract_wikilinks("Qarang: [[Boshqa eslatma]]") == ["Boshqa eslatma"]

    def test_extract_with_alias(self) -> None:
        assert extract_wikilinks("[[Eslatma|Ko'rsatiladigan nom]]") == ["Eslatma"]

    def test_extract_with_heading(self) -> None:
        assert extract_wikilinks("[[Eslatma#Bo'lim]]") == ["Eslatma"]

    def test_extract_multiple_dedup(self) -> None:
        text = "[[A]] va [[B]] va yana [[A]]"
        assert extract_wikilinks(text) == ["A", "B"]

    def test_extract_none(self) -> None:
        assert extract_wikilinks("Oddiy matn, havolasiz") == []


class TestIterNotes:
    def test_missing_vault_yields_nothing(self, tmp_path: Path) -> None:
        assert list(iter_notes(tmp_path / "yoq")) == []

    def test_finds_nested_notes(self, tmp_path: Path) -> None:
        (tmp_path / "Loyihalar").mkdir()
        (tmp_path / "yuza.md").write_text("a")
        (tmp_path / "Loyihalar" / "ichki.md").write_text("b")

        titles = {note_title(tmp_path, p) for p in iter_notes(tmp_path)}
        assert titles == {"yuza", "Loyihalar/ichki"}

    def test_skips_obsidian_config_folder(self, tmp_path: Path) -> None:
        """Haqiqiy vault'da `.obsidian` bor — u eslatma emas."""
        (tmp_path / ".obsidian").mkdir()
        (tmp_path / ".obsidian" / "workspace.md").write_text("config")
        (tmp_path / ".trash").mkdir()
        (tmp_path / ".trash" / "eski.md").write_text("o'chirilgan")
        (tmp_path / "haqiqiy.md").write_text("eslatma")

        titles = {note_title(tmp_path, p) for p in iter_notes(tmp_path)}
        assert titles == {"haqiqiy"}

    def test_ignores_non_markdown(self, tmp_path: Path) -> None:
        (tmp_path / "rasm.png").write_text("binary")
        (tmp_path / "eslatma.md").write_text("matn")

        assert [note_title(tmp_path, p) for p in iter_notes(tmp_path)] == ["eslatma"]


class TestWikilinkTargets:
    def test_exact_path_match(self) -> None:
        assert wikilink_targets("Loyihalar/ZET", "Loyihalar/ZET")

    def test_basename_matches_nested_note(self) -> None:
        """Obsidian'da `[[ZET]]` `Loyihalar/ZET.md` ga ishora qiladi."""
        assert wikilink_targets("ZET", "Loyihalar/ZET")

    def test_full_path_link_does_not_match_other_folder(self) -> None:
        assert not wikilink_targets("Boshqa/ZET", "Loyihalar/ZET")

    def test_different_name_no_match(self) -> None:
        assert not wikilink_targets("Boshqa", "Loyihalar/ZET")


class TestUnicodeNames:
    """Obsidian Unicode fayl nomlarini qo'llab-quvvatlaydi — ZET ham shunday.

    Ega o'zbek tilida yozadi (`gʻ`, `oʻ`, kirill) — ASCII-only cheklov
    haqiqiy vault bilan ishlashni to'sib qo'yardi.
    """

    @pytest.mark.parametrize(
        "title",
        [
            "Yangi gʻoya",
            "Oʻzbekcha eslatma",
            "Ғоялар",
            "日本語",
            "Ideas 💡",
            "Loyihalar/ZET reja",
        ],
    )
    def test_accepts_unicode(self, title: str) -> None:
        assert sanitize_title(title) == title

    @pytest.mark.parametrize(
        "title",
        [
            "bad<>name",
            "a:b",
            "a|b",
            'a"b',
            "a\x00b",
            "a‮b",  # RTL override — nom spoofing
        ],
    )
    def test_rejects_unsafe_chars(self, title: str) -> None:
        with pytest.raises(ToolError):
            sanitize_title(title)

    @pytest.mark.parametrize("title", ["CON", "nul.md", "COM1", "lpt9"])
    def test_rejects_windows_reserved(self, title: str) -> None:
        with pytest.raises(ToolError, match="band"):
            sanitize_title(title)

    def test_rejects_overlong_segment(self) -> None:
        with pytest.raises(ToolError, match="uzun"):
            sanitize_title("x" * 150)

    def test_strips_trailing_dot_and_space(self) -> None:
        assert sanitize_title("Eslatma. ") == "Eslatma"
