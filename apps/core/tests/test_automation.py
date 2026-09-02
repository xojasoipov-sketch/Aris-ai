"""Bo'lim 9 testlari — Automation Engine (Scheduler, Triggers, Workflow).

Test guruhlari:
    1. ScheduleRule — yaratish, cron validatsiya, shortcutlar, is_active
    2. Scheduler — CRUD, pause/resume, record_run, stats
    3. TriggerCondition — eq, ne, contains, gt, lt, missing field
    4. EventTrigger — yaratish, matches, render_command, is_active, max_fires
    5. TriggerRegistry — CRUD, find_matching, record_fire, disable, stats
    6. WorkflowStep — yaratish, maydonlar
    7. WorkflowChain — yaratish, progress, current_step, is_terminal
    8. WorkflowRunner — create, start, complete_step, fail_step, stats
    9. AutomationEngine — event processing, integration
    10. Automation __init__ — exports
    11. Xavfsizlik invariantlari
"""

from __future__ import annotations

import pytest

from zet.automation import (
    AutomationEngine,
    EventTrigger,
    ScheduleRule,
    ScheduleStatus,
    TriggerCondition,
    TriggerType,
    WorkflowChain,
    WorkflowStatus,
    WorkflowStep,
)
from zet.automation.engine import AutomationEvent
from zet.automation.scheduler import Scheduler, validate_cron
from zet.automation.triggers import TriggerRegistry
from zet.automation.workflow import WorkflowRunner, validate_chain

# ── 1. ScheduleRule ──────────────────────────────────────────────


class TestScheduleRule:
    def test_create_basic(self) -> None:
        rule = ScheduleRule(
            name="Kunlik hisobot",
            agent_name="research",
            cron_expr="0 9 * * *",
        )
        assert rule.name == "Kunlik hisobot"
        assert rule.agent_name == "research"
        assert rule.cron_expr == "0 9 * * *"
        assert rule.status == ScheduleStatus.ACTIVE
        assert rule.is_active
        assert rule.run_count == 0
        assert len(rule.id) == 12

    def test_shortcut_hourly(self) -> None:
        rule = ScheduleRule(name="Har soat", agent_name="ops", cron_expr="@hourly")
        assert rule.normalized_cron == "0 * * * *"

    def test_shortcut_daily(self) -> None:
        rule = ScheduleRule(name="Har kuni", agent_name="ops", cron_expr="@daily")
        assert rule.normalized_cron == "0 0 * * *"

    def test_shortcut_weekly(self) -> None:
        rule = ScheduleRule(name="Har hafta", agent_name="ops", cron_expr="@weekly")
        assert rule.normalized_cron == "0 0 * * 0"

    def test_shortcut_monthly(self) -> None:
        rule = ScheduleRule(name="Har oy", agent_name="ops", cron_expr="@monthly")
        assert rule.normalized_cron == "0 0 1 * *"

    def test_normal_cron_passthrough(self) -> None:
        rule = ScheduleRule(name="Custom", agent_name="ops", cron_expr="30 14 * * 1-5")
        assert rule.normalized_cron == "30 14 * * 1-5"

    def test_inactive_when_paused(self) -> None:
        rule = ScheduleRule(
            name="Paused",
            agent_name="ops",
            cron_expr="@daily",
            status=ScheduleStatus.PAUSED,
        )
        assert not rule.is_active

    def test_inactive_when_max_runs_reached(self) -> None:
        rule = ScheduleRule(
            name="Limited",
            agent_name="ops",
            cron_expr="@daily",
            max_runs=5,
            run_count=5,
        )
        assert not rule.is_active

    def test_active_when_under_max_runs(self) -> None:
        rule = ScheduleRule(
            name="Limited",
            agent_name="ops",
            cron_expr="@daily",
            max_runs=5,
            run_count=3,
        )
        assert rule.is_active

    def test_frozen(self) -> None:
        rule = ScheduleRule(name="Test", agent_name="ops", cron_expr="@daily")
        with pytest.raises(Exception):  # noqa: B017
            rule.name = "other"  # type: ignore[misc]


