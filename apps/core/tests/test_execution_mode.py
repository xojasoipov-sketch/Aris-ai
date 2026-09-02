"""ExecutionModeClassifier testlari (JB-8).

Spetsifikatsiyaning §17'dagi 7 ta qabul testi so'zma-so'z shu yerda —
"Workflow har doim yoqilgan emas" tamoyilining asosiy dalili.
"""

from __future__ import annotations

from zet.core.execution_mode import ExecutionMode, ExecutionModeClassifier
from zet.domain.command import Intent


def _intent(
    *,
    request_kind: str = "command",
    requires_tools: list[str] | None = None,
    text: str = "",
) -> Intent:
    return Intent(
        action="test",
        request_kind=request_kind,
        requires_tools=requires_tools or [],
        original_text=text,
    )


class TestSpecAcceptanceScenarios:
    """JB-8 §17 — 7 ta test, aynan spetsifikatsiyadagi kabi."""

    def test_1_simple_math_question_is_direct_response(self) -> None:
        classifier = ExecutionModeClassifier()
        intent = _intent(request_kind="chat", text="2 + 2 nechchi?")

        decision = classifier.classify(intent)

        assert decision.mode == ExecutionMode.DIRECT_RESPONSE

    def test_2_check_telegram_is_direct_tool_not_workflow(self) -> None:
        classifier = ExecutionModeClassifier()
        intent = _intent(
            request_kind="command",
            requires_tools=["telegram.read"],
            text="Telegramimni tekshir.",
        )

        decision = classifier.classify(intent)

        assert decision.mode in (ExecutionMode.DIRECT_TOOL, ExecutionMode.MISSION)
        assert decision.mode not in (ExecutionMode.WORKFLOW, ExecutionMode.BACKGROUND_WORKFLOW)

    def test_3_github_audit_is_task_graph_not_workflow(self) -> None:
        classifier = ExecutionModeClassifier()
        intent = _intent(
            request_kind="goal",
            requires_tools=["github.read", "code_analysis"],
            text="GitHub projectimni audit qil.",
        )

        decision = classifier.classify(intent)

        assert decision.mode in (ExecutionMode.TASK_GRAPH, ExecutionMode.MISSION)
        assert decision.mode not in (ExecutionMode.WORKFLOW, ExecutionMode.BACKGROUND_WORKFLOW)

    def test_4_explicit_workflow_request_is_workflow(self) -> None:
        classifier = ExecutionModeClassifier()
        intent = _intent(request_kind="goal", text="Shuni workflow qilib bajar.")

        decision = classifier.classify(intent)

        assert decision.mode == ExecutionMode.WORKFLOW

    def test_5_recurring_request_is_background_workflow(self) -> None:
        classifier = ExecutionModeClassifier()
        intent = _intent(
            request_kind="goal",
            requires_tools=["telegram.read"],
            text="Har kuni soat 9 da Telegramni tekshir.",
        )

        decision = classifier.classify(intent)

        assert decision.mode == ExecutionMode.BACKGROUND_WORKFLOW
        assert decision.persistent is True

    def test_6_explicit_one_time_disables_workflow(self) -> None:
        classifier = ExecutionModeClassifier()
        intent = _intent(
            request_kind="command",
            requires_tools=["telegram.read"],
            text="Faqat hozir bir marta tekshir.",
        )

        decision = classifier.classify(intent)

        assert decision.mode not in (
            ExecutionMode.WORKFLOW,
            ExecutionMode.BACKGROUND_WORKFLOW,
            ExecutionMode.WORKFLOW_COMMAND,
        )

    def test_7_resume_workflow_command_is_workflow_command(self) -> None:
        classifier = ExecutionModeClassifier()
        intent = _intent(request_kind="goal", text="Workflowni davom ettir.")

        decision = classifier.classify(intent)

        assert decision.mode == ExecutionMode.WORKFLOW_COMMAND


class TestWorkflowCommandRecognition:
    def test_list_workflows(self) -> None:
        classifier = ExecutionModeClassifier()
        decision = classifier.classify(_intent(text="Workflowlarimni ko'rsat."))
        assert decision.mode == ExecutionMode.WORKFLOW_COMMAND

    def test_workflow_status(self) -> None:
        classifier = ExecutionModeClassifier()
        decision = classifier.classify(_intent(text="Oxirgi workflow holati nima?"))
        assert decision.mode == ExecutionMode.WORKFLOW_COMMAND

    def test_pause_workflow(self) -> None:
        classifier = ExecutionModeClassifier()
        decision = classifier.classify(_intent(text="Workflowni to'xtat."))
        assert decision.mode == ExecutionMode.WORKFLOW_COMMAND

    def test_cancel_workflow(self) -> None:
        classifier = ExecutionModeClassifier()
        decision = classifier.classify(_intent(text="Workflowni bekor qil."))
        assert decision.mode == ExecutionMode.WORKFLOW_COMMAND

    def test_restart_workflow(self) -> None:
        classifier = ExecutionModeClassifier()
        decision = classifier.classify(_intent(text="Workflowni qayta ishga tushir."))
        assert decision.mode == ExecutionMode.WORKFLOW_COMMAND

    def test_workflow_command_is_marked_persistent(self) -> None:
        classifier = ExecutionModeClassifier()
        decision = classifier.classify(_intent(text="Workflowni to'xtat."))
        assert decision.persistent is True


