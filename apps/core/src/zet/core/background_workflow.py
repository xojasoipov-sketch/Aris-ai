"""Brain → AutomationEngine.Scheduler integratsiyasi (JB-9).

MUAMMO (JB-8'da ochiq qoldirilgan): "Har kuni soat 9 da telegramimni
tekshir" so'rovi BACKGROUND_WORKFLOW deb to'g'ri aniqlanar edi, lekin
hech qanday HAQIQIY `ScheduleRule` yaratilmasdi — so'rov shunchaki
Mission yo'liga tushib, BIR MARTA bajarilardi. Bu — spetsifikatsiyaga
zid: foydalanuvchi "muntazam ravishda" so'raganda tizim buni tushunishi
kerak.

YECHIM: bu modul BACKGROUND_WORKFLOW qarori uchun:
    1. Buyruq matnidan cron ifodasini ajratib oladi
       (`core/schedule_expression.py`, deterministik).
    2. `Intent.requires_tools` va `AgentSelector` orqali MOS AGENT
       tanlaydi (agent yo'q bo'lsa — Rule yaratmaydi, halol xato
       qaytaradi).
    3. Mavjud `Scheduler.add_rule()` ni chaqiradi.
    4. Persist qilish (`automation_state`) — chaqiruvchi qatlam
       mas'uliyati (JB-9 `deps.py`da bir marta yozilgan mexanizm
       orqali).

NEGA YANGI DVIGATEL EMAS: `AutomationEngine.Scheduler` allaqachon:
    - DB-persistent (`automation_state` jadvali),
    - restart-safe (`load_automation` bootstrap'da),
    - 60 soniyada bir `AutomationDaemon.tick()` bilan ishlaydi,
    - `run_agent_command()` orqali ishga tushiradi,
    - `record_run()` + `pause/resume/remove` to'liq API bilan.

Yangi qatlam qurish bu ishning ustidan takrorlash bo'lardi.

HALOL DOIRA (JB-9, ochiq kamchilik):
    Bu bridge FAQAT bir "asosiy agent" tanlaydi va uning nomi bilan
    ScheduleRule yozadi — Mission yo'lidagi to'liq Task Graph (2+ tool
    uchun parallel ijro) HALI qo'llab-quvvatlanmaydi. Bu — Scheduler'ning
    o'zi HOZIRDA bir ScheduleRule = bir agent naqshi bo'yicha qurilganidan.
    "Har kuni ko'p bosqichli mission bajar" senariysi uchun keyingi
    ish (JB-10+) kerak bo'ladi: ScheduleRule fire'i Mission YARATSIN,
    o'sha Mission esa Task Graph orqali ijro etilsin.

Bog'liq qarorlar:
    JB-8 — ExecutionModeClassifier (BACKGROUND_WORKFLOW aniqlash)
    JB-9 — bu bridge
    Bo'lim 9 — Scheduler / AutomationDaemon / run_agent_command
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from zet.automation.scheduler import ScheduleRule

if TYPE_CHECKING:
    from zet.automation.engine import AutomationEngine
    from zet.core.agent_selector import AgentSelector
    from zet.core.schedule_expression import ScheduleExpression
    from zet.domain.command import Intent

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class BackgroundWorkflowResult:
    """Bridge amalining natijasi (chaqiruvchi UX/log uchun)."""

    ok: bool
    """`True` — ScheduleRule muvaffaqiyatli yaratilgan."""

    message: str
    """Foydalanuvchiga qaytariladigan HALOL tushuntirish (ok=False
    bo'lganda — nima uchun yaratilmadi va nima qilish kerak)."""

    rule_id: str | None = None
    """Yaratilgan qoida ID (`ok=True` bo'lsa)."""

    cron_expr: str | None = None
    """Aniqlangan cron ifodasi (audit uchun)."""


class BackgroundWorkflowBridge:
    """`BACKGROUND_WORKFLOW` qaroridan haqiqiy `ScheduleRule` yaratadi.

    Bir marta yaratiladi, `Brain`ga optional param sifatida beriladi
    (berilmasa — eski xatti-harakat: BACKGROUND_WORKFLOW rejim Mission
    yo'liga tushadi, JB-8'dagi kabi).
    """

    def __init__(
        self,
        *,
        automation_engine: AutomationEngine,
        agent_selector: AgentSelector,
    ) -> None:
        self._engine = automation_engine
        self._selector = agent_selector

    def create_schedule(
        self,
        *,
        intent: Intent,
        expression: ScheduleExpression,
        command_text: str,
    ) -> BackgroundWorkflowResult:
        """Yangi `ScheduleRule` yaratadi (mos agent topilsa).

        Args:
            intent: LLM klassifikatsiyalangan Intent (requires_tools
                kerakli tool nomlari uchun).
            expression: cron ifoda + tushuntirish (matndan ajratilgan).
            command_text: foydalanuvchining asl so'rovi — jadval
                fire bo'lganda agentga yuboriladigan buyruq.

        Returns:
            `BackgroundWorkflowResult` — ok/message/rule_id.
        """
        required_tools = list(intent.requires_tools)

        # Agent tanlash — mavjud AgentSelector (JB-4). Agent topilmasa
        # HECH QANDAY jadval yaratilmaydi (soxta muvaffaqiyatdan ko'ra
        # halol xato yaxshiroq).
        agent_name = self._pick_agent(required_tools)
        if agent_name is None:
            tools_str = ", ".join(required_tools) if required_tools else "(ko'rsatilmagan)"
            return BackgroundWorkflowResult(
                ok=False,
                message=(
                    "Takrorlanuvchi jadval yaratib bo'lmadi — bu vazifa "
                    "uchun mos ACTIVE agent topilmadi. "
                    f"Talab qilingan toollar: {tools_str}. "
                    "Iltimos, avval mos agentni yaratib faollashtiring."
                ),
                cron_expr=expression.cron,
            )

        rule_name = self._derive_rule_name(command_text)
        try:
            rule = self._engine.scheduler.add_rule(
                ScheduleRule(
                    name=rule_name,
                    agent_name=agent_name,
                    cron_expr=expression.cron,
                    command=command_text,
                )
            )
        except ValueError as exc:
            # `validate_cron` xatosi — bizning `schedule_expression`
            # parser'imiz noto'g'ri cron yasagan degani (bug); halol
            # xato qaytariladi.
            log.warning(
                "background_workflow.invalid_cron",
                cron=expression.cron,
                error=str(exc),
            )
            return BackgroundWorkflowResult(
                ok=False,
                message=f"Ichki xatolik: cron ifodasi noto'g'ri ({exc}).",
                cron_expr=expression.cron,
            )

        log.info(
            "background_workflow.scheduled",
            rule_id=rule.id,
            rule_name=rule.name,
            agent=agent_name,
            cron=rule.normalized_cron,
            reason=expression.reason,
        )
        return BackgroundWorkflowResult(
            ok=True,
            message=(
                f"Jadval yaratildi: '{rule.name}' — {expression.reason} "
                f"({agent_name} agent bilan). Cron: `{rule.normalized_cron}`. "
                "To'xtatish uchun: 'workflowni to'xtat', bekor qilish uchun: "
                "'workflowni bekor qil'."
            ),
            rule_id=rule.id,
            cron_expr=rule.normalized_cron,
        )

    def _pick_agent(self, required_tools: list[str]) -> str | None:
        """Talab qilingan toollar uchun eng qamrovli ACTIVE agentni tanlaydi.

        Toollar berilmasa (LLM `requires_tools` bo'sh ro'yxat qaytargan
        bo'lsa) — HECH QANDAY agent tanlanmaydi. Bu ATAYLAB: "har kuni
        biror narsa qil" kabi noaniq buyruq uchun jimgina bir default
        agent tanlash — kutilmagan xatti-harakat.
        """
        if not required_tools:
            return None
        matches = self._selector.rank_for_tools(required_tools)
        if not matches:
            return None
        return matches[0].agent_name

    @staticmethod
    def _derive_rule_name(command_text: str) -> str:
        """Buyruq matnidan qoida uchun qisqa nom yasaydi (audit/UX uchun).

        Uzunlik chegarasi (`ScheduleRule.name` — 100 belgi). Yozuv
        oldiga aniq prefiks ("Brain") qo'yiladi — ko'p qoidalar orasida
        Brain-yaratgan qoida ajralib tursin.
        """
        head = command_text.strip().split("\n", 1)[0]
        if len(head) > 80:
            head = head[:77] + "..."
        return f"Brain: {head}"


__all__ = ["BackgroundWorkflowBridge", "BackgroundWorkflowResult"]
