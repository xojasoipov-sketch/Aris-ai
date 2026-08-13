"""MissionStatus holat mashinasi testlari (Bo'lim 2, §2.2).

NEGA. Mission ilgari yo'q edi va agentlar bitta buyruq siklidan
ko'proq nima qilishni bilmasdi ("kecha qilingan saytni davom ettir"
holati mumkin emasdi). Bu testlar Mission fazalari orasidagi ruxsat
etilgan o'tishlarni (RECEIVED → UNDERSTANDING → ... → COMPLETED)
qulflaydi va terminal holatlardan chiqib bo'lmasligini isbotlaydi.
"""

from __future__ import annotations

from zet.domain.enums import MISSION_TRANSITIONS, MissionStatus


class TestMissionStatusTransitions:
    def test_received_can_start_understanding(self) -> None:
        assert MissionStatus.RECEIVED.can_transition_to(MissionStatus.UNDERSTANDING)

    def test_understanding_cannot_skip_to_planning(self) -> None:
        assert not MissionStatus.UNDERSTANDING.can_transition_to(MissionStatus.PLANNING)

    def test_executing_can_recover(self) -> None:
        assert MissionStatus.EXECUTING.can_transition_to(MissionStatus.RECOVERING)

    def test_completed_is_terminal(self) -> None:
        assert MissionStatus.COMPLETED.is_terminal
        for target in MissionStatus:
            assert not MissionStatus.COMPLETED.can_transition_to(target)

    def test_terminal_states(self) -> None:
        assert MissionStatus.COMPLETED.is_terminal
        assert MissionStatus.FAILED.is_terminal
        assert MissionStatus.CANCELLED.is_terminal
        assert not MissionStatus.RECEIVED.is_terminal
        assert not MissionStatus.EXECUTING.is_terminal

    def test_every_status_has_transition_entry(self) -> None:
        assert set(MISSION_TRANSITIONS) == set(MissionStatus)

    def test_every_non_terminal_can_be_cancelled(self) -> None:
        """Emergency cancel (V-33 bilan bir xil siyosat) — istalgan faol holatdan."""
        for status in MissionStatus:
            if not status.is_terminal:
                assert status.can_transition_to(MissionStatus.CANCELLED), status

    def test_verifying_can_go_back_to_recovering(self) -> None:
        assert MissionStatus.VERIFYING.can_transition_to(MissionStatus.RECOVERING)

    def test_recovering_can_restart_executing(self) -> None:
        assert MissionStatus.RECOVERING.can_transition_to(MissionStatus.EXECUTING)
