"""Capability Registry — yuqori darajali qobiliyatlar allowlist (Master Spec PART 2).

Capability = "bo'lim"ga o'xshash yuqori darajali qobiliyat (Website, Instagram,
Sales, ...). U MissionEngine bilan mavjud AgentRegistry/ToolRegistry o'rtasida
turadi. MissionEngine UNDERSTANDING→PLANNING bosqichida capability tanlab, uni
konkret agent + tool + risk + verification strategiyasiga yoyadi.

NEGA: Ilgari MissionEngine har mission uchun to'g'ridan-to'g'ri tool va agent
ro'yxatlari tuzardi — bu qattiq kodlangan iboralar (phrase-matching) yoki
LLM'ga barcha yuzlab tool imzosini uzatishga olib kelardi. Capability qatlami
esa (a) semantik "qobiliyatlar" ustidan qidiruv beradi, (b) risk + verification
strategiyasini bir joyda ushlab turadi, (c) mission darajasida bitta approval
darvozasini o'tkazadi.

Bog'liq qarorlar:
    V-31 — permission tekshiruvi (Capability.permission_level shu tomonga)
    A-01 — mission holat mashinasi (WAITING_APPROVAL escalation)
    A-05 — ishonch chegarasi (RiskLevel high/critical mission approval'ni oshiradi)

Integratsiya:
    MissionEngine.PLANNING → resolution = registry.resolve(shortlist)
    Planner.build_tasks   → cap.default_agents, cap.default_tools, cap.verification_strategy
    Verifier.dispatch     → task.verification_strategy = cap.verification_strategy
    Bootstrap             → registry.register_many(builtin_capabilities())
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from collections.abc import Iterable, Sequence
from typing import Any, Literal

import structlog
from pydantic import BaseModel, Field, field_validator, model_validator

from zet.domain.enums import PermissionLevel, RiskLevel, VerificationStrategy

log = structlog.get_logger(__name__)


_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
"""Capability nomi snake_case bo'lishi shart."""


IntegrationStatus = Literal[
    "REAL",
    "MOCK",
    "PARTIAL",
    "REQUIRES_API",
    "REQUIRES_AUTH",
    "REQUIRES_APPROVAL",
    "REQUIRES_EXTERNAL",
]
"""Master Spec PART 2 §"halollik qoidasi" — capability qay darajada ishlaydi."""


class CapabilityNotFoundError(Exception):
    """Registry'da bunday capability yo'q (ToolNotFoundError bilan parallel)."""


class CapabilityCycleError(Exception):
    """register()/register_many() aylanma bog'liqlik hosil qilmoqchi."""


