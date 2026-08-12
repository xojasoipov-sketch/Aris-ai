"""tools/builtin/_vault.py testlari — frontmatter va wikilink yordamchilari."""

from __future__ import annotations

from pathlib import Path

import pytest

from zet.tools.base import ToolError
from zet.tools.builtin._vault import (
    extract_wikilinks,
    render_frontmatter,
    resolve_note_path,
    sanitize_title,
    split_frontmatter,
)


class TestSanitizeTitle:
    def test_simple_title_unchanged(self) -> None:
        assert sanitize_title("Loyiha rejasi") == "Loyiha rejasi"

    def test_strips_path_separators(self) -> None:
        assert sanitize_title("a/b\\c") == "a_b_c"

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

    def test_traversal_attempt_sanitized_stays_inside_vault(self, tmp_path: Path) -> None:
        # sanitize_title "/" va ".." ni oldindan tozalaydi — natija baribir vault ichida
        path = resolve_note_path(tmp_path, "../../etc/passwd")
        assert str(path).startswith(str(tmp_path.resolve()))


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
