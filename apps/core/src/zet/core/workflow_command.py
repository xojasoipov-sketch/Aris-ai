"""Workflow-boshqaruv buyruqlari uchun haqiqiy backend (JB-9).

JB-8 xavfsizlik qoidasi ("workflowni to'xtat" YANGI Mission yaratmasin)
saqlanadi va endi HAQIQIY samara beradi: matn "workflowlarimni ko'rsat"
bo'lsa Scheduler'dan ro'yxat qaytadi; "to'xtat" bo'lsa mos qoida
`pause_rule` orqali PAUSED holatga o'tadi va persist qilinadi.

MUAMMO (JB-8'da ochiq qoldirilgan): `WORKFLOW_COMMAND` deb aniqlangan
buyruq oddiy Run yo'liga tushib qolar edi — LLM foydalanuvchining
"workflowni to'xtat" so'roviga suhbat javobi berardi, lekin hech qanday
haqiqiy jadval to'xtamas edi. Bu — "fake" tuyuladigan xatti-harakat.

YECHIM: bu modul buyruqning qaysi AMAL (LIST/STATUS/PAUSE/RESUME/CANCEL)
ekanini ODDIY kalit so'z bo'yicha aniqlaydi va mavjud
`AutomationEngine.scheduler` (fully persistent — `automation_state`
jadvali orqali) API'siga o'tkazadi.

NEGA DETERMINISTIK, LLM YOTQIZILMAGAN: bu qatlam foydalanuvchi
KUTGAN xavfsizlik chegarasi. "Workflowni to'xtat" degan buyruq LLM
tomonidan "workflowni ishga tushir" deb noto'g'ri talqin qilinishi
mumkin bo'lmasligi kerak (JB-8'ning asosiy dalili). LLM chaqiruvi
ustuvorlik tartibini buzardi.

QAYSI qoida (ID BERILMAGAN holda):
    - Faqat BITTA faol qoida bo'lsa — o'sha.
    - Bir nechta qoida bo'lsa — foydalanuvchidan aniqlashtirish so'ralib,
      RO'YXAT bilan javob beriladi. HECH QANDAY tanlash o'tkazilmaydi
      (JB-9 §7 "AMBIGUOUS WORKFLOW COMMANDS" — hech qachon o'ylab
      topilgan tanlov qilmang).

HALOL DOIRA (JB-9, ochiq kamchilik):
    Bu modul FAQAT `AutomationEngine.scheduler` (`ScheduleRule`'lar)
    ustida ishlaydi. `WorkflowChain` (`automation/workflow.py` — in-memory
    only, hech qachon Brain'ga ulanmagan) UCHUN buyruqlar SUPPORT
    QILINMAYDI — chunki `WorkflowChain` DB-persistent emas va restart'da
    yo'qoladi. Bu tanlov: "haqiqatan ham persistent bo'lgan" ScheduleRule
    ustida haqiqiy ishlash — soxta "workflow" obyektini ushlab turishdan
    ko'ra halolroq.

Bog'liq qarorlar:
    JB-8 — ExecutionModeClassifier (WORKFLOW_COMMAND aniqlash)
    JB-9 — Brain → Scheduler integratsiyasi (bu modul)
    Bo'lim 9 — AutomationEngine, Scheduler, ScheduleRule
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import structlog

from zet.automation.scheduler import Scheduler, ScheduleRule, ScheduleStatus

log = structlog.get_logger(__name__)


class WorkflowCommandAction(StrEnum):
    """Aniqlanadigan buyruq turlari."""

    LIST = "list"
    STATUS = "status"
    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"
    RESTART = "restart"
    UNKNOWN = "unknown"


# Amal → xarakterli kalit so'zlar. ODDIY substring qidiruvi (ExecutionMode
# klassifikatoridagi bilan bir xil naqsh — audit oson bo'lishi uchun).
#
# Ustuvorlik: PAUSE/RESUME/CANCEL/RESTART — konkret amallar (birinchi).
# LIST/STATUS — umumiy so'rovlar (keyingi).
#
# NEGA CANCEL "bekor qil" ni birinchi tekshiramiz "to'xtat"dan oldin:
# uzbek tilida "to'xtat" ham "pause" ham "cancel" ma'nosini beradi;
# lekin ANIQ "bekor qil" — CANCEL. Foydalanuvchi noaniq bo'lsa ehtiyot
# choralari (default = PAUSE) bilan qaytariladi.
_KEYWORDS: tuple[tuple[WorkflowCommandAction, tuple[str, ...]], ...] = (
    (
        WorkflowCommandAction.CANCEL,
        ("bekor qil", "cancel", "o'chir", "ochir", "delete"),
    ),
    (
        WorkflowCommandAction.RESTART,
        ("qayta ishga tushir", "qayta boshla", "restart", "reboot"),
    ),
    (
        WorkflowCommandAction.RESUME,
        ("davom ettir", "resume", "qayta faollashtir", "yoq"),
    ),
    (
        WorkflowCommandAction.PAUSE,
        ("to'xtat", "toxtat", "pause", "stop"),
    ),
    (
        WorkflowCommandAction.STATUS,
        ("holati", "holatini", "status", "nima ahvolda", "qay holda"),
    ),
    (
        WorkflowCommandAction.LIST,
        ("ko'rsat", "korsat", "ro'yxat", "royxat", "list", "show", "hammasini"),
    ),
)


def detect_action(text: str) -> WorkflowCommandAction:
    """Buyruq matnidan qaysi AMAL so'ralganini aniqlaydi.

    Aniqlab bo'lmasa — `UNKNOWN` (chaqiruvchi qaytib matnli tushuntirish
    berishi kerak, HECH QANDAY chuqur tanlash o'tkazmasin).
    """
    lowered = (text or "").lower()
    for action, keywords in _KEYWORDS:
        if any(kw in lowered for kw in keywords):
            return action
    return WorkflowCommandAction.UNKNOWN


@dataclass(frozen=True, slots=True)
class WorkflowCommandResult:
    """Buyruqning bajarilishidan qaytadigan strukturaviy natija.

    `ok`:
        True — amal muvaffaqiyatli bajarildi (yoki UNKNOWN uchun
        tushuntirish qaytarildi — bu ham "muvaffaqiyatli javob").
        False — amal talab qilindi lekin bajarib bo'lmadi (qoida
        topilmadi/xatolik).

    `needs_disambiguation`:
        True — bir nechta mos qoida bor, foydalanuvchi qaysi biri
        ekanini ko'rsatishi kerak. `message` allaqachon ro'yxatni o'z
        ichiga oladi.
    """

    action: WorkflowCommandAction
    ok: bool
    message: str
    needs_disambiguation: bool = False
    affected_rule_ids: tuple[str, ...] = ()


def _format_rule_line(rule: ScheduleRule, index: int) -> str:
    """Bitta qoidani ro'yxat uchun formatlaydi."""
    last_run = rule.last_run_at.strftime("%Y-%m-%d %H:%M UTC") if rule.last_run_at else "hech qachon"
    return (
        f"{index}. {rule.name}\n"
        f"   Cron: {rule.normalized_cron}\n"
        f"   Holat: {rule.status.value}\n"
        f"   Oxirgi bajarilish: {last_run}, jami: {rule.run_count}"
    )


