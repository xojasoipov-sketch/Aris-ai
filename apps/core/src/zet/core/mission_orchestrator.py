"""MissionOrchestrator — 6 ta yangi qatlamni bitta joyda birlashtiruvchi.

NEGA bu qatlam kerak. `MissionEngine` (§2.2) allaqachon fazalar bo'yicha
oqim (understand → discover → plan → execute → verify → recover) beradi.
Lekin haqiqiy hayotda uni ishga tushirish uchun boshqa qismlar ham
kerak — kill-switch tekshiruvi, capability preflight, notifier orqali
egaga xabar, va tashqaridan (API/CLI) uni qanday chaqirish.

`MissionOrchestrator` shu yopqichni yopadi: bitta `Command` qabul qiladi,
`Mission`ni yaratadi, kill-switch va capability preflight'ni bajaradi,
`MissionEngine`ni oxirigacha aylantiradi va yakuniy holat bo'yicha egaga
`Notifier` orqali xabar yuboradi.

Bog'liq qismlar:
    CapabilityRegistry  — bundle preflight (bo'sh natija = FAILED)
    ContextEngine       — MissionEngine ichida ishlatiladi
    MissionEngine       — asosiy fazalar driver'i
    Planner/Executor/Verifier — MissionEngine tarkibida (mavjud
        Orchestrator qatlami orqali)
    RecoveryEngine      — MissionEngine tarkibida
    ApprovalService     — MissionEngine tarkibida (HIGH → WAITING_APPROVAL)
    PermissionPolicy    — capability approval'ini oshiradi
    Notifier            — yakuniy holat bo'yicha egaga xabar

Bog'liq qarorlar:
    A-01 — davomli holat mashinasi
    V-32 — majburiy tasdiq (RiskLevel + WAITING_APPROVAL)
    V-33 — favqulodda to'xtatish (kill-switch)
    V-17 — natija egaga yetkaziladi (Notifier)
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

import structlog

from zet.core.mission import (
    Mission,
    MissionEngine,
    MissionNotFoundError,
)
from zet.domain.command import Command
from zet.domain.enums import MissionStatus, PermissionLevel, RiskLevel

if TYPE_CHECKING:
    from zet.core.capability import CapabilityRegistry
    from zet.core.context import ContextEngine
    from zet.core.executor import Executor
    from zet.core.planner import Planner
    from zet.core.recovery import RecoveryEngine
    from zet.core.verifier import Verifier
    from zet.security.approvals import ApprovalService
    from zet.security.killswitch import KillSwitchState
    from zet.security.permissions import PermissionPolicy
    from zet.telegram.notifier import Notifier


log = structlog.get_logger(__name__)


class MissionOrchestratorError(Exception):
    """MissionOrchestrator darajasidagi umumiy xato."""


class _CapabilityRegistryLike(Protocol):
    """MissionEngine bilan bir xil compose interfeysi (preflight uchun)."""

    def compose(
        self, objective: str, context: dict[str, Any]
    ) -> Any:  # pragma: no cover — protocol
        ...


class MissionOrchestrator:
    """6 ta yangi qatlamni bitta `run(command)` orqasida birlashtiradi.

    Butun ish MissionEngine.run_to_completion() ga topshiriladi —
    MissionOrchestrator faqat quyidagi qo'shimchalarni beradi:

    * kill-switch preflight — engaged bo'lsa mission darhol CANCELLED
      va execute chaqirilmaydi (MissionEngine ichida bu FAILED bo'lardi,
      bu yerda esa "ega bekor qildi" degan aniqroq status);
    * capability preflight — CapabilityRegistry.compose() umuman tool
      qaytarmasa mission darhol FAILED (xato yozuvi bilan), execute
      chaqirilmaydi;
    * yakuniy notifier — terminal holatga yetganda egaga xabar yuboriladi
      (V-17).

    Qolgan qismlar (planner, executor, verifier, recovery, approvals,
    permission_policy) MissionEngine tarkibida yashaydi va u orqali
    ishlaydi.

    Notifier istisnolari yutiladi — xabar yubora olmaslik mission
    natijasini o'zgartirmasligi kerak (V-17 fail-open).
    """

    def __init__(
        self,
        *,
        capability_registry: _CapabilityRegistryLike | CapabilityRegistry,
        context_engine: ContextEngine | Any,
        mission_engine: MissionEngine,
        planner: Planner | Any,
        executor: Executor | Any,
        verifier: Verifier | Any,
        recovery_engine: RecoveryEngine | Any,
        approval_service: ApprovalService,
        permission_policy: PermissionPolicy,
        notifier: Notifier,
        killswitch: KillSwitchState | None = None,
    ) -> None:
        self._capabilities = capability_registry
        self._context_engine = context_engine
        self._mission_engine = mission_engine
        self._planner = planner
        self._executor = executor
        self._verifier = verifier
        self._recovery = recovery_engine
        self._approvals = approval_service
        self._permissions = permission_policy
        self._notifier = notifier
        self._killswitch = killswitch

    @property
    def owner_id(self) -> uuid.UUID:
        """MissionEngine repository qaysi egaga bog'langan."""
        return self._mission_engine.repository.owner_id

    # ── Asosiy oqim ──────────────────────────────────────────────

    async def run(self, command: Command, *, owner_id: uuid.UUID) -> Mission:
        """Buyruqni oxirigacha aylantiradi va yakuniy Mission qaytaradi.

        Bosqichlar (Master Spec §2.2 fazalari):
            1. Mission yaratish (RECEIVED)
            2. Intent aniqlash — MissionEngine.understand()
            3. Kontekst topish — MissionEngine.discover()
            4. Capability tanlash + reja — MissionEngine.plan()
            5. Approval tekshiruvi — HIGH_RISK bo'lsa WAITING_APPROVAL
            6. Bajarish — MissionEngine.execute()
            7. Tekshirish — MissionEngine.verify()
            8. Yiqilsa qayta urinish — MissionEngine.recover() → 6
            9. Yakunlash — memory_updates yozish + Notifier

        `owner_id` — Command uchun tegishli ega; `Command` modeli o'zi
        `owner_id` maydonini tutmaydi (chunki u kanal darajasida
        aniqlanadi), shu sabab bu yerga alohida uzatiladi.
        """
        mission = await self._mission_engine.submit(
            owner_id=owner_id,
            objective=command.text,
        )
        log.info("mission_orchestrator.received", mission_id=str(mission.id))

        # 1. Kill-switch preflight — V-33.
        if self._is_killed():
            reason = self._killswitch_reason()
            mission = await self._mission_engine.cancel(mission.id, reason)
            log.warning(
                "mission_orchestrator.killswitch_engaged",
                mission_id=str(mission.id),
                reason=reason,
            )
            await self._notify_terminal(mission)
            return mission

        # 2. Capability preflight — bo'sh natija = FAILED.
        try:
            bundle = self._capabilities.compose(command.text, {})
        except Exception as exc:
            mission = await self._fail(mission, f"capability compose failed: {exc}")
            log.warning(
                "mission_orchestrator.capability_compose_failed",
                mission_id=str(mission.id),
                error=str(exc),
            )
            await self._notify_terminal(mission)
            return mission

        if not self._bundle_has_content(bundle):
            mission = await self._fail(
                mission,
                f"no capability matched objective: {command.text!r}",
            )
            log.warning(
                "mission_orchestrator.no_capability_match",
                mission_id=str(mission.id),
                objective=command.text,
            )
            await self._notify_terminal(mission)
            return mission

        # 3. MissionEngine ga topshiramiz — o'zi phase'lar bo'yicha aylanadi.
        try:
            mission = await self._mission_engine.run_to_completion(mission.id)
        except Exception as exc:
            log.exception(
                "mission_orchestrator.driver_failed",
                mission_id=str(mission.id),
            )
            mission = await self._fail(mission, f"driver failed: {exc}")

        await self._notify_terminal(mission)
        return mission

    # ── Read/List ─────────────────────────────────────────────────

    async def get(self, mission_id: uuid.UUID) -> Mission:
        """Bitta missionni id bo'yicha o'qib qaytaradi (owner-scoped)."""
        return await self._mission_engine.repository.get(mission_id)

    async def list_recent(
        self,
        *,
        limit: int = 25,
        offset: int = 0,
        status: MissionStatus | None = None,
    ) -> Sequence[Mission]:
        """Yaqinda yaratilgan missionlar — priority DESC → created_at DESC.

        Sahifalash `offset`/`limit` orqali; repository darajasida
        `limit` mavjud, `offset` esa bu yerda ro'yxatni kesish orqali
        qo'llaniladi (SQL LIMIT/OFFSET emas — natija hajmi kichik va
        `owner_id` scoping baribir mavjud).
        """
        # Repository `limit` argumentini oladi, `offset` bermaydi;
        # shuning uchun `limit + offset` ta yozuv olib, `offset`dan
        # kesamiz. Kelajakda ko'p mission bo'lsa `offset` repository'ga
        # ham qo'shiladi (o'shanda bu yer o'zgaradi).
        all_rows = await self._mission_engine.repository.list(
            status=status,
            limit=max(limit + offset, 1),
        )
        return list(all_rows)[offset : offset + limit]

    # ── Ichki yordamchi'lar ───────────────────────────────────────

    def _is_killed(self) -> bool:
        return self._killswitch is not None and self._killswitch.is_engaged

    def _killswitch_reason(self) -> str:
        base = "kill switch engaged"
        if self._killswitch is None:
            return base
        detail = self._killswitch.reason if hasattr(self._killswitch, "reason") else None
        return f"{base}: {detail}" if detail else base

    @staticmethod
    def _bundle_has_content(bundle: Any) -> bool:
        """Bundle'da ishga oshirish uchun biror tool/agent/capability bormi?

        NEGA barchasi tekshiriladi: kelajakda ba'zi bundle'lar faqat
        capability nomlarini qaytarishi mumkin (tool ro'yxati Planner
        tomonidan aniqlanadi). Bu yerda "hech narsa yo'q" degan yagona
        holat FAILED sabab bo'ladi.
        """
        for attr in ("tools", "agents", "capabilities"):
            values = getattr(bundle, attr, None)
            if values:
                return True
        return False

    async def _fail(self, mission: Mission, reason: str) -> Mission:
        """Mission'ni FAILED holatiga o'tkazadi (owner-scoped set_status)."""
        return await self._mission_engine.repository.set_status(
            mission.id, MissionStatus.FAILED, error=reason
        )

    async def _notify_terminal(self, mission: Mission) -> None:
        """Terminal holatda egaga xabar — fail-open (yutilgan istisno)."""
        if not mission.status.is_terminal:
            return
        try:
            summary = _format_summary(mission)
            await self._notifier.send_task_result(summary, run_id=str(mission.id))
        except Exception:
            log.warning(
                "mission_orchestrator.notify_failed",
                mission_id=str(mission.id),
                status=mission.status.value,
            )


