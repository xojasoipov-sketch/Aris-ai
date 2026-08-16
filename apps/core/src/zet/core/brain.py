"""Brain — barcha kanallar uchun YAGONA kirish va marshrutlash qatlami (JB-2).

MUAMMO (audit topilmasi #1 va #2, kod bilan tasdiqlangan):

Tizimda ikkita miya bor edi, lekin faqat kichigi ulangan edi.

    * `Orchestrator` (Run pipeline'i: intent → reja → bajarish → tekshirish
      → recovery) — Telegram, web, CLI, hammasi shu yerga borardi;
    * `MissionEngine`/`MissionOrchestrator` (uzoq muddatli, DB'da
      saqlanadigan, qayta urinadigan, xotiraga yozadigan Mission qatlami)
      — faqat `POST /api/v1/missions` REST endpoint'idan yetsa bo'lardi.
      Telegram kodida "mission" so'zi 0 marta, `apps/web`da 0 marta.

Va hech bir kanal xabarni "oddiy savol" va "ko'p qadamli maqsad" deb
AJRATMASDI — `Intent`da so'rov TURI umuman yo'q edi. Natijada "biznesimni
tekshir va nimaga e'tibor berishim kerakligini ayt" degan maqsad ham
bitta bir martalik Run bo'lib tugardi.

YECHIM: bu modul. Brain LLM EMAS — u LLM atrofidagi nazorat qatlami:

    1. `IntentRecognizer` bir marta chaqiriladi (triaj: chat/command/goal)
    2. `goal` bo'lsa → Mission yo'li (saqlanadi, qayta urinadi, xotiraga
       yozadi)
    3. Aks holda → mavjud Run yo'li, AYNAN o'sha intent qayta
       ishlatilgan holda (ikkinchi LLM chaqiruvi yo'q)

XAVFSIZLIK VA REGRESSIYA KAFOLATI: Mission yo'li Run yo'lidan qat'iyroq —
`MissionOrchestrator` capability preflight qiladi va hech qanday
capability mos kelmasa mission'ni FAILED qiladi. Bu oddiy savolga
"yiqildi" javobini qaytarishi mumkin edi. Shu sabab Brain'da ORQAGA
QAYTISH bor: mission hech qanday run boshlamasdan yiqilsa, so'rov
odatdagi Run yo'lidan qayta yuritiladi. Ya'ni JB-2 hech qachon
mavjud xatti-harakatdan YOMONROQ natija bera olmaydi.

Bog'liq qarorlar:
    JB-2 — goal→mission triaj (JARVIS Brain auditi)
    A-01 — mission holat mashinasi
    V-29 — task_class model marshrutlash (BU BOSHQA narsa: task_class
           modelni tanlaydi, request_kind esa ish YURITISH usulini)
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

import structlog

from zet.core.intent import AmbiguousCommandError, IntentError, IntentRecognizer
from zet.core.mission import Mission
from zet.domain.command import Command, Intent
from zet.domain.enums import MissionStatus, RunStatus
from zet.llm.base import LLMError

log = structlog.get_logger(__name__)


class BrainRoute(StrEnum):
    """Brain so'rovni qaysi yo'lga yuborgani — kuzatuv/diagnostika uchun."""

    RUN = "run"
    """Odatdagi Run pipeline'i (chat/command)."""

    MISSION = "mission"
    """Mission qatlami (goal) — saqlanadi, qayta urinadi, xotiraga yozadi."""

    MISSION_FALLBACK = "mission_fallback"
    """Goal deb tanildi, lekin mission boshlanmadi — Run yo'liga qaytdi."""


@dataclass(frozen=True)
class BrainResult:
    """Brain qaytaradigan yagona natija — kanal shundan javob yasaydi."""

    text: str
    """Egaga ko'rsatiladigan javob matni."""

    ok: bool
    """Muvaffaqiyatli tugadimi (xato/bekor qilingan bo'lsa False)."""

    route: BrainRoute
    """Qaysi yo'ldan ketdi."""

    run_id: str | None = None
    """Bog'liq run (bo'lsa) — approval tugmalari shu ID bilan ishlaydi."""

    mission_id: str | None = None
    """Bog'liq mission (goal yo'lida)."""

    request_kind: str = "command"
    """Triaj natijasi: chat/command/goal."""

    run: object | None = None
    """Bog'liq `RunRecord` (bo'lsa) — HTTP javobi qadam/xarajat/approval
    maydonlarini shundan oladi. `object` tipi ataylab: `core.brain`
    `RunRecord`ning to'liq tipiga bog'lanmasligi kerak (protokol yetarli)."""

    mission: Mission | None = None
    """Bog'liq Mission (goal yo'lida) — chaqiruvchi holatni ko'rsatishi uchun."""