class TestCronValidation:
    def test_valid_standard(self) -> None:
        assert validate_cron("0 9 * * *")
        assert validate_cron("30 14 * * 1-5")
        assert validate_cron("*/15 * * * *")
        assert validate_cron("0 0 1 * *")

    def test_valid_shortcuts(self) -> None:
        assert validate_cron("@hourly")
        assert validate_cron("@daily")
        assert validate_cron("@weekly")
        assert validate_cron("@monthly")

    def test_invalid(self) -> None:
        assert not validate_cron("")
        assert not validate_cron("not a cron")
        assert not validate_cron("0 9 *")  # Too few fields
        assert not validate_cron("0 9 * * * *")  # Too many fields


# ── 2. Scheduler ─────────────────────────────────────────────────


class TestScheduler:
    def test_add_rule(self) -> None:
        sched = Scheduler()
        rule = ScheduleRule(name="Test", agent_name="research", cron_expr="@daily")
        added = sched.add_rule(rule)
        assert added.id == rule.id
        assert sched.get_rule(rule.id) is not None

    def test_add_invalid_cron(self) -> None:
        sched = Scheduler()
        rule = ScheduleRule(name="Bad", agent_name="ops", cron_expr="not valid")
        with pytest.raises(ValueError, match="Noto'g'ri cron"):
            sched.add_rule(rule)

    def test_list_all(self) -> None:
        sched = Scheduler()
        sched.add_rule(ScheduleRule(name="A", agent_name="a", cron_expr="@daily"))
        sched.add_rule(ScheduleRule(name="B", agent_name="b", cron_expr="@hourly"))
        assert len(sched.list_rules()) == 2

    def test_list_by_status(self) -> None:
        sched = Scheduler()
        r1 = sched.add_rule(ScheduleRule(name="A", agent_name="a", cron_expr="@daily"))
        sched.add_rule(ScheduleRule(name="B", agent_name="b", cron_expr="@hourly"))
        sched.pause_rule(r1.id)
        assert len(sched.list_rules(status=ScheduleStatus.ACTIVE)) == 1
        assert len(sched.list_rules(status=ScheduleStatus.PAUSED)) == 1

    def test_pause_resume(self) -> None:
        sched = Scheduler()
        rule = sched.add_rule(ScheduleRule(name="A", agent_name="a", cron_expr="@daily"))
        paused = sched.pause_rule(rule.id)
        assert paused is not None
        assert paused.status == ScheduleStatus.PAUSED

        resumed = sched.resume_rule(rule.id)
        assert resumed is not None
        assert resumed.status == ScheduleStatus.ACTIVE

    def test_pause_missing(self) -> None:
        sched = Scheduler()
        assert sched.pause_rule("nonexistent") is None

    def test_record_run(self) -> None:
        sched = Scheduler()
        rule = sched.add_rule(ScheduleRule(name="A", agent_name="a", cron_expr="@daily"))
        assert rule.run_count == 0
        updated = sched.record_run(rule.id)
        assert updated is not None
        assert updated.run_count == 1
        assert updated.last_run_at is not None

    def test_remove_rule(self) -> None:
        sched = Scheduler()
        rule = sched.add_rule(ScheduleRule(name="A", agent_name="a", cron_expr="@daily"))
        assert sched.remove_rule(rule.id)
        assert sched.get_rule(rule.id) is None

    def test_remove_missing(self) -> None:
        sched = Scheduler()
        assert not sched.remove_rule("nonexistent")

    def test_active_rules(self) -> None:
        sched = Scheduler()
        sched.add_rule(ScheduleRule(name="A", agent_name="a", cron_expr="@daily"))
        r2 = sched.add_rule(ScheduleRule(name="B", agent_name="b", cron_expr="@hourly"))
        sched.pause_rule(r2.id)
        assert len(sched.active_rules) == 1

    def test_stats(self) -> None:
        sched = Scheduler()
        sched.add_rule(ScheduleRule(name="A", agent_name="a", cron_expr="@daily"))
        r2 = sched.add_rule(ScheduleRule(name="B", agent_name="b", cron_expr="@hourly"))
        sched.pause_rule(r2.id)
        stats = sched.stats
        assert stats["total"] == 2
        assert stats["active"] == 1
        assert stats["paused"] == 1

    def test_get_missing(self) -> None:
        sched = Scheduler()
        assert sched.get_rule("nonexistent") is None