def _format_summary(mission: Mission) -> str:
    """Egaga yuboriladigan qisqa hisobot matni.

    Formatga alohida test yozilmaydi (bir jumlalik hisobot) — muhimi
    holat va objective ega ko'radigan shaklga tushirilishi.
    """
    header = {
        MissionStatus.COMPLETED: "Mission bajarildi",
        MissionStatus.FAILED: "Mission yiqildi",
        MissionStatus.CANCELLED: "Mission bekor qilindi",
    }.get(mission.status, f"Mission holati: {mission.status.value}")
    body = f"Maqsad: {mission.objective}"
    if mission.error:
        body = f"{body}\nSabab: {mission.error}"
    return f"{header}\n{body}"


# ── Adapter'lar (deps.py wiring uchun) ───────────────────────────
#
# Ilgari mavjud CapabilityRegistry va ContextEngine imzolari MissionEngine
# protokoli bilan aynan mos kelmasdi — CapabilityRegistry `resolve(names)`
# beradi (compose emas), ContextEngine esa `discover(UserRequest)` (o'zi
# ichida owner_id/text bo'lgan obyekt). Bu yerdagi adapter'lar mavjud
# imzolarni MissionEngine kutayotgan shakliga yopishtiradi — o'zgartirmasdan.


@dataclass
class CapabilityBundle:
    """MissionEngine `CapabilityBundleLike` protokoliga mos oddiy bundle."""

    capabilities: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    permissions_required: list[PermissionLevel] = field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW


