"""Capability Registry testlari (Master Spec PART 2).

Tekshiriladi:
    T1  — register/get + not-found
    T2  — dubl registratsiya reject
    T3  — frozen model immutability
    T4  — dep cikl rad etiladi + register_many rollback
    T5  — resolve() topo-sort + diamond dedup
    T6  — resolve() agent/tool/permission/risk agregatsiyasi
    T7  — resolve() missing_dependencies (fail-open)
    T8  — inverted index lookup (outcome/action/tag)
    T9  — builtin 20 seed + "launch business" scenario
    T10 — signatures() shape planner uchun
    T11 — register_many atomic on failure
    T12 — PermissionLevel ordering resolution ichida
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from zet.core.capability import (
    Capability,
    CapabilityCycleError,
    CapabilityNotFoundError,
    CapabilityRegistry,
    builtin_capabilities,
)
from zet.domain.enums import PermissionLevel, RiskLevel, VerificationStrategy


def _cap(
    name: str,
    *,
    description: str | None = None,
    dependencies: list[str] | None = None,
    agents: list[str] | None = None,
    tools: list[str] | None = None,
    permission: PermissionLevel = PermissionLevel.READ,
    risk: RiskLevel = RiskLevel.LOW,
    outcomes: list[str] | None = None,
    actions: list[str] | None = None,
    tags: list[str] | None = None,
) -> Capability:
    return Capability(
        name=name,
        description=description or f"cap {name}",
        dependencies=dependencies or [],
        default_agents=agents or [],
        default_tools=tools or [],
        permission_level=permission,
        risk_level=risk,
        supported_outcomes=outcomes or [],
        actions=actions or [],
        tags=tags or [],
    )


class TestRegisterGet:
    def test_register_and_get(self) -> None:
        """T1 — register saqlaydi, get qaytaradi, not-found xato beradi."""
        reg = CapabilityRegistry()
        cap = _cap("website", description="Build sites")
        reg.register(cap)
        assert reg.get("website") is cap
        assert reg.count == 1
        assert reg.has("website")
        with pytest.raises(CapabilityNotFoundError):
            reg.get("nope")

    def test_duplicate_registration_rejected(self) -> None:
        """T2 — bir nom ikki marta register — ValueError."""
        reg = CapabilityRegistry()
        reg.register(_cap("website"))
        with pytest.raises(ValueError, match="website"):
            reg.register(_cap("website"))

    def test_name_regex_enforced(self) -> None:
        """Capability nomi snake_case: bosh harf yoki tire — ValidationError."""
        with pytest.raises(ValidationError):
            Capability(name="Website", description="x")
        with pytest.raises(ValidationError):
            Capability(name="web-site", description="x")

    def test_self_dependency_rejected(self) -> None:
        """Model validator: o'ziga bog'lanish taqiqlanadi."""
        with pytest.raises(ValidationError):
            Capability(name="a", description="x", dependencies=["a"])


class TestImmutability:
    def test_frozen_model_immutability(self) -> None:
        """T3 — Capability o'zgarmas: setattr ValidationError."""
        cap = builtin_capabilities()[0]
        with pytest.raises(ValidationError):
            cap.description = "x"  # type: ignore[misc]

    def test_registry_preserves_identity(self) -> None:
        """Registry saqlagan capability aynan bir obyekt qaytariladi."""
        reg = CapabilityRegistry()
        cap = _cap("solo")
        reg.register(cap)
        assert reg.get("solo") is cap


class TestCycleDetection:
    def test_dependency_cycle_rejected_in_batch(self) -> None:
        """T4 — register_many ichida cikl bo'lsa — CapabilityCycleError + full rollback."""
        reg = CapabilityRegistry()
        batch = [
            _cap("x", dependencies=["y"]),
            _cap("y", dependencies=["x"]),
        ]
        with pytest.raises(CapabilityCycleError):
            reg.register_many(batch)
        assert reg.count == 0
        assert not reg.has("x")
        assert not reg.has("y")

    def test_transitive_cycle_rejected(self) -> None:
        """A→B→C→A ham ushlanadi."""
        reg = CapabilityRegistry()
        batch = [
            _cap("a", dependencies=["c"]),
            _cap("b", dependencies=["a"]),
            _cap("c", dependencies=["b"]),
        ]
        with pytest.raises(CapabilityCycleError):
            reg.register_many(batch)
        assert reg.count == 0


