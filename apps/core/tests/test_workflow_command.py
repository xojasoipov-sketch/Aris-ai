"""`WorkflowCommandExecutor` testlari (JB-9).

Buyruq matnidan qanday amal so'ralganini aniqlash + Scheduler API'ni
haqiqatan chaqirish + ambiguity halol qaytarish.
"""

from __future__ import annotations

from zet.automation.scheduler import Scheduler, ScheduleRule, ScheduleStatus
from zet.core.workflow_command import (
    WorkflowCommandAction,
    WorkflowCommandExecutor,
    detect_action,
)


def _rule(name: str, status: ScheduleStatus = ScheduleStatus.ACTIVE) -> ScheduleRule:
    """Test uchun yordamchi qoida quruvchi."""
    return ScheduleRule(
        name=name,
        agent_name="test-agent",
        cron_expr="0 9 * * *",
        status=status,
    )


class TestDetectAction:
    """Buyruq matnidan qaysi AMAL so'ralganini aniqlash."""

    def test_list_uzbek(self) -> None:
        assert detect_action("workflowlarimni ko'rsat") == WorkflowCommandAction.LIST

    def test_list_english(self) -> None:
        assert detect_action("list workflows") == WorkflowCommandAction.LIST

    def test_pause_uzbek(self) -> None:
        assert detect_action("workflowni to'xtat") == WorkflowCommandAction.PAUSE

    def test_pause_no_apostrophe(self) -> None:
        """'to'xtat' vs 'toxtat' — apostrof yo'q variant ham qamrab olinadi."""
        assert detect_action("workflowni toxtat") == WorkflowCommandAction.PAUSE

    def test_resume(self) -> None:
        assert detect_action("workflowni davom ettir") == WorkflowCommandAction.RESUME

    def test_cancel_uzbek(self) -> None:
        assert detect_action("workflowni bekor qil") == WorkflowCommandAction.CANCEL

    def test_restart(self) -> None:
        assert detect_action("workflowni qayta ishga tushir") == WorkflowCommandAction.RESTART

    def test_status(self) -> None:
        assert detect_action("workflow holati nima?") == WorkflowCommandAction.STATUS

    def test_unknown(self) -> None:
        """Aniq amal ko'rsatilmagan buyruq — UNKNOWN."""
        assert detect_action("workflow haqida gapir") == WorkflowCommandAction.UNKNOWN


class TestListCommand:
    def test_list_empty(self) -> None:
        scheduler = Scheduler()
        executor = WorkflowCommandExecutor(scheduler)

        result = executor.execute("workflowlarimni ko'rsat")

        assert result.action == WorkflowCommandAction.LIST
        assert result.ok is True
        assert "hozircha bironta" in result.message.lower()

    def test_list_shows_all_rules(self) -> None:
        scheduler = Scheduler()
        scheduler.add_rule(_rule("Kunlik hisobot"))
        scheduler.add_rule(_rule("Haftalik smm"))
        executor = WorkflowCommandExecutor(scheduler)

        result = executor.execute("show workflows")

        assert result.ok is True
        assert "Kunlik hisobot" in result.message
        assert "Haftalik smm" in result.message


class TestPauseCommand:
    def test_pause_single_workflow(self) -> None:
        scheduler = Scheduler()
        added = scheduler.add_rule(_rule("Kunlik hisobot"))
        executor = WorkflowCommandExecutor(scheduler)

        result = executor.execute("workflowni to'xtat")

        assert result.ok is True
        assert result.action == WorkflowCommandAction.PAUSE
        assert added.id in result.affected_rule_ids
        # HAQIQIY Scheduler holati o'zgargani — ground truth.
        stored = scheduler.get_rule(added.id)
        assert stored is not None
        assert stored.status == ScheduleStatus.PAUSED

    def test_pause_ambiguous_multiple_workflows(self) -> None:
        """JB-9 §7: bir nechta workflow bo'lsa — HECH QAYSISINI to'xtatmaslik."""
        scheduler = Scheduler()
        r1 = scheduler.add_rule(_rule("Kunlik hisobot"))
        r2 = scheduler.add_rule(_rule("Haftalik smm"))
        executor = WorkflowCommandExecutor(scheduler)

        result = executor.execute("workflowni to'xtat")

        assert result.ok is False
        assert result.needs_disambiguation is True
        assert "qaysi" in result.message.lower()
        # HECH QAYSISI o'zgarmagani — kritik xavfsizlik dalili.
        assert scheduler.get_rule(r1.id) is not None
        assert scheduler.get_rule(r1.id).status == ScheduleStatus.ACTIVE  # type: ignore[union-attr]
        assert scheduler.get_rule(r2.id).status == ScheduleStatus.ACTIVE  # type: ignore[union-attr]

    def test_pause_no_workflows(self) -> None:
        scheduler = Scheduler()
        executor = WorkflowCommandExecutor(scheduler)

        result = executor.execute("workflowni to'xtat")

        assert result.ok is False
        assert "topilmadi" in result.message.lower()