class Capability(BaseModel):
    """Bitta yuqori darajali qobiliyatning o'zgarmas metadata yozuvi.

    NEGA: MissionEngine "Instagram post chiqar" degan maqsadni Task Graph'ga
    yoyish uchun oldindan tayyor "resept"ga muhtoj — qaysi agent, qaysi tool,
    qanday risk, qanday verification. Capability shu resept.

    Ilgari MissionEngine har safar 40+ tool imzosidan LLM'ga tanlatardi;
    bu asta va noaniq bo'lardi. Endi u avval 20 ta capability ustidan
    qidiradi (qat'iy allowlist), so'ng resolve orqali aniq tool ro'yxatiga
    yetadi.
    """

    model_config = {"frozen": True}

    name: str = Field(
        min_length=1,
        max_length=64,
        description="Unikal snake_case identifikator (masalan: 'website', 'instagram').",
    )
    description: str = Field(
        min_length=1,
        max_length=500,
        description="Capability nima qilishini bir jumlada tushuntiradi.",
    )
    supported_outcomes: list[str] = Field(
        default_factory=list,
        description="Qanday natijalarga erisha oladi (masalan: 'build_website').",
    )
    required_context_sources: list[str] = Field(
        default_factory=list,
        description="Discovery bosqichida qaysi manbalardan kontekst tortish kerak.",
    )
    actions: list[str] = Field(
        default_factory=list,
        description="Ichki actionlar (masalan: 'plan', 'design', 'deploy').",
    )
    default_agents: list[str] = Field(
        default_factory=list,
        description="AgentRegistry'da tekshiriladigan default agent nomlari.",
    )
    default_tools: list[str] = Field(
        default_factory=list,
        description="ToolRegistry'da tekshiriladigan default tool nomlari.",
    )
    permission_level: PermissionLevel = Field(
        default=PermissionLevel.READ,
        description="Eng past yetarli ruxsat darajasi.",
    )
    risk_level: RiskLevel = Field(
        default=RiskLevel.LOW,
        description="Xavf tieri — mission darajasidagi approval'ga ta'sir qiladi.",
    )
    verification_strategy: VerificationStrategy = Field(
        default=VerificationStrategy.NONE,
        description="Verifier chiqishni qanday tekshirishi (Master Spec PART 6).",
    )
    failure_strategies: list[str] = Field(
        default_factory=list,
        description="Muvaffaqiyatsiz bo'lganda nima qilish (masalan: 'rollback_deploy').",
    )
    dependencies: list[str] = Field(
        default_factory=list,
        description="Boshqa capability nomlari — DAG ota tugunlari.",
    )
    provides: list[str] = Field(
        default_factory=list,
        description="Semantik teglar — boshqa capability shularni dependencies'ga qo'shishi mumkin.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Semantik qidiruv uchun erkin teglar (masalan: 'marketing', 'devops').",
    )
    integration_status: IntegrationStatus = Field(
        default="PARTIAL",
        description="Master Spec PART 2 halollik qoidasi.",
    )
    version: int = Field(default=1, ge=1)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if not _NAME_RE.match(value):
            raise ValueError(
                f"Capability nomi snake_case bo'lishi shart (regex ^[a-z][a-z0-9_]*$): {value!r}"
            )
        return value

    @model_validator(mode="after")
    def _no_self_dep(self) -> Capability:
        if self.name in self.dependencies:
            raise ValueError(f"Capability '{self.name}' o'ziga bog'liq bo'la olmaydi")
        return self


class CapabilityResolution(BaseModel):
    """resolve() natijasi — topologik tartiblangan reja skeleti.

    NEGA: MissionEngine bir shortlist beradi (masalan ['website']); Registry
    dependencies'ni transitiv tortadi, dedup qiladi, topo-sort qiladi va
    agent/tool/permission/risk to'plamlarini bitta joyda beradi. Bu Mission
    obyekti va Task Graph'ga to'g'ridan-to'g'ri quyiladi.

    Ilgari bu logika MissionEngine ichida edi va planner uni takrorlardi;
    endi u yagona nuqtada.
    """

    model_config = {"frozen": True}

    capabilities: list[Capability] = Field(
        default_factory=list,
        description="Topo-sort qilingan (ota-ota-... o'zi) capability ro'yxati.",
    )
    agents: list[str] = Field(
        default_factory=list,
        description="Barcha default_agents birlashmasi (tartibda, dedup).",
    )
    tools: list[str] = Field(
        default_factory=list,
        description="Barcha default_tools birlashmasi (tartibda, dedup).",
    )
    required_permission: PermissionLevel = Field(
        default=PermissionLevel.READ,
        description="Kompozitsiyadagi eng yuqori permission_level.",
    )
    max_risk: RiskLevel = Field(
        default=RiskLevel.LOW,
        description="Kompozitsiyadagi eng yuqori risk_level.",
    )
    verification_strategies: list[VerificationStrategy] = Field(
        default_factory=list,
        description="Har capability uchun verification (capabilities ro'yxati bilan sinxron).",
    )
    missing_dependencies: list[str] = Field(
        default_factory=list,
        description="E'lon qilinganu, ammo ro'yxatga olinmagan dependency nomlari.",
    )


