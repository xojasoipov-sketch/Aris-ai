"""Z1.11 — Verifier testlari.

Tekshiriladi:
    - Fikrlash qadami (tool_name=None) → ok=True
    - Tool natijasi yo'q lekin tool kerak → ok=False
    - Tool muvaffaqiyatsiz → ok=False
    - Tool muvaffaqiyatli, expected_outcome yo'q → ok=True, confidence=0.8
    - Tool muvaffaqiyatli, expected_outcome topildi → ok=True
    - Tool muvaffaqiyatli, expected_outcome regex bilan → ok=True
    - Tool muvaffaqiyatli, expected_outcome topilmadi → ok=False
    - verify_run: barcha muvaffaqiyatli → ok=True
    - verify_run: bitta muvaffaqiyatsiz → ok=False
    - verify_run: bo'sh ro'yxat → ok=True
"""

from __future__ import annotations

from zet.core.verifier import Verifier
from zet.domain.enums import PermissionLevel
from zet.domain.plan import PlanStep
from zet.domain.tool import ToolResult, Verification

# ── Yordamchilar ────────────────────────────────────────────────────


def _step(
    position: int = 0,
    tool_name: str | None = "test.read",
    expected_outcome: str | None = None,
) -> PlanStep:
    return PlanStep(
        position=position,
        description="Test qadam",
        tool_name=tool_name,
        permission_required=PermissionLevel.READ,
        expected_outcome=expected_outcome,
    )


def _result(
    success: bool = True,
    output: object = "natija",
    error: str | None = None,
) -> ToolResult:
    return ToolResult(
        tool_name="test.read",
        success=success,
        output=output,
        error=error,
    )


# ── Testlar ─────────────────────────────────────────────────────────


class TestVerifyStep:
    def test_thinking_step(self) -> None:
        """tool_name=None, tool_result=None → ok=True."""
        v = Verifier()
        result = v.verify_step(_step(tool_name=None), None)

        assert result.ok is True
        assert result.auto is True
        assert result.confidence == 1.0

    def test_tool_result_missing(self) -> None:
        """tool kerak, lekin natija yo'q → ok=False."""
        v = Verifier()
        result = v.verify_step(_step(), None)

        assert result.ok is False
        assert "tool natijasi" in result.reason

    def test_tool_failed(self) -> None:
        """Tool muvaffaqiyatsiz → ok=False."""
        v = Verifier()
        result = v.verify_step(
            _step(),
            _result(success=False, error="xato yuz berdi"),
        )

        assert result.ok is False
        assert "xato" in result.reason.lower()

    def test_success_no_expectation(self) -> None:
        """Muvaffaqiyatli, expected_outcome yo'q → ok=True, confidence=0.8."""
        v = Verifier()
        result = v.verify_step(_step(), _result())

        assert result.ok is True
        assert result.confidence == 0.8

    def test_expected_outcome_found(self) -> None:
        """Kutilgan natija output'da topildi."""
        v = Verifier()
        step = _step(expected_outcome="natija")
        result = v.verify_step(step, _result(output="bu natija matn"))

        assert result.ok is True
        assert result.confidence == 0.9

    def test_expected_outcome_case_insensitive(self) -> None:
        """Kutilgan natija case-insensitive topiladi."""
        v = Verifier()
        step = _step(expected_outcome="NATIJA")
        result = v.verify_step(step, _result(output="bu natija matn"))

        assert result.ok is True

    def test_expected_outcome_regex(self) -> None:
        """Kutilgan natija regex bilan topiladi."""
        v = Verifier()
        step = _step(expected_outcome=r"\d{3}")
        result = v.verify_step(step, _result(output="kod: 200"))

        assert result.ok is True
        assert result.confidence == 0.85

    def test_expected_outcome_not_found(self) -> None:
        """Kutilgan natija topilmadi → ok=False."""
        v = Verifier()
        step = _step(expected_outcome="maxfiy_so'z")
        result = v.verify_step(step, _result(output="boshqa matn"))

        assert result.ok is False
        assert "topilmadi" in result.reason

    def test_output_none_with_expectation(self) -> None:
        """output=None, lekin expected_outcome bor → ok=False."""
        v = Verifier()
        step = _step(expected_outcome="natija")
        result = v.verify_step(step, _result(output=None))

        assert result.ok is False

    def test_invalid_regex_falls_through(self) -> None:
        """Yaroqsiz regex → oddiy matn sifatida qaraladi."""
        v = Verifier()
        step = _step(expected_outcome="[invalid")
        result = v.verify_step(step, _result(output="boshqa matn"))

        assert result.ok is False


class TestVerifyRun:
    def test_all_success(self) -> None:
        """Barcha muvaffaqiyatli → ok=True."""
        v = Verifier()
        verifications = [
            Verification(ok=True, reason="ok", auto=True, confidence=0.9),
            Verification(ok=True, reason="ok", auto=True, confidence=0.8),
        ]
        result = v.verify_run(verifications)

        assert result.ok is True
        assert result.confidence == 0.85

    def test_one_failed(self) -> None:
        """Bitta muvaffaqiyatsiz → ok=False."""
        v = Verifier()
        verifications = [
            Verification(ok=True, reason="ok", auto=True, confidence=0.9),
            Verification(ok=False, reason="xato", auto=True, confidence=0.7),
        ]
        result = v.verify_run(verifications)

        assert result.ok is False
        assert "1 qadam" in result.reason

    def test_empty_list(self) -> None:
        """Bo'sh ro'yxat → ok=True."""
        v = Verifier()
        result = v.verify_run([])

        assert result.ok is True
        assert result.confidence == 1.0

    def test_multiple_failures(self) -> None:
        """Bir nechta muvaffaqiyatsiz → ok=False, sabablari birlashtirilgan."""
        v = Verifier()
        verifications = [
            Verification(ok=False, reason="xato1", auto=True, confidence=0.5),
            Verification(ok=False, reason="xato2", auto=True, confidence=0.6),
        ]
        result = v.verify_run(verifications)

        assert result.ok is False
        assert "2 qadam" in result.reason
        assert result.confidence == 0.5  # min

    def test_confidence_average(self) -> None:
        """Confidence o'rtacha hisoblanadi."""
        v = Verifier()
        verifications = [
            Verification(ok=True, reason="ok", auto=True, confidence=1.0),
            Verification(ok=True, reason="ok", auto=True, confidence=0.8),
            Verification(ok=True, reason="ok", auto=True, confidence=0.6),
        ]
        result = v.verify_run(verifications)

        assert result.ok is True
        assert result.confidence == 0.8