class TestExplicitWorkflowCreation:
    def test_step_by_step_persistent_process_without_word_workflow(self) -> None:
        classifier = ExecutionModeClassifier()
        decision = classifier.classify(
            _intent(
                request_kind="goal",
                text="Bu ishni bosqichma-bosqich yuritib, har bosqich natijasini saqla.",
            )
        )
        assert decision.mode == ExecutionMode.WORKFLOW

    def test_weekly_recurring_is_background_not_plain_workflow(self) -> None:
        classifier = ExecutionModeClassifier()
        decision = classifier.classify(
            _intent(request_kind="goal", text="Har hafta shu jarayonni avtomatik bajar.")
        )
        assert decision.mode == ExecutionMode.BACKGROUND_WORKFLOW


class TestAvoidWorkflowPriority:
    def test_avoid_phrase_beats_recurring_signal(self) -> None:
        """`_AVOID_WORKFLOW_PHRASES` HAMMA workflow signallaridan ustun."""
        classifier = ExecutionModeClassifier()
        decision = classifier.classify(
            _intent(
                request_kind="command",
                requires_tools=["telegram.read"],
                text="Workflow kerak emas, faqat hozir bir marta tekshir.",
            )
        )
        assert decision.mode not in (
            ExecutionMode.WORKFLOW,
            ExecutionMode.BACKGROUND_WORKFLOW,
            ExecutionMode.WORKFLOW_COMMAND,
        )


class TestMinimalExecutionPrinciple:
    """JB-8 §5 — eng oddiy yetarli mexanizm tanlanadi."""

    def test_chat_is_direct_response(self) -> None:
        classifier = ExecutionModeClassifier()
        decision = classifier.classify(_intent(request_kind="chat"))
        assert decision.mode == ExecutionMode.DIRECT_RESPONSE

    def test_command_without_tools_is_direct_response(self) -> None:
        classifier = ExecutionModeClassifier()
        decision = classifier.classify(_intent(request_kind="command", requires_tools=[]))
        assert decision.mode == ExecutionMode.DIRECT_RESPONSE

    def test_command_with_one_tool_is_direct_tool(self) -> None:
        classifier = ExecutionModeClassifier()
        decision = classifier.classify(
            _intent(request_kind="command", requires_tools=["web.search"])
        )
        assert decision.mode == ExecutionMode.DIRECT_TOOL

    def test_command_with_two_tools_is_task_graph(self) -> None:
        classifier = ExecutionModeClassifier()
        decision = classifier.classify(
            _intent(request_kind="command", requires_tools=["web.search", "note.write"])
        )
        assert decision.mode == ExecutionMode.TASK_GRAPH

    def test_goal_with_one_tool_is_mission(self) -> None:
        classifier = ExecutionModeClassifier()
        decision = classifier.classify(
            _intent(request_kind="goal", requires_tools=["web.search"])
        )
        assert decision.mode == ExecutionMode.MISSION
        assert decision.persistent is True

    def test_goal_with_two_tools_is_task_graph(self) -> None:
        classifier = ExecutionModeClassifier()
        decision = classifier.classify(
            _intent(request_kind="goal", requires_tools=["web.search", "note.write"])
        )
        assert decision.mode == ExecutionMode.TASK_GRAPH


class TestExplainability:
    """JB-8 §9/§16 — har bir qaror tushuntirilgan bo'lishi shart."""

    def test_every_decision_has_nonempty_reason(self) -> None:
        classifier = ExecutionModeClassifier()
        scenarios = [
            _intent(request_kind="chat"),
            _intent(request_kind="command", requires_tools=["web.search"]),
            _intent(request_kind="goal", requires_tools=["a", "b"]),
            _intent(text="Workflow qilib bajar."),
            _intent(text="Har kuni tekshir."),
            _intent(text="Workflowni bekor qil."),
        ]
        for intent in scenarios:
            decision = classifier.classify(intent)
            assert decision.reason.strip() != ""