class CapabilityRegistryComposer:
    """`CapabilityRegistry` ustidan `compose(objective, context)` beradi.

    Objective'dan kalit so'zlar ajratib olib `search()` orqali nomzod
    capability'larni topadi, so'ng `resolve()` bilan topologik tartibga
    keltiradi. Hech nima topilmasa — bo'sh bundle qaytadi va
    MissionOrchestrator preflight uni FAILED holatiga o'tkazadi.
    """

    def __init__(self, registry: Any, *, top_k: int = 5) -> None:
        self._registry = registry
        self._top_k = top_k

    def compose(self, objective: str, context: dict[str, Any]) -> CapabilityBundle:
        del context  # kelajakda contextdan qo'shimcha tanlash uchun
        keywords = [w for w in objective.lower().split() if len(w) >= 3]
        if not keywords:
            return CapabilityBundle()
        matches = self._registry.search(keywords)
        if not matches:
            return CapabilityBundle()
        selected = [c.name for c in matches[: self._top_k]]
        resolution = self._registry.resolve(selected)
        return CapabilityBundle(
            capabilities=[c.name for c in resolution.capabilities],
            agents=list(resolution.agents),
            tools=list(resolution.tools),
            permissions_required=[resolution.required_permission],
            risk_level=resolution.max_risk,
        )