# ── 3. TriggerCondition ──────────────────────────────────────────


class TestTriggerCondition:
    def test_eq(self) -> None:
        cond = TriggerCondition(field="event_type", operator="eq", value="motion")
        assert cond.evaluate({"event_type": "motion"})
        assert not cond.evaluate({"event_type": "noise"})

    def test_ne(self) -> None:
        cond = TriggerCondition(field="status", operator="ne", value="ok")
        assert cond.evaluate({"status": "error"})
        assert not cond.evaluate({"status": "ok"})

    def test_contains(self) -> None:
        cond = TriggerCondition(field="message", operator="contains", value="alarm")
        assert cond.evaluate({"message": "fire alarm detected"})
        assert not cond.evaluate({"message": "all clear"})

    def test_gt(self) -> None:
        cond = TriggerCondition(field="score", operator="gt", value="50")
        assert cond.evaluate({"score": "75"})
        assert not cond.evaluate({"score": "30"})
        assert not cond.evaluate({"score": "50"})

    def test_lt(self) -> None:
        cond = TriggerCondition(field="budget", operator="lt", value="0.1")
        assert cond.evaluate({"budget": "0.05"})
        assert not cond.evaluate({"budget": "0.2"})

    def test_missing_field(self) -> None:
        cond = TriggerCondition(field="missing", operator="eq", value="test")
        assert not cond.evaluate({"other": "data"})

    def test_gt_invalid_value(self) -> None:
        cond = TriggerCondition(field="x", operator="gt", value="50")
        assert not cond.evaluate({"x": "not-a-number"})

    def test_lt_invalid_value(self) -> None:
        cond = TriggerCondition(field="x", operator="lt", value="50")
        assert not cond.evaluate({"x": "abc"})

    def test_unknown_operator(self) -> None:
        cond = TriggerCondition(field="x", operator="regex", value=".*")
        assert not cond.evaluate({"x": "anything"})

    def test_frozen(self) -> None:
        cond = TriggerCondition(field="x", operator="eq", value="y")
        with pytest.raises(Exception):  # noqa: B017
            cond.field = "z"  # type: ignore[misc]


# ── 4. EventTrigger ──────────────────────────────────────────────


class TestEventTrigger:
    def test_create(self) -> None:
        trigger = EventTrigger(
            name="Motion Alert",
            trigger_type=TriggerType.DEVICE,
            agent_name="vision",
        )
        assert trigger.name == "Motion Alert"
        assert trigger.trigger_type == TriggerType.DEVICE
        assert trigger.is_active
        assert len(trigger.id) == 12

    def test_matches_no_conditions(self) -> None:
        """Shartsiz trigger har doim ishlaydi."""
        trigger = EventTrigger(
            name="Catch All",
            trigger_type=TriggerType.SYSTEM,
            agent_name="ops",
        )
        assert trigger.matches({"anything": "data"})

    def test_matches_with_conditions(self) -> None:
        trigger = EventTrigger(
            name="Motion",
            trigger_type=TriggerType.DEVICE,
            agent_name="vision",
            conditions=[
                TriggerCondition(field="event_type", operator="eq", value="motion"),
                TriggerCondition(field="camera_id", operator="eq", value="cam1"),
            ],
        )
        assert trigger.matches({"event_type": "motion", "camera_id": "cam1"})
        assert not trigger.matches({"event_type": "motion", "camera_id": "cam2"})
        assert not trigger.matches({"event_type": "noise", "camera_id": "cam1"})

    def test_matches_disabled(self) -> None:
        trigger = EventTrigger(
            name="Off",
            trigger_type=TriggerType.SYSTEM,
            agent_name="ops",
            enabled=False,
        )
        assert not trigger.matches({"anything": "data"})

    def test_matches_max_fires_reached(self) -> None:
        trigger = EventTrigger(
            name="Limited",
            trigger_type=TriggerType.SYSTEM,
            agent_name="ops",
            max_fires=3,
            fire_count=3,
        )
        assert not trigger.is_active
        assert not trigger.matches({"anything": "data"})

    def test_render_command(self) -> None:
        trigger = EventTrigger(
            name="Alert",
            trigger_type=TriggerType.DEVICE,
            agent_name="vision",
            command_template="Kamerada harakat: {camera_id}, tur: {event_type}",
        )
        result = trigger.render_command({"camera_id": "cam1", "event_type": "motion"})
        assert result == "Kamerada harakat: cam1, tur: motion"

    def test_render_empty_template(self) -> None:
        trigger = EventTrigger(
            name="No cmd",
            trigger_type=TriggerType.SYSTEM,
            agent_name="ops",
        )
        assert trigger.render_command({"x": "y"}) == ""

    def test_frozen(self) -> None:
        trigger = EventTrigger(
            name="X",
            trigger_type=TriggerType.SYSTEM,
            agent_name="ops",
        )
        with pytest.raises(Exception):  # noqa: B017
            trigger.name = "Y"  # type: ignore[misc]