class CapabilityRegistry:
    """Capability'larni ro'yxatga olish va kompozitsiya qilish.

    Same shape as ToolRegistry / AgentRegistry — in-memory, allowlist,
    MissionEngine'ning yagona so'rov nuqtasi. Boshqa registrylarga
    bog'liq emas; Planner ularni bir joyga ulaydi.
    """

    def __init__(self) -> None:
        self._capabilities: dict[str, Capability] = {}
        self._by_outcome: dict[str, set[str]] = defaultdict(set)
        self._by_action: dict[str, set[str]] = defaultdict(set)
        self._by_tag: dict[str, set[str]] = defaultdict(set)

    # ── registration ──────────────────────────────────────────

    def register(self, cap: Capability) -> None:
        """Bitta capability'ni ro'yxatga oladi.

        Aylanma bog'liqlikni oldini oladi: agar yangi capability o'zining
        biror ajdodini dependency sifatida ko'rsatgan bo'lsa — reject.

        Raises:
            ValueError: dubl nom.
            CapabilityCycleError: dep cikli hosil bo'lardi.
        """
        if cap.name in self._capabilities:
            raise ValueError(f"Capability '{cap.name}' allaqachon ro'yxatda")

        # Ciklga tayyorlanish: yangi capability'ning dependencies ichida
        # o'zi bo'lmasligi kerak (bu allaqachon model_validator tomonidan
        # tekshirilgan), va yangi bog'liqlik cikl hosil qilmasligi kerak.
        self._capabilities[cap.name] = cap
        try:
            self._assert_no_cycle(cap.name)
        except CapabilityCycleError:
            del self._capabilities[cap.name]
            raise

        self._index(cap)

        log.info(
            "capability.registered",
            name=cap.name,
            outcomes=len(cap.supported_outcomes),
            risk=cap.risk_level.value,
            permission=cap.permission_level.value,
        )

    def register_many(self, caps: Iterable[Capability]) -> None:
        """Batch registration — birortasi yiqilsa hammasi qaytariladi (atomic).

        NEGA: bootstrap 20 ta seed'ni bir marta yuklaydi; bittasi noto'g'ri
        bo'lsa yarim-yuklangan registry ishlashi noaniq bo'lardi. Rollback
        bu holatni oldini oladi.
        """
        added: list[str] = []
        try:
            for cap in caps:
                self.register(cap)
                added.append(cap.name)
        except Exception:
            for name in reversed(added):
                self._unregister_silent(name)
            raise

    def _unregister_silent(self, name: str) -> None:
        """Rollback yordamchisi — inverted indexlardan ham tozalaydi."""
        cap = self._capabilities.pop(name, None)
        if cap is None:
            return
        for outcome in cap.supported_outcomes:
            self._by_outcome[outcome].discard(name)
            if not self._by_outcome[outcome]:
                del self._by_outcome[outcome]
        for action in cap.actions:
            self._by_action[action].discard(name)
            if not self._by_action[action]:
                del self._by_action[action]
        for tag in cap.tags:
            self._by_tag[tag].discard(name)
            if not self._by_tag[tag]:
                del self._by_tag[tag]

    def _index(self, cap: Capability) -> None:
        for outcome in cap.supported_outcomes:
            self._by_outcome[outcome].add(cap.name)
        for action in cap.actions:
            self._by_action[action].add(cap.name)
        for tag in cap.tags:
            self._by_tag[tag].add(cap.name)

    def _assert_no_cycle(self, start: str) -> None:
        """DFS orqali `start`dan boshlanadigan dep zanjirida cikl bor-yo'qligini tekshiradi.

        Faqat ro'yxatga olingan tugunlar bo'ylab yuradi — noma'lum
        dependencies cikl deb hisoblanmaydi (ular resolve() da
        missing_dependencies sifatida qaytadi).
        """
        stack: list[tuple[str, list[str]]] = [(start, [start])]
        seen: set[str] = set()
        while stack:
            node, path = stack.pop()
            cap = self._capabilities.get(node)
            if cap is None:
                continue
            for dep in cap.dependencies:
                if dep == start or dep in path:
                    raise CapabilityCycleError(
                        f"Capability '{start}' dep cikli hosil qiladi: {' → '.join([*path, dep])}"
                    )
                if dep in seen:
                    continue
                seen.add(dep)
                stack.append((dep, [*path, dep]))

    # ── lookups ──────────────────────────────────────────────

    def get(self, name: str) -> Capability:
        """Nom bo'yicha capability'ni qaytaradi.

        Raises:
            CapabilityNotFoundError: yo'q.
        """
        try:
            return self._capabilities[name]
        except KeyError as exc:
            raise CapabilityNotFoundError(f"Capability '{name}' registry'da topilmadi") from exc

    def has(self, name: str) -> bool:
        return name in self._capabilities

    def list_capabilities(
        self,
        *,
        tag: str | None = None,
        max_risk: RiskLevel | None = None,
    ) -> list[Capability]:
        """Filtrlangan ro'yxat.

        Args:
            tag: shu tegga ega bo'lganlari.
            max_risk: risk'i shu darajadan katta bo'lmaganlari.
        """
        result = list(self._capabilities.values())
        if tag is not None:
            allowed = self._by_tag.get(tag, set())
            result = [c for c in result if c.name in allowed]
        if max_risk is not None:
            result = [c for c in result if c.risk_level <= max_risk]
        return result

    def list_by_outcome(self, outcome: str) -> list[Capability]:
        names = self._by_outcome.get(outcome, set())
        return [self._capabilities[n] for n in sorted(names)]

    def list_by_action(self, action: str) -> list[Capability]:
        names = self._by_action.get(action, set())
        return [self._capabilities[n] for n in sorted(names)]

    def search(self, keywords: Sequence[str]) -> list[Capability]:
        """Kalit so'zlar bo'yicha kandidatlarni kamaytiruvchi qidiruv.

        NEGA: Master Spec PART 2 aytadi — qattiq iboralar jadvalidan
        qochish kerak. Bu search phrase-match qilmaydi, u faqat
        LLM'ga uzatilishidan oldin ro'yxatni qisqartiradi. Skor —
        capability'ning description/outcomes/tags/actions/name maydonlarida
        kalit so'z topilishlar sonining yig'indisi.
        """
        if not keywords:
            return []
        norm = [k.lower().strip() for k in keywords if k and k.strip()]
        if not norm:
            return []

        scored: list[tuple[int, Capability]] = []
        for cap in self._capabilities.values():
            haystack = " ".join(
                [
                    cap.name,
                    cap.description,
                    *cap.supported_outcomes,
                    *cap.actions,
                    *cap.tags,
                    *cap.provides,
                ]
            ).lower()
            score = sum(haystack.count(k) for k in norm)
            if score > 0:
                scored.append((score, cap))
        scored.sort(key=lambda item: (-item[0], item[1].name))
        return [cap for _, cap in scored]

    # ── composition ──────────────────────────────────────────

    def resolve(self, names: Sequence[str]) -> CapabilityResolution:
        """Shortlist bo'yicha topologik tartiblangan reja skeleti.

        NEGA: MissionEngine LLM shortlisteri ("website" + "instagram") beradi.
        Registry ularning barcha dependencies'ni tortadi, ["content", "design",
        "branding", "website", "instagram"] tartibida joylashtiradi, agent+tool
        birlashmasini yig'adi va max risk/permission'ni hisoblab beradi.

        Fail-open: noma'lum dep nomlari `missing_dependencies` ga tushadi
        (istisno emas) — Clarifier ularni owner'dan so'raydi, planner esa
        qolgan qismini davom ettira oladi.
        """
        # Dep zanjirini tortish (BFS).
        expanded: list[str] = []
        seen: set[str] = set()
        missing: list[str] = []
        missing_set: set[str] = set()
        queue: deque[str] = deque()
        for name in names:
            if name and name not in seen and name not in missing_set:
                queue.append(name)

        while queue:
            current = queue.popleft()
            if current in seen or current in missing_set:
                continue
            cap = self._capabilities.get(current)
            if cap is None:
                missing.append(current)
                missing_set.add(current)
                continue
            seen.add(current)
            expanded.append(current)
            for dep in cap.dependencies:
                if dep not in seen and dep not in missing_set:
                    queue.append(dep)

        # Topo-sort (Kahn) — faqat mavjud (seen) tugunlar ustida.
        indegree: dict[str, int] = dict.fromkeys(seen, 0)
        edges: dict[str, list[str]] = defaultdict(list)
        for name in seen:
            cap = self._capabilities[name]
            for dep in cap.dependencies:
                if dep in seen:
                    edges[dep].append(name)
                    indegree[name] += 1

        # Barqaror tartib uchun alfabetik queue.
        ready: deque[str] = deque(sorted(n for n, d in indegree.items() if d == 0))
        ordered: list[str] = []
        while ready:
            node = ready.popleft()
            ordered.append(node)
            for child in sorted(edges[node]):
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)

        if len(ordered) != len(seen):
            # `_assert_no_cycle` register()'da ushlab qolgan bo'lishi kerak,
            # bu yerga tushish invariant buzilishi — himoya.
            raise CapabilityCycleError(
                f"Topo-sort ciklga duch keldi: {sorted(seen - set(ordered))}"
            )

        capabilities = [self._capabilities[n] for n in ordered]

        # Agent va tool birlashmasi (tartibda, dedup).
        agents_seen: dict[str, None] = {}
        tools_seen: dict[str, None] = {}
        max_perm = PermissionLevel.READ
        max_risk = RiskLevel.LOW
        for cap in capabilities:
            for agent in cap.default_agents:
                agents_seen.setdefault(agent, None)
            for tool in cap.default_tools:
                tools_seen.setdefault(tool, None)
            if cap.permission_level > max_perm:
                max_perm = cap.permission_level
            if cap.risk_level > max_risk:
                max_risk = cap.risk_level

        return CapabilityResolution(
            capabilities=capabilities,
            agents=list(agents_seen.keys()),
            tools=list(tools_seen.keys()),
            required_permission=max_perm,
            max_risk=max_risk,
            verification_strategies=[c.verification_strategy for c in capabilities],
            missing_dependencies=missing,
        )

    # ── planner-facing views ─────────────────────────────────

    def signatures(self) -> list[dict[str, Any]]:
        """MissionEngine LLM shortlisteri uchun ixcham ko'rinish.

        NEGA: LLM'ga to'liq Capability yubormaslik uchun — u faqat
        (name, description, outcomes, actions, risk, agents, tools) ni
        ko'radi. Ilgari to'liq object berilganda tokenlar isrof bo'lardi.
        """
        return [
            {
                "name": cap.name,
                "description": cap.description,
                "outcomes": list(cap.supported_outcomes),
                "actions": list(cap.actions),
                "risk": cap.risk_level.value,
                "agents": list(cap.default_agents),
                "tools": list(cap.default_tools),
            }
            for cap in self._capabilities.values()
        ]

    @property
    def count(self) -> int:
        return len(self._capabilities)