class _RunLike(Protocol):
    """`RunRecord`ning Brain ishlatadigan qismi (test fake'lari uchun ham)."""

    run_id: uuid.UUID
    status: RunStatus
    result_summary: str | None
    error: str | None


class _OrchestratorLike(Protocol):
    """`Orchestrator`ning Brain ishlatadigan qismi."""

    async def start(  # pragma: no cover — protocol
        self,
        command: Command,
        *,
        dry_run: bool = False,
        intent: Intent | None = None,
    ) -> _RunLike: ...


MissionRunner = Callable[[Command], Awaitable[Mission]]
"""Mission yo'li — `MissionOrchestrator.run(command, owner_id=...)` o'ramasi."""

RunLookup = Callable[[uuid.UUID], _RunLike]
"""Run yozuvini id bo'yicha o'qish (`Orchestrator.get`) — mission javobi uchun."""


class Brain:
    """So'rovni tushunadi va TO'G'RI yo'lga yuboradi.

    Bu klass LLM emas: u faqat triaj qiladi va mavjud ikki dvigateldan
    birini tanlaydi. Hech qanday reja tuzmaydi, hech qanday tool
    chaqirmaydi — bularning hammasi Orchestrator/MissionEngine ichida,
    o'z xavfsizlik darvozalari bilan qoladi.
    """

    def __init__(
        self,
        *,
        orchestrator: _OrchestratorLike,
        intent_recognizer: IntentRecognizer,
        tool_names: Sequence[str] = (),
        mission_runner: MissionRunner | None = None,
        run_lookup: RunLookup | None = None,
        goal_missions_enabled: bool = True,
    ) -> None:
        """
        Args:
            orchestrator: Run pipeline'i (majburiy — asosiy yo'l).
            intent_recognizer: triaj uchun.
            tool_names: intent'ga hint sifatida beriladigan tool nomlari.
            mission_runner: Mission yo'li. `None` bo'lsa goal marshrutlash
                O'CHIQ — hamma narsa Run yo'lidan ketadi (eski xatti-harakat).
            run_lookup: mission bog'lagan run'ning natijasini o'qish uchun.
                Berilmasa mission javobi qisqa holat matni bo'ladi.
            goal_missions_enabled: ega sozlamasi (`ZET_BRAIN_GOAL_MISSIONS`).
        """
        self._orchestrator = orchestrator
        self._intent = intent_recognizer
        self._tool_names = list(tool_names)
        self._mission_runner = mission_runner
        self._run_lookup = run_lookup
        self._goal_missions_enabled = goal_missions_enabled

    @property
    def _mission_path_available(self) -> bool:
        return self._mission_runner is not None and self._goal_missions_enabled

    async def handle(self, command: Command, *, dry_run: bool = False) -> BrainResult:
        """So'rovni triaj qilib tegishli dvigatelga yuboradi.

        Fail-open falsafasi: triajning O'ZI hech qachon so'rovni yiqitmaydi.
        Intent aniqlanmasa yoki noaniq bo'lsa — so'rov odatdagi Run
        yo'liga tushadi, u yerda bu holatlar allaqachon to'g'ri (aniqlashtiruvchi
        savol / xato yozuvi bilan) qayta ishlanadi.
        """
        # Mission yo'li umuman yo'q bo'lsa — triajga LLM sarflashning
        # ma'nosi yo'q, natija baribir bitta.
        if not self._mission_path_available or dry_run:
            record = await self._orchestrator.start(command, dry_run=dry_run)
            return _from_run(record, BrainRoute.RUN, request_kind="command")

        try:
            intent = await self._intent.recognize(
                command,
                available_tools=self._tool_names,
            )
        except (AmbiguousCommandError, IntentError, LLMError) as exc:
            # Bu holatlarni Orchestrator O'ZI to'g'ri qayta ishlaydi
            # (aniqlashtiruvchi savolni RunRecord.error'ga yozadi) —
            # bu yerda nusxa mantiq yozmaymiz, shunchaki uzatamiz.
            log.info("brain.triage_skipped", reason=type(exc).__name__)
            record = await self._orchestrator.start(command, dry_run=dry_run)
            return _from_run(record, BrainRoute.RUN, request_kind="command")

        log.info(
            "brain.triaged",
            request_kind=intent.request_kind,
            action=intent.action,
            channel=command.channel,
        )

        if intent.request_kind != "goal":
            record = await self._orchestrator.start(command, intent=intent)
            return _from_run(record, BrainRoute.RUN, request_kind=intent.request_kind)

        return await self._handle_goal(command, intent)

    async def _handle_goal(self, command: Command, intent: Intent) -> BrainResult:
        """Goal → Mission, boshlanmasa Run yo'liga qaytish."""
        runner = self._mission_runner
        if runner is None:  # pragma: no cover — `_mission_path_available` kafolatlaydi
            record = await self._orchestrator.start(command, intent=intent)
            return _from_run(record, BrainRoute.RUN, request_kind="goal")

        try:
            mission = await runner(command)
        except Exception:
            # Mission qatlamining kutilmagan yiqilishi ega uchun
            # "hech qanday javob yo'q" bo'lib qolmasin.
            log.exception("brain.mission_runner_failed", channel=command.channel)
            record = await self._orchestrator.start(command, intent=intent)
            return _from_run(record, BrainRoute.MISSION_FALLBACK, request_kind="goal")

        # ORQAGA QAYTISH SHARTI: mission birorta ham run boshlamasdan
        # yiqilgan (masalan capability preflight mos kelmadi). Bunday
        # holatda ega "Mission yiqildi" degan foydasiz javob olardi —
        # holbuki eski xatti-harakat oddiy javob berardi.
        if mission.status == MissionStatus.FAILED and not mission.run_ids:
            log.info(
                "brain.mission_fallback",
                mission_id=str(mission.id),
                error=mission.error,
            )
            record = await self._orchestrator.start(command, intent=intent)
            return _from_run(record, BrainRoute.MISSION_FALLBACK, request_kind="goal")

        return BrainResult(
            text=self._mission_text(mission),
            ok=mission.status == MissionStatus.COMPLETED,
            route=BrainRoute.MISSION,
            run_id=(str(mission.run_ids[-1]) if mission.run_ids else None),
            mission_id=str(mission.id),
            request_kind="goal",
            run=self._last_run(mission),
            mission=mission,
        )

    def _last_run(self, mission: Mission) -> object | None:
        """Mission bog'lagan oxirgi run yozuvi (topilmasa None)."""
        if self._run_lookup is None or not mission.run_ids:
            return None
        try:
            return self._run_lookup(mission.run_ids[-1])
        except Exception:
            return None

    def _mission_text(self, mission: Mission) -> str:
        """Mission natijasini ega o'qiydigan matnga aylantiradi.

        Asosiy manba — mission bog'lagan OXIRGI run'ning javobi: mission
        modelining o'zi javob matnini saqlamaydi (u holat mashinasi),
        haqiqiy javob run yozuvida yotadi. Run o'qilmasa — holat matni.
        """
        record = self._last_run(mission)
        answer = (getattr(record, "result_summary", None) or "").strip() if record else ""

        if answer:
            return answer

        if mission.status == MissionStatus.WAITING_APPROVAL:
            return f"Tasdiq kutilmoqda: {mission.objective}"
        if mission.error:
            return f"Bajarilmadi: {mission.error}"
        return f"Holat: {mission.status.value} — {mission.objective}"


def _from_run(record: _RunLike, route: BrainRoute, *, request_kind: str) -> BrainResult:
    """`RunRecord` → `BrainResult` (kanallar uchun yagona shakl)."""
    text = record.result_summary or record.error or "(bo'sh natija)"
    return BrainResult(
        text=text,
        ok=record.error is None,
        route=route,
        run_id=str(record.run_id),
        request_kind=request_kind,
        run=record,
    )


__all__ = ["Brain", "BrainResult", "BrainRoute", "MissionRunner", "RunLookup"]