# ── 5. TriggerRegistry ──────────────────────────────────────────


class TestTriggerRegistry:
    def test_add_and_get(self) -> None:
        reg = TriggerRegistry()
        trigger = EventTrigger(
            name="T1",
            trigger_type=TriggerType.DEVICE,
            agent_name="vision",
        )
        reg.add(trigger)
        assert reg.get(trigger.id) is not None

    def test_list_all(self) -> None:
        reg = TriggerRegistry()
        reg.add(EventTrigger(name="A", trigger_type=TriggerType.DEVICE, agent_name="v"))
        reg.add(EventTrigger(name="B", trigger_type=TriggerType.WEBHOOK, agent_name="w"))
        assert len(reg.list_triggers()) == 2

    def test_list_by_type(self) -> None:
        reg = TriggerRegistry()
        reg.add(EventTrigger(name="A", trigger_type=TriggerType.DEVICE, agent_name="v"))
        reg.add(EventTrigger(name="B", trigger_type=TriggerType.WEBHOOK, agent_name="w"))
        assert len(reg.list_triggers(trigger_type=TriggerType.DEVICE)) == 1

    def test_find_matching(self) -> None:
        reg = TriggerRegistry()
        reg.add(
            EventTrigger(
                name="Motion",
                trigger_type=TriggerType.DEVICE,
                agent_name="vision",
                conditions=[TriggerCondition(field="event_type", operator="eq", value="motion")],
            )
        )
        reg.add(
            EventTrigger(
                name="Other",
                trigger_type=TriggerType.DEVICE,
                agent_name="ops",
                conditions=[TriggerCondition(field="event_type", operator="eq", value="noise")],
            )
        )
        matches = reg.find_matching({"event_type": "motion"})
        assert len(matches) == 1
        assert matches[0].name == "Motion"

    def test_record_fire(self) -> None:
        reg = TriggerRegistry()
        trigger = reg.add(EventTrigger(name="A", trigger_type=TriggerType.SYSTEM, agent_name="ops"))
        assert trigger.fire_count == 0
        updated = reg.record_fire(trigger.id)
        assert updated is not None
        assert updated.fire_count == 1
        assert updated.last_fired_at is not None

    def test_disable(self) -> None:
        reg = TriggerRegistry()
        trigger = reg.add(EventTrigger(name="A", trigger_type=TriggerType.SYSTEM, agent_name="ops"))
        disabled = reg.disable(trigger.id)
        assert disabled is not None
        assert not disabled.enabled

    def test_remove(self) -> None:
        reg = TriggerRegistry()
        trigger = reg.add(EventTrigger(name="A", trigger_type=TriggerType.SYSTEM, agent_name="ops"))
        assert reg.remove(trigger.id)
        assert reg.get(trigger.id) is None

    def test_remove_missing(self) -> None:
        reg = TriggerRegistry()
        assert not reg.remove("nonexistent")

    def test_stats(self) -> None:
        reg = TriggerRegistry()
        reg.add(EventTrigger(name="A", trigger_type=TriggerType.SYSTEM, agent_name="ops"))
        t2 = reg.add(EventTrigger(name="B", trigger_type=TriggerType.DEVICE, agent_name="v"))
        reg.disable(t2.id)
        stats = reg.stats
        assert stats["total"] == 2
        assert stats["active"] == 1
        assert stats["disabled"] == 1