class _RelevantContextView:
    """`RelevantContext` uchun `to_dict()` bergan yengil ko'rinish."""

    def __init__(self, ctx: Any) -> None:
        self._ctx = ctx

    def to_dict(self) -> dict[str, Any]:
        try:
            return {
                "fragments": [
                    {"source": f.source.value, "content": f.content}
                    for f in getattr(self._ctx, "fragments", ())
                ],
                "total_tokens": getattr(self._ctx, "total_tokens", 0),
                "truncated": getattr(self._ctx, "truncated", False),
            }
        except Exception:
            return {}


class ContextEngineAdapter:
    """`ContextEngine.discover(UserRequest)` → MissionEngine imzosi.

    MissionEngine `discover(objective, *, owner_id, constraints)` chaqiradi;
    haqiqiy ContextEngine esa `discover(UserRequest)` kutadi. Bu adapter
    UserRequest'ni to'ldirib chaqiradi va natijani `to_dict()`ga ega
    ko'rinishga o'raydi.
    """

    def __init__(self, engine: Any) -> None:
        self._engine = engine

    async def discover(
        self, objective: str, *, owner_id: uuid.UUID, constraints: list[str]
    ) -> _RelevantContextView:
        # Local import — Bo'lim 4 modullariga aylanma bog'lanmaslik uchun.
        from zet.core.context import UserRequest

        del constraints  # ContextEngine constraint'ni to'g'ridan-to'g'ri ishlatmaydi
        request = UserRequest(
            request_id=uuid.uuid4().hex,
            owner_id=owner_id,
            text=objective,
        )
        ctx = await self._engine.discover(request)
        return _RelevantContextView(ctx)


__all__ = [
    "CapabilityBundle",
    "CapabilityRegistryComposer",
    "ContextEngineAdapter",
    "MissionNotFoundError",
    "MissionOrchestrator",
    "MissionOrchestratorError",
]