# ── Seed capabilities (Master Spec PART 2) ─────────────────────


def builtin_capabilities() -> list[Capability]:
    """20 ta seed capability — MissionEngine birinchi ishga tushganda haqiqiy ma'lumot.

    NEGA: bootstrap paytida ToolRegistry seed'lari kabi shu ham yuklanadi
    — Mission ko'r-ko'rona ishlamasligi uchun (Master Spec PART 2).

    Har capability halollik qoidasiga muvofiq belgilangan
    integration_status bilan chiqadi (REAL/PARTIAL/REQUIRES_API/...).
    """
    return [
        Capability(
            name="content",
            description="Maqola, script va marketing kopiyasi tayyorlaydi.",
            supported_outcomes=["draft_article", "script_reel", "translate_copy"],
            required_context_sources=["obsidian", "web"],
            actions=["research", "outline", "write", "edit"],
            default_agents=["content", "research"],
            default_tools=["note.write", "web.search"],
            permission_level=PermissionLevel.WRITE,
            risk_level=RiskLevel.LOW,
            tags=["marketing", "writing"],
            integration_status="REAL",
        ),
        Capability(
            name="design",
            description="Vizual, layout va asset yaratadi.",
            supported_outcomes=["create_visual", "design_layout", "export_asset"],
            required_context_sources=["files"],
            actions=["moodboard", "design", "review", "export"],
            default_agents=["design"],
            default_tools=["image.generate", "note.write"],
            permission_level=PermissionLevel.WRITE,
            risk_level=RiskLevel.LOW,
            tags=["marketing", "creative"],
            integration_status="PARTIAL",
        ),
        Capability(
            name="research",
            description="Bozor, raqobat va faktlarni izlaydi va sintez qiladi.",
            supported_outcomes=["market_scan", "competitor_analysis", "source_facts"],
            required_context_sources=["web"],
            actions=["search", "synthesize", "cite"],
            default_agents=["research"],
            default_tools=["web.search", "note.write"],
            permission_level=PermissionLevel.READ,
            risk_level=RiskLevel.LOW,
            tags=["analysis"],
            integration_status="REAL",
        ),
        Capability(
            name="analytics",
            description="Trafik, KPI va anomaliyalarni o'lchaydi va hisobot beradi.",
            supported_outcomes=["measure_traffic", "report_kpis", "detect_anomaly"],
            required_context_sources=["metrics"],
            actions=["collect", "aggregate", "report"],
            default_agents=["analytics"],
            default_tools=["metrics.query", "note.write"],
            permission_level=PermissionLevel.READ,
            risk_level=RiskLevel.LOW,
            verification_strategy=VerificationStrategy.METRIC_THRESHOLD,
            tags=["analysis", "reporting"],
            integration_status="PARTIAL",
        ),
        Capability(
            name="branding",
            description="Brend palitrasi, nomlash va brand kit tayyorlaydi.",
            supported_outcomes=["build_brand_kit", "choose_palette", "name_product"],
            required_context_sources=["obsidian"],
            actions=["research", "design", "approve"],
            default_agents=["design", "strategy"],
            default_tools=["note.write", "image.generate"],
            permission_level=PermissionLevel.WRITE,
            risk_level=RiskLevel.LOW,
            provides=["brand_kit"],
            tags=["marketing", "creative"],
            integration_status="PARTIAL",
        ),
        Capability(
            name="business",
            description="Biznes plan, pozitsiyalash va taklif tanlashda yordam beradi.",
            supported_outcomes=["draft_business_plan", "define_positioning", "choose_offer"],
            required_context_sources=["obsidian", "web"],
            actions=["analyze", "plan", "decide"],
            default_agents=["ceo", "research", "strategy"],
            default_tools=["note.write", "web.search"],
            permission_level=PermissionLevel.WRITE,
            risk_level=RiskLevel.LOW,
            tags=["strategy"],
            integration_status="PARTIAL",
        ),
        Capability(
            name="website",
            description="Web sayt qurish, audit qilish va landing yangilash.",
            supported_outcomes=["build_website", "audit_site", "update_landing"],
            required_context_sources=["github", "files"],
            actions=["plan", "design", "develop", "deploy"],
            default_agents=["developer", "qa", "deployer"],
            default_tools=["github.write", "deploy.push"],
            permission_level=PermissionLevel.WRITE,
            risk_level=RiskLevel.MEDIUM,
            verification_strategy=VerificationStrategy.HTTP_CHECK,
            dependencies=["branding", "content"],
            tags=["devops", "marketing"],
            integration_status="PARTIAL",
        ),
        Capability(
            name="instagram",
            description="Instagram uchun post/scheduling/reach analitikasi.",
            supported_outcomes=[
                "publish_post",
                "schedule_content",
                "grow_audience",
                "analyze_reach",
            ],
            required_context_sources=["files", "calendar"],
            actions=["research", "design", "write", "publish", "analyze"],
            default_agents=["smm", "content", "design", "analytics"],
            default_tools=["instagram.publish", "image.generate", "note.write"],
            permission_level=PermissionLevel.WRITE,
            risk_level=RiskLevel.MEDIUM,
            verification_strategy=VerificationStrategy.API_ECHO,
            dependencies=["content", "design"],
            tags=["marketing", "social"],
            integration_status="REQUIRES_API",
        ),
        Capability(
            name="telegram",
            description="Telegram bo'ylab xabar yuborish, kanal broadcast, DM javob.",
            supported_outcomes=["send_message", "broadcast_channel", "respond_dm"],
            required_context_sources=["obsidian"],
            actions=["draft", "send", "reply"],
            default_agents=["communication"],
            default_tools=["telegram.send"],
            permission_level=PermissionLevel.WRITE,
            risk_level=RiskLevel.MEDIUM,
            verification_strategy=VerificationStrategy.API_ECHO,
            tags=["communication", "social"],
            integration_status="REQUIRES_API",
        ),
        Capability(
            name="sales",
            description="Sales funnel, pitch va lead follow-up.",
            supported_outcomes=["build_funnel", "write_pitch", "follow_up_leads"],
            required_context_sources=["obsidian"],
            actions=["plan", "write", "reach_out", "track"],
            default_agents=["sales", "content", "analytics"],
            default_tools=["note.write", "email.send", "crm.upsert"],
            permission_level=PermissionLevel.WRITE,
            risk_level=RiskLevel.MEDIUM,
            tags=["sales"],
            integration_status="PARTIAL",
        ),
        Capability(
            name="automation",
            description="Workflow, cron va trigger zanjirlarini quradi.",
            supported_outcomes=["build_workflow", "schedule_job", "chain_triggers"],
            required_context_sources=["github"],
            actions=["design", "wire", "test", "monitor"],
            default_agents=["automation", "developer"],
            default_tools=["cron.create", "webhook.register", "github.write"],
            permission_level=PermissionLevel.WRITE,
            risk_level=RiskLevel.MEDIUM,
            tags=["devops"],
            integration_status="PARTIAL",
        ),
        Capability(
            name="smm",
            description="Content calendar, cross-post va engagement hisoboti.",
            supported_outcomes=["plan_content_calendar", "cross_post", "engagement_report"],
            required_context_sources=["calendar"],
            actions=["plan", "publish", "respond", "measure"],
            default_agents=["smm", "content", "analytics"],
            default_tools=["instagram.publish", "telegram.send", "metrics.query"],
            permission_level=PermissionLevel.WRITE,
            risk_level=RiskLevel.MEDIUM,
            dependencies=["content", "analytics"],
            tags=["marketing", "social"],
            integration_status="PARTIAL",
        ),
        Capability(
            name="camera",
            description="Kamera snapshot, oqim ko'rinishi va hodisa detektsiyasi.",
            supported_outcomes=["snapshot", "stream_view", "event_detect"],
            required_context_sources=["camera"],
            actions=["query", "subscribe", "analyze"],
            default_agents=["vision"],
            default_tools=["camera.snapshot", "vision.analyze"],
            permission_level=PermissionLevel.READ,
            risk_level=RiskLevel.MEDIUM,
            verification_strategy=VerificationStrategy.VISUAL_DIFF,
            tags=["vision", "iot"],
            integration_status="REQUIRES_EXTERNAL",
        ),
        Capability(
            name="computer",
            description="Local shell, fs va screen kontrol.",
            supported_outcomes=["run_command", "move_file", "screenshot"],
            required_context_sources=["files"],
            actions=["shell", "fs", "screen"],
            default_agents=["computer"],
            default_tools=["shell.run", "fs.write", "screen.capture"],
            permission_level=PermissionLevel.EXECUTE,
            risk_level=RiskLevel.HIGH,
            verification_strategy=VerificationStrategy.LOG_INSPECTION,
            tags=["devops", "system"],
            integration_status="PARTIAL",
        ),
        Capability(
            name="deployment",
            description="Service deploy, rollback va release promotsiyasi.",
            supported_outcomes=["deploy_service", "rollback", "promote_release"],
            required_context_sources=["github"],
            actions=["build", "deploy", "verify", "rollback"],
            default_agents=["deployer", "qa"],
            default_tools=["deploy.push", "deploy.rollback"],
            permission_level=PermissionLevel.EXECUTE,
            risk_level=RiskLevel.HIGH,
            verification_strategy=VerificationStrategy.HTTP_CHECK,
            failure_strategies=["rollback_deploy", "notify_owner"],
            tags=["devops"],
            integration_status="PARTIAL",
        ),
        Capability(
            name="github",
            description="GitHub'da PR ochish, fix commit va issue triage.",
            supported_outcomes=["open_pr", "commit_fix", "triage_issues"],
            required_context_sources=["github"],
            actions=["clone", "edit", "commit", "pr"],
            default_agents=["developer", "qa"],
            default_tools=["github.read", "github.write"],
            permission_level=PermissionLevel.WRITE,
            risk_level=RiskLevel.MEDIUM,
            verification_strategy=VerificationStrategy.TEST_SUITE,
            tags=["devops"],
            integration_status="REAL",
        ),
        Capability(
            name="obsidian",
            description="Obsidian vault: not yozish, bog'lash, so'rov.",
            supported_outcomes=["capture_note", "link_thoughts", "query_vault"],
            required_context_sources=["obsidian"],
            actions=["read", "write", "link"],
            default_agents=["knowledge"],
            default_tools=["note.read", "note.write"],
            permission_level=PermissionLevel.WRITE,
            risk_level=RiskLevel.LOW,
            tags=["knowledge"],
            integration_status="REAL",
        ),
        Capability(
            name="security",
            description="Secret scan, ruxsat auditi va config qattiqlash.",
            supported_outcomes=["scan_secrets", "review_permissions", "harden_config"],
            required_context_sources=["github"],
            actions=["scan", "recommend", "apply"],
            default_agents=["security"],
            default_tools=["security.scan", "github.write"],
            permission_level=PermissionLevel.WRITE,
            risk_level=RiskLevel.HIGH,
            verification_strategy=VerificationStrategy.TEST_SUITE,
            tags=["security", "devops"],
            integration_status="PARTIAL",
        ),
        Capability(
            name="finance",
            description="Xarajat, forecast va invoice ish jarayonlari.",
            supported_outcomes=["record_expense", "forecast", "invoice"],
            required_context_sources=["files"],
            actions=["record", "project", "report"],
            default_agents=["finance"],
            default_tools=["ledger.write", "note.write"],
            permission_level=PermissionLevel.WRITE,
            risk_level=RiskLevel.MEDIUM,
            verification_strategy=VerificationStrategy.HUMAN_REVIEW,
            tags=["finance"],
            integration_status="PARTIAL",
        ),
        Capability(
            name="communication",
            description="Email, telegram xabar va thread umumlashtirish.",
            supported_outcomes=["send_email", "summarize_thread", "schedule_message"],
            required_context_sources=["obsidian"],
            actions=["draft", "send", "summarize"],
            default_agents=["communication"],
            default_tools=["email.send", "telegram.send", "note.write"],
            permission_level=PermissionLevel.WRITE,
            risk_level=RiskLevel.LOW,
            tags=["communication"],
            integration_status="PARTIAL",
        ),
    ]


__all__ = [
    "Capability",
    "CapabilityCycleError",
    "CapabilityNotFoundError",
    "CapabilityRegistry",
    "CapabilityResolution",
    "IntegrationStatus",
    "builtin_capabilities",
]