# ── 6. WorkflowStep ─────────────────────────────────────────────


class TestWorkflowStep:
    def test_create(self) -> None:
        step = WorkflowStep(agent_name="research")
        assert step.agent_name == "research"
        assert step.status == WorkflowStatus.PENDING
        assert step.output == ""
        assert step.error is None

    def test_with_template(self) -> None:
        step = WorkflowStep(
            agent_name="ceo",
            command_template="Tadqiqot natijasi: {prev_output}",
            timeout_s=300,
            require_approval=True,
        )
        assert step.require_approval
        assert step.timeout_s == 300

    def test_frozen(self) -> None:
        step = WorkflowStep(agent_name="x")
        with pytest.raises(Exception):  # noqa: B017
            step.agent_name = "y"  # type: ignore[misc]


# ── 7. WorkflowChain ────────────────────────────────────────────


class TestWorkflowChain:
    def test_create(self) -> None:
        chain = WorkflowChain(
            name="Hisobot zanjiri",
            steps=[
                WorkflowStep(agent_name="research"),
                WorkflowStep(agent_name="ceo"),
            ],
        )
        assert chain.name == "Hisobot zanjiri"
        assert chain.step_count == 2
        assert chain.completed_steps == 0
        assert chain.progress == 0.0
        assert chain.status == WorkflowStatus.PENDING
        assert not chain.is_terminal

    def test_progress(self) -> None:
        chain = WorkflowChain(
            name="Test",
            steps=[
                WorkflowStep(agent_name="a", status=WorkflowStatus.COMPLETED),
                WorkflowStep(agent_name="b"),
            ],
        )
        assert chain.progress == 0.5

    def test_current_step_index(self) -> None:
        chain = WorkflowChain(
            name="Test",
            steps=[
                WorkflowStep(agent_name="a", status=WorkflowStatus.COMPLETED),
                WorkflowStep(agent_name="b", status=WorkflowStatus.RUNNING),
                WorkflowStep(agent_name="c"),
            ],
        )
        assert chain.current_step_index == 1

    def test_current_step_none_when_done(self) -> None:
        chain = WorkflowChain(
            name="Test",
            steps=[
                WorkflowStep(agent_name="a", status=WorkflowStatus.COMPLETED),
            ],
            status=WorkflowStatus.COMPLETED,
        )
        assert chain.current_step_index is None

    def test_is_terminal(self) -> None:
        for status in [
            WorkflowStatus.COMPLETED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        ]:
            chain = WorkflowChain(name="T", status=status)
            assert chain.is_terminal

    def test_not_terminal(self) -> None:
        for status in [WorkflowStatus.PENDING, WorkflowStatus.RUNNING]:
            chain = WorkflowChain(name="T", status=status)
            assert not chain.is_terminal

    def test_empty_progress(self) -> None:
        chain = WorkflowChain(name="Empty")
        assert chain.progress == 0.0


class TestWorkflowValidation:
    def test_valid(self) -> None:
        errors = validate_chain(
            [
                WorkflowStep(agent_name="a"),
                WorkflowStep(agent_name="b"),
            ]
        )
        assert errors == []

    def test_empty(self) -> None:
        errors = validate_chain([])
        assert any("hech qanday qadam" in e for e in errors)

    def test_too_many_steps(self) -> None:
        steps = [WorkflowStep(agent_name=f"a{i}") for i in range(15)]
        errors = validate_chain(steps)
        assert any("juda uzun" in e for e in errors)


