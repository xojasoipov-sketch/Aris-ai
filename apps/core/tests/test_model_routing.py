"""BrainModelRouter testlari (JB-7).

`RoutingSignal → RoutingDecision` — deterministik, LLM chaqirilmaydi.
Har bir qoida ustuvorlik tartibida sinaladi.
"""

from __future__ import annotations

from zet.core.model_routing import BrainModelRouter, CognitiveStage, RoutingSignal
from zet.domain.enums import RiskLevel, TaskClass


class TestBrainModelRouter:
    def test_vision_namespace_routes_to_vision(self) -> None:
        router = BrainModelRouter()
        decision = router.route(
            RoutingSignal(stage=CognitiveStage.TASK_EXECUTION, tool="camera.snapshot")
        )
        assert decision.task_class == TaskClass.VISION
        assert "camera.snapshot" in decision.reason

    def test_desktop_namespace_routes_to_vision(self) -> None:
        router = BrainModelRouter()
        decision = router.route(
            RoutingSignal(stage=CognitiveStage.TASK_EXECUTION, tool="desktop.screenshot")
        )
        assert decision.task_class == TaskClass.VISION

    def test_coding_namespace_routes_to_coding(self) -> None:
        router = BrainModelRouter()
        decision = router.route(
            RoutingSignal(stage=CognitiveStage.TASK_EXECUTION, tool="github.write")
        )
        assert decision.task_class == TaskClass.CODING
        assert "github.write" in decision.reason

    def test_high_risk_routes_to_complex(self) -> None:
        """`instagram.*` — kod/vizual namespace emas, HIGH risk qoidasi yutadi."""
        router = BrainModelRouter()
        decision = router.route(
            RoutingSignal(
                stage=CognitiveStage.TASK_EXECUTION,
                tool="instagram.publish_photo",
                risk_level=RiskLevel.HIGH,
            )
        )
        assert decision.task_class == TaskClass.COMPLEX
        assert "high" in decision.reason.lower()

    def test_critical_risk_routes_to_complex(self) -> None:
        router = BrainModelRouter()
        decision = router.route(
            RoutingSignal(stage=CognitiveStage.TASK_EXECUTION, risk_level=RiskLevel.CRITICAL)
        )
        assert decision.task_class == TaskClass.COMPLEX

    def test_long_text_routes_to_complex(self) -> None:
        router = BrainModelRouter()
        decision = router.route(
            RoutingSignal(stage=CognitiveStage.TASK_EXECUTION, text_length=5000)
        )
        assert decision.task_class == TaskClass.COMPLEX
        assert "5000" in decision.reason

    def test_planning_stage_routes_to_complex(self) -> None:
        router = BrainModelRouter()
        decision = router.route(RoutingSignal(stage=CognitiveStage.PLANNING))
        assert decision.task_class == TaskClass.COMPLEX

    def test_evaluation_stage_routes_to_complex(self) -> None:
        router = BrainModelRouter()
        decision = router.route(RoutingSignal(stage=CognitiveStage.EVALUATION))
        assert decision.task_class == TaskClass.COMPLEX

    def test_recovery_stage_routes_to_complex(self) -> None:
        router = BrainModelRouter()
        decision = router.route(RoutingSignal(stage=CognitiveStage.RECOVERY))
        assert decision.task_class == TaskClass.COMPLEX

    def test_intent_stage_routes_to_simple(self) -> None:
        router = BrainModelRouter()
        decision = router.route(RoutingSignal(stage=CognitiveStage.INTENT))
        assert decision.task_class == TaskClass.SIMPLE

    def test_default_task_execution_routes_to_normal(self) -> None:
        router = BrainModelRouter()
        decision = router.route(
            RoutingSignal(stage=CognitiveStage.TASK_EXECUTION, tool="web.search")
        )
        assert decision.task_class == TaskClass.NORMAL

    def test_vision_takes_priority_over_high_risk(self) -> None:
        """Ustuvorlik tartibi: vision namespace risk darajasidan OLDIN tekshiriladi."""
        router = BrainModelRouter()
        decision = router.route(
            RoutingSignal(
                stage=CognitiveStage.TASK_EXECUTION,
                tool="camera.snapshot",
                risk_level=RiskLevel.HIGH,
            )
        )
        assert decision.task_class == TaskClass.VISION

    def test_every_decision_has_nonempty_reason(self) -> None:
        router = BrainModelRouter()
        signals = [
            RoutingSignal(stage=CognitiveStage.INTENT),
            RoutingSignal(stage=CognitiveStage.PLANNING),
            RoutingSignal(stage=CognitiveStage.TASK_EXECUTION, tool="note.write"),
            RoutingSignal(stage=CognitiveStage.TASK_EXECUTION, tool="github.write"),
            RoutingSignal(stage=CognitiveStage.TASK_EXECUTION, tool="camera.snapshot"),
            RoutingSignal(stage=CognitiveStage.RECOVERY),
        ]
        for signal in signals:
            decision = router.route(signal)
            assert decision.reason.strip() != ""