class TestResolve:
    def test_resolve_composes_and_topo_sorts_transitive_deps(self) -> None:
        """T5 — diamond: content-ni ikki farzand ishlatadi, faqat bir marta chiqadi."""
        reg = CapabilityRegistry()
        reg.register(_cap("content"))
        reg.register(_cap("design", dependencies=["content"]))
        reg.register(_cap("copywriting", dependencies=["content"]))
        reg.register(_cap("website", dependencies=["design", "copywriting"]))

        res = reg.resolve(["website"])
        names = [c.name for c in res.capabilities]

        # content — birinchi (dep-first)
        assert names[0] == "content"
        # website — oxirgi
        assert names[-1] == "website"
        # design va copywriting content'dan keyin, website'dan oldin
        assert names.index("design") > 0
        assert names.index("copywriting") > 0
        assert names.index("design") < names.index("website")
        assert names.index("copywriting") < names.index("website")
        # diamond dedup — har biri bir marta
        assert len(names) == len(set(names)) == 4

    def test_resolve_aggregates_agents_tools_permission_risk(self) -> None:
        """T6 — agent/tool birlashmasi + max permission + max risk."""
        reg = CapabilityRegistry()
        reg.register(
            _cap(
                "a",
                agents=["research"],
                tools=["web.search"],
                permission=PermissionLevel.READ,
                risk=RiskLevel.LOW,
            )
        )
        reg.register(
            _cap(
                "b",
                agents=["developer"],
                tools=["github.write"],
                permission=PermissionLevel.WRITE,
                risk=RiskLevel.MEDIUM,
                dependencies=["a"],
            )
        )
        reg.register(
            _cap(
                "c",
                agents=["deployer"],
                tools=["deploy.push"],
                permission=PermissionLevel.EXECUTE,
                risk=RiskLevel.HIGH,
                dependencies=["b"],
            )
        )

        res = reg.resolve(["c"])
        assert set(res.agents) == {"research", "developer", "deployer"}
        assert set(res.tools) == {"web.search", "github.write", "deploy.push"}
        assert res.required_permission == PermissionLevel.EXECUTE
        assert res.max_risk == RiskLevel.HIGH

    def test_resolve_reports_missing_dependencies_without_raising(self) -> None:
        """T7 — noma'lum dep resolve()'ni yiqmaydi, faqat missing'ga tushadi."""
        reg = CapabilityRegistry()
        reg.register(_cap("website", dependencies=["brand_kit"]))
        res = reg.resolve(["website"])
        assert "brand_kit" in res.missing_dependencies
        assert res.capabilities[-1].name == "website"

    def test_resolve_empty_input(self) -> None:
        """Bo'sh shortlist — bo'sh natija (fail-open)."""
        reg = CapabilityRegistry()
        reg.register(_cap("a"))
        res = reg.resolve([])
        assert res.capabilities == []
        assert res.agents == []
        assert res.tools == []
        assert res.missing_dependencies == []