def _format_rules(rules: list[ScheduleRule]) -> str:
    """Qoidalar ro'yxatini foydalanuvchi ko'rishga qulay matnga aylantiradi."""
    if not rules:
        return "Hozircha bironta ham workflow (jadval) yo'q."
    lines = [_format_rule_line(rule, index=i + 1) for i, rule in enumerate(rules)]
    return "Sizning workflow'laringiz:\n\n" + "\n\n".join(lines)


def _pickable_targets(rules: list[ScheduleRule]) -> list[ScheduleRule]:
    """Amal bajarish uchun 'nomzod' qoidalarni tanlaydi.

    Faqat ACTIVE/PAUSED qoidalar amaliy — DISABLED qoidalar allaqachon
    yopiq va yangi buyruqlar ular ustida ma'nosiz. Bu tanlov "birinchi
    faol qoida" uchun ambiguity aniqlashda ham foydali (yopiq qoidalarni
    hisobga olmasak, foydalanuvchi so'ragan qoidani topish osonroq).
    """
    return [r for r in rules if r.status in (ScheduleStatus.ACTIVE, ScheduleStatus.PAUSED)]


class WorkflowCommandExecutor:
    """`WORKFLOW_COMMAND` deb aniqlangan buyruqlar uchun HAQIQIY backend.

    Chaqiruvchi (Brain) buyruqning `text`ini beradi; bu klass buyruqning
    turini aniqlaydi va tegishli `Scheduler` API'sini chaqiradi. Persist
    qilish (`automation_state`ga yozish) — bu klassdan TASHQARIDA (Brain
    yoki chaqiruvchi qatlam) — chunki DB `Session` bu qatlamda mavjud
    emas va persist mexanizmi allaqachon `api/routes/automation.py`da
    ishlaydi (`_persist(background, engine)`).
    """

    def __init__(self, scheduler: Scheduler) -> None:
        self._scheduler = scheduler

    def execute(self, text: str) -> WorkflowCommandResult:
        """Buyruqni bajaradi va strukturaviy natija qaytaradi.

        Bu metod NEVER (a) yangi ScheduleRule/Workflow yaratmaydi,
        (b) hech qanday LLM chaqirmaydi, (c) qoidani "taxminan mos"
        deb tanlamaydi. Har qanday noaniqlik matnli tushuntirish bilan
        qaytariladi va foydalanuvchi qaror qabul qiladi.
        """
        action = detect_action(text)
        all_rules = self._scheduler.list_rules()

        if action == WorkflowCommandAction.LIST:
            return WorkflowCommandResult(
                action=action,
                ok=True,
                message=_format_rules(sorted(all_rules, key=lambda r: r.name.lower())),
            )

        if action == WorkflowCommandAction.STATUS:
            return self._status(all_rules)

        # Mutant amallar — nishonni topish kerak.
        candidates = _pickable_targets(all_rules)

        if action == WorkflowCommandAction.UNKNOWN:
            # Aniqlab bo'lmadi — HECH QANDAY o'ylab topilgan amal EMAS;
            # ro'yxat + qanday buyruqlar mumkinligi haqida tushuntirish.
            return WorkflowCommandResult(
                action=action,
                ok=True,
                message=(
                    "Qanday amal so'raganingizni aniqlay olmadim. "
                    "Mumkin bo'lgan buyruqlar: 'ko'rsat', 'to'xtat', "
                    "'davom ettir', 'bekor qil', 'holati'.\n\n"
                    + _format_rules(all_rules)
                ),
            )

        if not candidates:
            return WorkflowCommandResult(
                action=action,
                ok=False,
                message="Hech qanday faol workflow (jadval) topilmadi — amal bajarib bo'lmaydi.",
            )

        if len(candidates) > 1:
            listing = _format_rules(sorted(candidates, key=lambda r: r.name.lower()))
            return WorkflowCommandResult(
                action=action,
                ok=False,
                needs_disambiguation=True,
                message=(
                    "Bir nechta workflow topildi — qaysi birini "
                    f"{action.value} qilishni xohlaysiz?\n\n{listing}"
                ),
            )

        # Aynan bitta nomzod — amal bajariladi.
        target = candidates[0]
        return self._apply_action(action, target)

    def _status(self, all_rules: list[ScheduleRule]) -> WorkflowCommandResult:
        candidates = _pickable_targets(all_rules)
        if not candidates:
            return WorkflowCommandResult(
                action=WorkflowCommandAction.STATUS,
                ok=True,
                message="Faol workflow yo'q.",
            )
        if len(candidates) > 1:
            return WorkflowCommandResult(
                action=WorkflowCommandAction.STATUS,
                ok=True,
                message=_format_rules(sorted(candidates, key=lambda r: r.name.lower())),
            )
        target = candidates[0]
        return WorkflowCommandResult(
            action=WorkflowCommandAction.STATUS,
            ok=True,
            message=_format_rule_line(target, index=1),
            affected_rule_ids=(target.id,),
        )

    def _apply_action(
        self, action: WorkflowCommandAction, target: ScheduleRule
    ) -> WorkflowCommandResult:
        rule_id = target.id
        if action == WorkflowCommandAction.PAUSE:
            updated = self._scheduler.pause_rule(rule_id)
            if updated is None:
                return WorkflowCommandResult(
                    action=action,
                    ok=False,
                    message=f"Workflow '{target.name}' topilmadi.",
                )
            log.info("workflow_command.paused", rule_id=rule_id, name=target.name)
            return WorkflowCommandResult(
                action=action,
                ok=True,
                message=f"Workflow '{target.name}' to'xtatildi (paused).",
                affected_rule_ids=(rule_id,),
            )

        if action == WorkflowCommandAction.RESUME:
            updated = self._scheduler.resume_rule(rule_id)
            if updated is None:
                return WorkflowCommandResult(
                    action=action,
                    ok=False,
                    message=f"Workflow '{target.name}' topilmadi.",
                )
            log.info("workflow_command.resumed", rule_id=rule_id, name=target.name)
            return WorkflowCommandResult(
                action=action,
                ok=True,
                message=f"Workflow '{target.name}' qayta faollashtirildi (active).",
                affected_rule_ids=(rule_id,),
            )

        if action == WorkflowCommandAction.CANCEL:
            removed = self._scheduler.remove_rule(rule_id)
            if not removed:
                return WorkflowCommandResult(
                    action=action,
                    ok=False,
                    message=f"Workflow '{target.name}' topilmadi.",
                )
            log.info("workflow_command.cancelled", rule_id=rule_id, name=target.name)
            return WorkflowCommandResult(
                action=action,
                ok=True,
                message=f"Workflow '{target.name}' butunlay bekor qilindi.",
                affected_rule_ids=(rule_id,),
            )

        if action == WorkflowCommandAction.RESTART:
            # RESTART = PAUSE + RESUME (holatni qayta yoqish) — run_count
            # saqlanadi. "Faqat bir marta darhol ishga tushir" TALAB
            # qilinmaydi (bu Scheduler mas'uliyati emas — foydalanuvchi
            # buni alohida so'rashi kerak).
            paused = self._scheduler.pause_rule(rule_id)
            if paused is None:
                return WorkflowCommandResult(
                    action=action,
                    ok=False,
                    message=f"Workflow '{target.name}' topilmadi.",
                )
            resumed = self._scheduler.resume_rule(rule_id)
            log.info("workflow_command.restarted", rule_id=rule_id, name=target.name)
            return WorkflowCommandResult(
                action=action,
                ok=True,
                message=f"Workflow '{target.name}' qayta boshlandi (active).",
                affected_rule_ids=(rule_id,) if resumed is not None else (),
            )

        # Bu joyga borish mumkin emas (yuqorida `if` bilan barcha
        # `WorkflowCommandAction` qamrab olingan), lekin exhaustiveness
        # uchun aniq javob.
        return WorkflowCommandResult(
            action=action,
            ok=False,
            message=f"Ichki xatolik: '{action.value}' amali qo'llab-quvvatlanmaydi.",
        )


__all__ = [
    "WorkflowCommandAction",
    "WorkflowCommandExecutor",
    "WorkflowCommandResult",
    "detect_action",
]