# ── 8. WorkflowRunner ───────────────────────────────────────────


class TestWorkflowRunner:
    def test_create(self) -> None:
        runner = WorkflowRunner()
        wf = runner.create(
            name="Test",
            steps=[
                WorkflowStep(agent_name="research"),
                WorkflowStep(agent_name="ceo"),
            ],
        )
        assert wf.name == "Test"
        assert wf.step_count == 2

    def test_create_invalid(self) -> None:
        runner = WorkflowRunner()
        with pytest.raises(ValueError, match="validatsiya"):
            runner.create(name="Empty", steps=[])

    def test_start(self) -> None:
        runner = WorkflowRunner()
        wf = runner.create(
            name="Test",
            steps=[
                WorkflowStep(agent_name="a"),
                WorkflowStep(agent_name="b"),
            ],
        )
        started = runner.start(wf.id)
        assert started is not None
        assert started.status == WorkflowStatus.RUNNING
        assert started.steps[0].status == WorkflowStatus.RUNNING
        assert started.started_at is not None

    def test_start_missing(self) -> None:
        runner = WorkflowRunner()
        assert runner.start("nonexistent") is None

    def test_complete_step(self) -> None:
        runner = WorkflowRunner()
        wf = runner.create(
            name="Test",
            steps=[
                WorkflowStep(agent_name="a"),
                WorkflowStep(agent_name="b"),
            ],
        )
        runner.start(wf.id)
        updated = runner.complete_step(wf.id, 0, output="result A")
        assert updated is not None
        assert updated.steps[0].status == WorkflowStatus.COMPLETED
        assert updated.steps[0].output == "result A"
        assert updated.steps[1].status == WorkflowStatus.RUNNING
        assert updated.status == WorkflowStatus.RUNNING

    def test_complete_last_step(self) -> None:
        runner = WorkflowRunner()
        wf = runner.create(
            name="Test",
            steps=[WorkflowStep(agent_name="a")],
        )
        runner.start(wf.id)
        updated = runner.complete_step(wf.id, 0, output="done")
        assert updated is not None
        assert updated.status == WorkflowStatus.COMPLETED
        assert updated.finished_at is not None

    def test_fail_step(self) -> None:
        runner = WorkflowRunner()
        wf = runner.create(
            name="Test",
            steps=[
                WorkflowStep(agent_name="a"),
                WorkflowStep(agent_name="b"),
            ],
        )
        runner.start(wf.id)
        failed = runner.fail_step(wf.id, 0, error="timeout")
        assert failed is not None
        assert failed.status == WorkflowStatus.FAILED
        assert failed.steps[0].error == "timeout"
        assert failed.finished_at is not None

    def test_list_workflows(self) -> None:
        runner = WorkflowRunner()
        runner.create(name="A", steps=[WorkflowStep(agent_name="a")])
        runner.create(name="B", steps=[WorkflowStep(agent_name="b")])
        assert len(runner.list_workflows()) == 2

    def test_list_by_status(self) -> None:
        runner = WorkflowRunner()
        wf = runner.create(name="A", steps=[WorkflowStep(agent_name="a")])
        runner.create(name="B", steps=[WorkflowStep(agent_name="b")])
        runner.start(wf.id)
        assert len(runner.list_workflows(status=WorkflowStatus.RUNNING)) == 1
        assert len(runner.list_workflows(status=WorkflowStatus.PENDING)) == 1

    def test_remove(self) -> None:
        runner = WorkflowRunner()
        wf = runner.create(name="A", steps=[WorkflowStep(agent_name="a")])
        assert runner.remove(wf.id)
        assert runner.get(wf.id) is None

    def test_stats(self) -> None:
        runner = WorkflowRunner()
        wf1 = runner.create(name="A", steps=[WorkflowStep(agent_name="a")])
        runner.create(name="B", steps=[WorkflowStep(agent_name="b")])
        runner.start(wf1.id)
        stats = runner.stats
        assert stats["total"] == 2
        assert stats["running"] == 1
        assert stats["pending"] == 1


