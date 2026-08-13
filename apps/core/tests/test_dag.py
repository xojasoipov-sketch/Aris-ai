"""`plan_to_dag` — Kahn algoritmi bilan bosqichlarga bo'lish testlari.

`Plan._validate_dag`ni chetlab o'tish uchun testlar xom
`list[PlanStep]` bilan ishlaydi (funksiya `Plan`ni emas, `Sequence`ni
qabul qiladi). Bu — sikl testini alohida yozish uchun kerak.
"""

from __future__ import annotations

import pytest

from zet.core.dag import plan_to_dag
from zet.domain.plan import PlanStep, PlanValidationError


def _step(position: int, depends_on: list[int] | None = None) -> PlanStep:
    return PlanStep(
        position=position,
        description=f"q{position}",
        depends_on=list(depends_on or []),
    )


class TestPlanToDag:
    def test_plan_to_dag_empty(self) -> None:
        assert plan_to_dag([]) == []

    def test_plan_to_dag_single_step(self) -> None:
        s = _step(0)
        batches = plan_to_dag([s])
        assert batches == [[s]]

    def test_plan_to_dag_linear_chain_backward_compat(self) -> None:
        """Chiziqli zanjir 0→1→2→3 — bugungi ketma-ket ish bilan bir xil."""
        steps = [
            _step(0),
            _step(1, [0]),
            _step(2, [1]),
            _step(3, [2]),
        ]
        batches = plan_to_dag(steps)
        assert [[s.position for s in b] for b in batches] == [[0], [1], [2], [3]]

    def test_plan_to_dag_all_independent_parallel(self) -> None:
        """Uchta mustaqil qadam — bitta bosqichda barchasi."""
        steps = [_step(0), _step(1), _step(2)]
        batches = plan_to_dag(steps)
        assert len(batches) == 1
        assert [s.position for s in batches[0]] == [0, 1, 2]

    def test_plan_to_dag_diamond(self) -> None:
        """0 → {1, 2} → 3 diamond."""
        steps = [
            _step(0),
            _step(1, [0]),
            _step(2, [0]),
            _step(3, [1, 2]),
        ]
        batches = plan_to_dag(steps)
        assert [[s.position for s in b] for b in batches] == [[0], [1, 2], [3]]

    def test_plan_to_dag_multiple_roots_join(self) -> None:
        """{0, 1} → 2."""
        steps = [_step(0), _step(1), _step(2, [0, 1])]
        batches = plan_to_dag(steps)
        assert [[s.position for s in b] for b in batches] == [[0, 1], [2]]

    def test_plan_to_dag_complex_mixed_dag(self) -> None:
        """0; 1,2←0; 3←1; 4←2; 5←3,4; 6 mustaqil."""
        steps = [
            _step(0),
            _step(1, [0]),
            _step(2, [0]),
            _step(3, [1]),
            _step(4, [2]),
            _step(5, [3, 4]),
            _step(6),
        ]
        batches = plan_to_dag(steps)
        levels = [[s.position for s in b] for b in batches]

        # Har bir qadam bir marta uchraydi.
        seen = [pos for b in levels for pos in b]
        assert sorted(seen) == [0, 1, 2, 3, 4, 5, 6]

        # Level partitsiyasi kutilganidek:
        #  L0 = {0, 6} (mustaqillar), L1 = {1, 2}, L2 = {3, 4}, L3 = {5}.
        assert levels == [[0, 6], [1, 2], [3, 4], [5]]

        # Har bir bosqich ichida position bo'yicha tartiblangan.
        for batch in levels:
            assert batch == sorted(batch)

    def test_plan_to_dag_cycle_detection_raises(self) -> None:
        """`Plan._validate_dag`ni chetlab, xom sikl qurish orqali test."""
        # `Plan` orqali qurish `dep >= position` ni bloklaydi, shuning uchun
        # xom PlanStep ro'yxatini yasab, `Plan`ga o'ramaymiz.
        s0 = PlanStep(position=0, description="a", depends_on=[1])
        s1 = PlanStep(position=1, description="b", depends_on=[0])

        with pytest.raises(PlanValidationError, match=r"sikl|Kahn"):
            plan_to_dag([s0, s1])

    def test_plan_to_dag_within_batch_sorted_by_position(self) -> None:
        """Position bo'yicha aralash tartibda qurilgan mustaqil qadamlar."""
        steps = [_step(2), _step(0), _step(3), _step(1)]
        batches = plan_to_dag(steps)
        assert len(batches) == 1
        assert [s.position for s in batches[0]] == [0, 1, 2, 3]