class TestResumeCommand:
    def test_resume_single_paused_workflow(self) -> None:
        scheduler = Scheduler()
        added = scheduler.add_rule(_rule("Kunlik", status=ScheduleStatus.PAUSED))
        executor = WorkflowCommandExecutor(scheduler)

        result = executor.execute("workflowni davom ettir")

        assert result.ok is True
        stored = scheduler.get_rule(added.id)
        assert stored is not None
        assert stored.status == ScheduleStatus.ACTIVE


class TestCancelCommand:
    def test_cancel_removes_rule(self) -> None:
        scheduler = Scheduler()
        added = scheduler.add_rule(_rule("Kunlik hisobot"))
        executor = WorkflowCommandExecutor(scheduler)

        result = executor.execute("workflowni bekor qil")

        assert result.ok is True
        assert scheduler.get_rule(added.id) is None  # butunlay o'chirilgan

    def test_cancel_ambiguity_leaves_all_intact(self) -> None:
        """Xavfsizlik: bir nechta bo'lsa hech qaysisi bekor qilinmaydi."""
        scheduler = Scheduler()
        r1 = scheduler.add_rule(_rule("A"))
        r2 = scheduler.add_rule(_rule("B"))
        executor = WorkflowCommandExecutor(scheduler)

        result = executor.execute("workflowni bekor qil")

        assert result.needs_disambiguation is True
        # Ikkalasi ham TURIBDI — hech biri o'chmagan.
        assert scheduler.get_rule(r1.id) is not None
        assert scheduler.get_rule(r2.id) is not None


class TestStatusCommand:
    def test_status_single_shows_details(self) -> None:
        scheduler = Scheduler()
        added = scheduler.add_rule(_rule("Kunlik hisobot"))
        executor = WorkflowCommandExecutor(scheduler)

        result = executor.execute("workflow holati nima")

        assert result.ok is True
        assert added.id in result.affected_rule_ids
        assert "Kunlik hisobot" in result.message


class TestUnknownAction:
    def test_unknown_action_returns_helpful_message(self) -> None:
        """Aniqlab bo'lmagan buyruq — ro'yxat + mumkin bo'lgan buyruqlar."""
        scheduler = Scheduler()
        scheduler.add_rule(_rule("Test"))
        executor = WorkflowCommandExecutor(scheduler)

        result = executor.execute("workflow haqida gap")

        assert result.action == WorkflowCommandAction.UNKNOWN
        assert result.ok is True
        assert "mumkin bo'lgan buyruqlar" in result.message.lower()


class TestNewCreationPrevention:
    """JB-8'dan meros: bu qatlam HECH QACHON yangi ScheduleRule
    yaratmaydi. Har qanday buyruq faqat MAVJUD qoidalar ustida
    ishlaydi."""

    def test_list_does_not_create_anything(self) -> None:
        scheduler = Scheduler()
        executor = WorkflowCommandExecutor(scheduler)
        before = len(scheduler.list_rules())

        executor.execute("workflowlarimni ko'rsat")

        assert len(scheduler.list_rules()) == before

    def test_pause_without_rules_creates_nothing(self) -> None:
        scheduler = Scheduler()
        executor = WorkflowCommandExecutor(scheduler)

        executor.execute("workflowni to'xtat")

        assert len(scheduler.list_rules()) == 0