class TestIndices:
    def test_indices_list_by_outcome_and_action_and_tag(self) -> None:
        """T8 — inverted indexlar to'g'ri javob beradi."""
        reg = CapabilityRegistry()
        reg.register_many(builtin_capabilities())

        # publish_post — instagram (telegram bo'lmasin, u post emas send_message qiladi)
        by_publish = [c.name for c in reg.list_by_outcome("publish_post")]
        assert "instagram" in by_publish

        # deploy action — website + deployment
        by_deploy = {c.name for c in reg.list_by_action("deploy")}
        assert {"website", "deployment"}.issubset(by_deploy)

        # marketing teg — content + instagram + smm ...
        by_marketing = {c.name for c in reg.list_capabilities(tag="marketing")}
        assert {"content", "instagram", "smm"}.issubset(by_marketing)

    def test_list_capabilities_max_risk_filter(self) -> None:
        """max_risk filtri LOW+MEDIUM qaytaradi, HIGH'ni tashlab yuboradi."""
        reg = CapabilityRegistry()
        reg.register_many(builtin_capabilities())
        low_med = reg.list_capabilities(max_risk=RiskLevel.MEDIUM)
        names = {c.name for c in low_med}
        # HIGH bo'lganlar chetlanadi
        assert "computer" not in names
        assert "deployment" not in names
        assert "security" not in names
        # LOW/MEDIUM ichida:
        assert "content" in names
        assert "website" in names

    def test_search_scans_description_and_tags(self) -> None:
        """search kandidatlarni qisqartiradi — phrase-match emas, count-based."""
        reg = CapabilityRegistry()
        reg.register_many(builtin_capabilities())
        hits = reg.search(["instagram"])
        assert any(c.name == "instagram" for c in hits)
        empty = reg.search([])
        assert empty == []


class TestBuiltins:
    def test_builtin_capabilities_ships_20_and_passes_registry(self) -> None:
        """T9 — 20 seed capability barcha kutilgan nomlar bilan, launch business scenario resolve."""
        caps = builtin_capabilities()
        assert len(caps) == 20
        expected = {
            "business",
            "branding",
            "website",
            "instagram",
            "telegram",
            "sales",
            "analytics",
            "automation",
            "content",
            "design",
            "research",
            "smm",
            "camera",
            "computer",
            "deployment",
            "github",
            "obsidian",
            "security",
            "finance",
            "communication",
        }
        assert {c.name for c in caps} == expected

        reg = CapabilityRegistry()
        reg.register_many(caps)  # istisno bo'lmasligi kerak
        assert reg.count == 20

        res = reg.resolve(
            [
                "business",
                "branding",
                "website",
                "instagram",
                "telegram",
                "sales",
                "analytics",
                "automation",
            ]
        )
        assert res.missing_dependencies == []
        names = [c.name for c in res.capabilities]
        assert "website" in names
        assert "instagram" in names

    def test_builtin_verification_strategies_valid(self) -> None:
        """Har seed capability haqiqiy VerificationStrategy enum qiymatiga ega."""
        for cap in builtin_capabilities():
            assert isinstance(cap.verification_strategy, VerificationStrategy)


class TestSignatures:
    def test_signatures_shape_for_planner(self) -> None:
        """T10 — signatures() planner LLM shortlisteri kutgan kalitlarni beradi."""
        reg = CapabilityRegistry()
        reg.register_many(builtin_capabilities())
        sigs = reg.signatures()
        required_keys = {"name", "description", "outcomes", "actions", "risk", "agents", "tools"}
        for sig in sigs:
            assert required_keys.issubset(sig.keys())
        assert any(sig["name"] == "instagram" and "publish_post" in sig["outcomes"] for sig in sigs)


class TestRegisterManyAtomicity:
    def test_register_many_is_atomic_on_failure(self) -> None:
        """T11 — batch ichida dubl bo'lsa — hech biri qolmasin."""
        reg = CapabilityRegistry()
        batch = [_cap("a"), _cap("b", dependencies=["a"]), _cap("a")]
        with pytest.raises(ValueError):
            reg.register_many(batch)
        assert reg.count == 0
        assert not reg.has("a")
        assert not reg.has("b")


class TestPermissionOrdering:
    def test_permission_level_ordering_used_in_resolution(self) -> None:
        """T12 — required_permission ADMIN gacha yetadi (max operator)."""
        reg = CapabilityRegistry()
        reg.register(_cap("r", permission=PermissionLevel.READ))
        reg.register(_cap("w", permission=PermissionLevel.WRITE))
        reg.register(_cap("a", permission=PermissionLevel.ADMIN))
        res = reg.resolve(["r", "w", "a"])
        assert res.required_permission == PermissionLevel.ADMIN