# ── 9. AutomationEngine ─────────────────────────────────────────


class TestAutomationEngine:
    def test_create(self) -> None:
        engine = AutomationEngine()
        assert engine.event_count == 0

    def test_add_schedule(self) -> None:
        engine = AutomationEngine()
        rule = engine.add_schedule(ScheduleRule(name="Test", agent_name="ops", cron_expr="@daily"))
        assert rule.name == "Test"
        assert engine.stats["schedules"]["total"] == 1

    def test_add_trigger(self) -> None:
        engine = AutomationEngine()
        trigger = engine.add_trigger(
            EventTrigger(
                name="Motion",
                trigger_type=TriggerType.DEVICE,
                agent_name="vision",
            )
        )
        assert trigger.name == "Motion"
        assert engine.stats["triggers"]["total"] == 1

    def test_create_workflow(self) -> None:
        engine = AutomationEngine()
        wf = engine.create_workflow(
            name="Chain",
            steps=[WorkflowStep(agent_name="a"), WorkflowStep(agent_name="b")],
        )
        assert wf.name == "Chain"
        assert engine.stats["workflows"]["total"] == 1

    def test_process_event_no_triggers(self) -> None:
        engine = AutomationEngine()
        event = AutomationEvent(event_type="test")
        actions = engine.process_event(event)
        assert actions == []
        assert engine.event_count == 1

    def test_process_event_matching(self) -> None:
        engine = AutomationEngine()
        engine.add_trigger(
            EventTrigger(
                name="Motion",
                trigger_type=TriggerType.DEVICE,
                agent_name="vision",
                conditions=[TriggerCondition(field="event_type", operator="eq", value="motion")],
                command_template="Kamerada harakat: {camera_id}",
            )
        )
        event = AutomationEvent(
            event_type="motion",
            source="camera.cam1",
            data={"camera_id": "cam1"},
        )
        actions = engine.process_event(event)
        assert len(actions) == 1
        assert actions[0].agent_name == "vision"
        assert "cam1" in actions[0].command
        assert actions[0].event_type == "motion"

    def test_process_event_no_match(self) -> None:
        engine = AutomationEngine()
        engine.add_trigger(
            EventTrigger(
                name="Motion",
                trigger_type=TriggerType.DEVICE,
                agent_name="vision",
                conditions=[TriggerCondition(field="event_type", operator="eq", value="motion")],
            )
        )
        event = AutomationEvent(event_type="noise")
        actions = engine.process_event(event)
        assert actions == []

    def test_process_event_multiple_triggers(self) -> None:
        engine = AutomationEngine()
        engine.add_trigger(
            EventTrigger(
                name="T1",
                trigger_type=TriggerType.SYSTEM,
                agent_name="ops",
            )
        )
        engine.add_trigger(
            EventTrigger(
                name="T2",
                trigger_type=TriggerType.SYSTEM,
                agent_name="ceo",
            )
        )
        event = AutomationEvent(event_type="alert")
        actions = engine.process_event(event)
        assert len(actions) == 2

    def test_process_event_records_fire(self) -> None:
        engine = AutomationEngine()
        trigger = engine.add_trigger(
            EventTrigger(
                name="T",
                trigger_type=TriggerType.SYSTEM,
                agent_name="ops",
            )
        )
        engine.process_event(AutomationEvent(event_type="test"))
        updated = engine.triggers.get(trigger.id)
        assert updated is not None
        assert updated.fire_count == 1

    def test_get_due_schedules(self) -> None:
        engine = AutomationEngine()
        engine.add_schedule(ScheduleRule(name="A", agent_name="a", cron_expr="@daily"))
        r2 = engine.add_schedule(ScheduleRule(name="B", agent_name="b", cron_expr="@hourly"))
        engine.scheduler.pause_rule(r2.id)
        due = engine.get_due_schedules()
        assert len(due) == 1

    def test_stats_integration(self) -> None:
        engine = AutomationEngine()
        engine.add_schedule(ScheduleRule(name="S", agent_name="a", cron_expr="@daily"))
        engine.add_trigger(
            EventTrigger(
                name="T",
                trigger_type=TriggerType.SYSTEM,
                agent_name="ops",
            )
        )
        engine.create_workflow(name="W", steps=[WorkflowStep(agent_name="a")])
        engine.process_event(AutomationEvent(event_type="x"))

        stats = engine.stats
        assert stats["schedules"]["total"] == 1
        assert stats["triggers"]["total"] == 1
        assert stats["workflows"]["total"] == 1
        assert stats["events_processed"]["total"] == 1


