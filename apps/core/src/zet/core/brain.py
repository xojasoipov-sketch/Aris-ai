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

JB-8 QO'SHIMCHASI — ijro rejimi ("Workflow har doim yoqilgan emas"):
`request_kind == "goal"` allaqachon Mission yo'liga yuboradi (yuqorida),
lekin Mission — "workflow" so'zi bilan chalkashtirilishi mumkin edi.
`core.execution_mode.ExecutionModeClassifier` (ixtiyoriy, berilmasa
Brain o'zgarmaydi) buyruq matnidan aniq workflow-signallarni ("workflow
qilib qo'y", "har kuni...", "workflowni to'xtat") ajratadi va
`BrainResult.execution_mode`/`execution_reason` orqali TUSHUNTIRADI.
JB-8'da yagona haqiqiy xatti-harakat o'zgarishi: `WORKFLOW_COMMAND` deb
klassifikatsiya qilingan buyruqlar ("workflowni to'xtat" kabi) HECH
QACHON yangi Mission yaratmaydi — LLM ularni xato ravishda "goal" deb
belgilasa ham, xavfsiz Run yo'liga tushadi.

JB-9 QO'SHIMCHASI — haqiqiy WORKFLOW_COMMAND va BACKGROUND_WORKFLOW
integratsiyasi (`WorkflowCommandExecutor`, `BackgroundWorkflowBridge`):
    - `WORKFLOW_COMMAND` endi HAQIQIY samara beradi: mavjud
      `AutomationEngine.Scheduler` (fully persistent) ustida
      LIST/STATUS/PAUSE/RESUME/CANCEL amallarini bajaradi. Bir nechta
      mos qoida bo'lsa — HECH QANDAY tanlash qilmaydi, foydalanuvchidan
      aniqlashtirish so'raydi.
    - `BACKGROUND_WORKFLOW` endi HAQIQIY `ScheduleRule` yaratadi
      (`core/schedule_expression.py` deterministik cron parseri +
      `AgentSelector` orqali mos agent). Fire vaqti kelganda mavjud
      `AutomationDaemon` (60s tick) ishga tushiradi.
    - `WORKFLOW` (bir martalik, aniq so'ralgan) — hozircha Mission
      yo'liga tushadi (bu HALOL: Mission allaqachon DB-persistent
      "ko'p qadamli, saqlanadigan, retryable" ijro qatlami).
    Barcha yangi imkoniyatlar ixtiyoriy (constructor parametri) —
    berilmasa JB-8 xatti-harakati saqlanadi.

Bog'liq qarorlar:
    JB-2 — goal→mission triaj (JARVIS Brain auditi)
    A-01 — mission holat mashinasi
    V-29 — task_class model marshrutlash (BU BOSHQA narsa: task_class
           modelni tanlaydi, request_kind esa ish YURITISH usulini)
    JB-8 — ijro rejimi (Workflow ixtiyoriy, default emas)
    JB-9 — WORKFLOW_COMMAND/BACKGROUND_WORKFLOW haqiqiy backend
           (Scheduler'ga ulanish)
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

import structlog

from zet.core.background_workflow import BackgroundWorkflowBridge
from zet.core.execution_mode import ExecutionDecision, ExecutionMode, ExecutionModeClassifier
from zet.core.intent import AmbiguousCommandError, IntentError, IntentRecognizer
from zet.core.mission import Mission
from zet.core.schedule_expression import parse_schedule
from zet.core.workflow_command import WorkflowCommandExecutor
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

    WORKFLOW_COMMAND = "workflow_command"
    """JB-9: mavjud workflow (Scheduler qoidasi) ustida amal —
    HECH QANDAY yangi Mission/Run yaratilmagan, Scheduler API to'g'ridan
    javob bergan."""

    BACKGROUND_WORKFLOW_CREATED = "background_workflow_created"
    """JB-9: haqiqiy `ScheduleRule` yaratildi (persistent) —
    `AutomationDaemon` cron vaqtida ishga tushiradi."""


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

    execution_mode: str = ""
    """JB-8: `ExecutionMode` qiymati (`execution_mode_classifier` berilgan
    bo'lsa) — masalan `"workflow"`, `"task_graph"`. Klassifikator
    berilmasa (default) — bo'sh (eski xatti-harakat, hech narsa
    o'zgarmagan)."""

    execution_reason: str = ""
    """JB-8: yuqoridagi qarorning tushuntirilishi (audit/UX uchun)."""


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
        execution_mode_classifier: ExecutionModeClassifier | None = None,
        workflow_command_executor: WorkflowCommandExecutor | None = None,
        background_workflow_bridge: BackgroundWorkflowBridge | None = None,
        schedule_persister: Callable[[], Awaitable[None]] | None = None,
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
            execution_mode_classifier: JB-8 — berilmasa (default `None`),
                `BrainResult.execution_mode`/`execution_reason` bo'sh
                qoladi va marshrutlash butunlay o'zgarmaydi (eski
                xatti-harakat). Berilsa, `WORKFLOW_COMMAND` deb
                klassifikatsiya qilingan buyruqlar hech qachon yangi
                Mission yaratmaydi.
            workflow_command_executor: JB-9 — berilsa `WORKFLOW_COMMAND`
                buyruqlari HAQIQIY `Scheduler` API (list/pause/resume/
                cancel) chaqiradi. Berilmasa — JB-8 xatti-harakati (Run
                yo'liga tushadi, hech narsa o'zgartirmaydi).
            background_workflow_bridge: JB-9 — berilsa `BACKGROUND_WORKFLOW`
                qarori HAQIQIY `ScheduleRule` yaratadi. Berilmasa — JB-8
                xatti-harakati (Mission yo'liga tushadi, bir martalik).
            schedule_persister: JB-9 — Scheduler holatini
                (`automation_state` jadvaliga) yozadigan async callback.
                Berilsa har WORKFLOW_COMMAND yoki BACKGROUND_WORKFLOW
                yaratilgach chaqiriladi. Berilmasa — persistensiya
                chaqiruvchi qatlam mas'uliyati (masalan mavjud
                `api/routes/automation.py` naqshi bilan).
        """
        self._orchestrator = orchestrator
        self._intent = intent_recognizer
        self._tool_names = list(tool_names)
        self._mission_runner = mission_runner
        self._run_lookup = run_lookup
        self._goal_missions_enabled = goal_missions_enabled
        self._execution_classifier = execution_mode_classifier
        self._workflow_command = workflow_command_executor
        self._background_workflow = background_workflow_bridge
        self._schedule_persister = schedule_persister

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

        decision = self._classify_execution(intent, command)

        # JB-8 xavfsizlik qoidasi: workflow-boshqaruv buyruqlari
        # ("Workflowni to'xtat" kabi) HECH QACHON yangi Mission
        # yaratmasin — LLM ularni xato ravishda "goal" deb belgilagan
        # bo'lsa ham. Mavjud workflow ustida amal — yangi maqsad EMAS.
        # JB-9: endi HAQIQIY backend (`WorkflowCommandExecutor`) mavjud
        # bo'lsa — Scheduler API'ni chaqiramiz; aks holda JB-8'dagi
        # kabi xavfsiz Run yo'liga tushamiz.
        if decision is not None and decision.mode == ExecutionMode.WORKFLOW_COMMAND:
            handled = await self._try_workflow_command(command, intent, decision)
            if handled is not None:
                return handled
            record = await self._orchestrator.start(command, intent=intent)
            return self._attach_decision(
                _from_run(record, BrainRoute.RUN, request_kind=intent.request_kind), decision
            )

        # JB-9: BACKGROUND_WORKFLOW — bridge mavjud bo'lsa haqiqiy
        # `ScheduleRule` yaratamiz; aks holda oddiy yo'ldan (JB-8 kabi).
        if decision is not None and decision.mode == ExecutionMode.BACKGROUND_WORKFLOW:
            handled = await self._try_background_workflow(command, intent, decision)
            if handled is not None:
                return handled

        if intent.request_kind != "goal":
            record = await self._orchestrator.start(command, intent=intent)
            return self._attach_decision(
                _from_run(record, BrainRoute.RUN, request_kind=intent.request_kind), decision
            )

        result = await self._handle_goal(command, intent)
        return self._attach_decision(result, decision)

    async def _try_workflow_command(
        self, command: Command, intent: Intent, decision: ExecutionDecision
    ) -> BrainResult | None:
        """JB-9: `WORKFLOW_COMMAND` uchun HAQIQIY Scheduler amali.

        Bridge berilmasa yoki xatolik bo'lsa — `None` qaytaradi (chaqiruvchi
        eski xavfsiz Run yo'liga tushadi). Bu — "fail-open" tamoyili:
        yangi funksiya ISHLAMAY qolsa, tizim ISHLAB TURSIN.
        """
        if self._workflow_command is None:
            return None
        try:
            outcome = self._workflow_command.execute(command.text)
        except Exception:
            log.exception("brain.workflow_command_failed", channel=command.channel)
            return None

        if outcome.affected_rule_ids and self._schedule_persister is not None:
            # Faqat holat o'zgargan bo'lsa persist qilamiz — LIST/STATUS
            # kabi read-only amallar uchun DB yozish keraksiz.
            try:
                await self._schedule_persister()
            except Exception:
                # Persist xatoligi so'rovni yiqitmasin — foydalanuvchi
                # javobni oldi, restart'da tikanmaslik ehtimoli kichik
                # muammo (mavjud persist naqshiga mos).
                log.warning("brain.schedule_persist_failed")

        log.info(
            "brain.workflow_command_result",
            action=outcome.action.value,
            ok=outcome.ok,
            needs_disambiguation=outcome.needs_disambiguation,
            affected=len(outcome.affected_rule_ids),
        )
        return self._attach_decision(
            BrainResult(
                text=outcome.message,
                ok=outcome.ok,
                route=BrainRoute.WORKFLOW_COMMAND,
                request_kind=intent.request_kind,
            ),
            decision,
        )

    async def _try_background_workflow(
        self, command: Command, intent: Intent, decision: ExecutionDecision
    ) -> BrainResult | None:
        """JB-9: `BACKGROUND_WORKFLOW` uchun HAQIQIY `ScheduleRule` yaratish.

        `None` qaytarilsa — chaqiruvchi mavjud yo'l bilan davom etadi
        (Mission/Run — ya'ni buyruq BIR MARTA baribir bajariladi, faqat
        takrorlanmaydi). Bu HALOL: parser cron ajratib olmasa, foydalanuvchi
        so'rovi baribir bir martalik javob oladi.
        """
        if self._background_workflow is None:
            return None
        expression = parse_schedule(command.text)
        if expression is None:
            log.info(
                "brain.background_workflow_no_cron",
                text_preview=command.text[:60],
            )
            return None
        try:
            outcome = self._background_workflow.create_schedule(
                intent=intent,
                expression=expression,
                command_text=command.text,
            )
        except Exception:
            log.exception("brain.background_workflow_failed")
            return None

        if outcome.ok and self._schedule_persister is not None:
            try:
                await self._schedule_persister()
            except Exception:
                log.warning("brain.schedule_persist_failed")

        # `ok=False` bo'lsa — bridge o'zi tushuntirdi (agent yo'q va h.k.);
        # foydalanuvchi HALOL javob oladi, tanlash uning qo'lida.
        log.info(
            "brain.background_workflow_result",
            ok=outcome.ok,
            rule_id=outcome.rule_id,
            cron=outcome.cron_expr,
        )
        return self._attach_decision(
            BrainResult(
                text=outcome.message,
                ok=outcome.ok,
                route=BrainRoute.BACKGROUND_WORKFLOW_CREATED,
                request_kind=intent.request_kind,
            ),
            decision,
        )

    def _classify_execution(self, intent: Intent, command: Command) -> ExecutionDecision | None:
        """JB-8: ijro rejimini aniqlaydi (`execution_mode_classifier` berilgan bo'lsa).

        Fail-open: klassifikatsiyaning O'ZI hech qachon so'rovni
        yiqitmasligi kerak (Brain'ning umumiy falsafasi — modul
        docstring'iga qarang).
        """
        if self._execution_classifier is None:
            return None
        try:
            decision = self._execution_classifier.classify(intent, text=command.text)
        except Exception:
            log.warning("brain.execution_mode_failed")
            return None
        log.info(
            "brain.execution_mode",
            mode=decision.mode.value,
            reason=decision.reason,
            confidence=decision.confidence,
        )
        return decision

    @staticmethod
    def _attach_decision(result: BrainResult, decision: ExecutionDecision | None) -> BrainResult:
        """`BrainResult`ga ijro rejimi qarorini yozadi (`decision=None` — o'zgarishsiz)."""
        if decision is None:
            return result
        return dataclasses.replace(
            result, execution_mode=decision.mode.value, execution_reason=decision.reason
        )

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