# ── 10. __init__ exports ────────────────────────────────────────


class TestAutomationInit:
    def test_all_exports(self) -> None:
        from zet.automation import __all__

        expected = {
            "AgentUnavailableError",
            "AutomationEngine",
            "EventTrigger",
            "ScheduleRule",
            "ScheduleStatus",
            "TriggerCondition",
            "TriggerType",
            "WorkflowChain",
            "WorkflowExecutor",
            "WorkflowStatus",
            "WorkflowStep",
            "is_due",
            "run_agent_command",
        }
        assert set(__all__) == expected


# ── 11. Xavfsizlik invariantlari ────────────────────────────────


class TestAutomationSecurity:
    def test_max_chain_length(self) -> None:
        """Zanjir uzunligi cheklangan."""
        runner = WorkflowRunner()
        long_steps = [WorkflowStep(agent_name=f"a{i}") for i in range(15)]
        with pytest.raises(ValueError):
            runner.create(name="TooLong", steps=long_steps)

    def test_invalid_cron_rejected(self) -> None:
        """Noto'g'ri cron ifodasi rad etiladi."""
        sched = Scheduler()
        with pytest.raises(ValueError):
            sched.add_rule(ScheduleRule(name="Bad", agent_name="ops", cron_expr="every 5 minutes"))

    def test_disabled_trigger_no_match(self) -> None:
        """O'chirilgan trigger ishga tushmaydi."""
        reg = TriggerRegistry()
        trigger = reg.add(
            EventTrigger(
                name="Off",
                trigger_type=TriggerType.SYSTEM,
                agent_name="ops",
            )
        )
        reg.disable(trigger.id)
        matches = reg.find_matching({"event_type": "any"})
        assert len(matches) == 0

    def test_max_fires_respected(self) -> None:
        """Maksimal ishga tushishlar chegarasi saqlanadi."""
        trigger = EventTrigger(
            name="Limited",
            trigger_type=TriggerType.SYSTEM,
            agent_name="ops",
            max_fires=1,
            fire_count=1,
        )
        assert not trigger.is_active
        assert not trigger.matches({"anything": "data"})

    def test_workflow_fail_stops_chain(self) -> None:
        """Bitta qadam muvaffaqiyatsiz bo'lsa — zanjir to'xtaydi."""
        runner = WorkflowRunner()
        wf = runner.create(
            name="Test",
            steps=[
                WorkflowStep(agent_name="a"),
                WorkflowStep(agent_name="b"),
                WorkflowStep(agent_name="c"),
            ],
        )
        runner.start(wf.id)
        failed = runner.fail_step(wf.id, 0, error="crash")
        assert failed is not None
        assert failed.status == WorkflowStatus.FAILED
        # Keyingi qadamlar PENDING da qoladi
        assert failed.steps[1].status == WorkflowStatus.PENDING
        assert failed.steps[2].status == WorkflowStatus.PENDING

    def test_schedule_max_runs_deactivates(self) -> None:
        """max_runs ga yetganda jadval o'z-o'zidan to'xtaydi."""
        sched = Scheduler()
        rule = sched.add_rule(
            ScheduleRule(name="Once", agent_name="ops", cron_expr="@daily", max_runs=1)
        )
        sched.record_run(rule.id)
        updated = sched.get_rule(rule.id)
        assert updated is not None
        assert not updated.is_active
