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
    async def test_thinking_step(self) -> None:
        """tool_name=None, tool_result=None → ok=True."""
        v = Verifier()
        result = await v.verify_step(_step(tool_name=None), None)

        assert result.ok is True
        assert result.auto is True
        assert result.confidence == 1.0

    async def test_tool_result_missing(self) -> None:
        """tool kerak, lekin natija yo'q → ok=False."""
        v = Verifier()
        result = await v.verify_step(_step(), None)

        assert result.ok is False
        assert "tool natijasi" in result.reason

    async def test_tool_failed(self) -> None:
        """Tool muvaffaqiyatsiz → ok=False."""
        v = Verifier()
        result = await v.verify_step(
            _step(),
            _result(success=False, error="xato yuz berdi"),
        )

        assert result.ok is False
        assert "xato" in result.reason.lower()

    async def test_success_no_expectation(self) -> None:
        """Muvaffaqiyatli, expected_outcome yo'q → ok=True, confidence=0.8."""
        v = Verifier()
        result = await v.verify_step(_step(), _result())

        assert result.ok is True
        assert result.confidence == 0.8

    async def test_expected_outcome_found(self) -> None:
        """Kutilgan natija output'da topildi."""
        v = Verifier()
        step = _step(expected_outcome="natija")
        result = await v.verify_step(step, _result(output="bu natija matn"))

        assert result.ok is True
        assert result.confidence == 0.9

    async def test_expected_outcome_case_insensitive(self) -> None:
        """Kutilgan natija case-insensitive topiladi."""
        v = Verifier()
        step = _step(expected_outcome="NATIJA")
        result = await v.verify_step(step, _result(output="bu natija matn"))

        assert result.ok is True

    async def test_expected_outcome_regex(self) -> None:
        """Kutilgan natija regex bilan topiladi."""
        v = Verifier()
        step = _step(expected_outcome=r"\d{3}")
        result = await v.verify_step(step, _result(output="kod: 200"))

        assert result.ok is True
        assert result.confidence == 0.85

    async def test_expected_outcome_not_found(self) -> None:
        """Kutilgan natija topilmadi → ok=False."""
        v = Verifier()
        step = _step(expected_outcome="maxfiy_so'z")
        result = await v.verify_step(step, _result(output="boshqa matn"))

        assert result.ok is False
        assert "topilmadi" in result.reason

    async def test_output_none_with_expectation(self) -> None:
        """output=None, lekin expected_outcome bor → ok=False."""
        v = Verifier()
        step = _step(expected_outcome="natija")
        result = await v.verify_step(step, _result(output=None))

        assert result.ok is False

    async def test_invalid_regex_falls_through(self) -> None:
        """Yaroqsiz regex → oddiy matn sifatida qaraladi."""
        v = Verifier()
        step = _step(expected_outcome="[invalid")
        result = await v.verify_step(step, _result(output="boshqa matn"))

        assert result.ok is False


class TestVerifyRun:
    async def test_all_success(self) -> None:
        """Barcha muvaffaqiyatli → ok=True."""
        v = Verifier()
        verifications = [
            Verification(ok=True, reason="ok", auto=True, confidence=0.9),
            Verification(ok=True, reason="ok", auto=True, confidence=0.8),
        ]
        result = v.verify_run(verifications)

        assert result.ok is True
        assert result.confidence == 0.85

    async def test_one_failed(self) -> None:
        """Bitta muvaffaqiyatsiz → ok=False."""
        v = Verifier()
        verifications = [
            Verification(ok=True, reason="ok", auto=True, confidence=0.9),
            Verification(ok=False, reason="xato", auto=True, confidence=0.7),
        ]
        result = v.verify_run(verifications)

        assert result.ok is False
        assert "1 qadam" in result.reason

    async def test_empty_list(self) -> None:
        """Bo'sh ro'yxat → ok=True."""
        v = Verifier()
        result = v.verify_run([])

        assert result.ok is True
        assert result.confidence == 1.0

    async def test_multiple_failures(self) -> None:
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

    async def test_confidence_average(self) -> None:
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


class TestDescriptionsAreNotLiteralChecks:
    """Uzun `expected_outcome` — tavsif, so'zma-so'z shablon emas.

    Jonli misolda `video.learn` 18.8 soniyada to'liq natija qaytardi
    (`tool.ok`, 5 asosiy fikr, 7 atama), lekin Planner yozgan jumla
    JSON chiqish ichida uchramagani uchun run FAILED deb belgilandi.
    Ega to'g'ri natijani oldi-yu, ZET uni "muvaffaqiyatsiz" dedi.
    """

    async def test_long_description_does_not_fail_a_successful_tool(self) -> None:
        v = Verifier()
        step = _step(
            expected_outcome="YouTube videosidan foydali ma'lumotlarni olish va ajratib olish"
        )

        result = await v.verify_step(step, _result(output={"title": "Neyron tarmoqlar"}))

        assert result.ok is True
        assert "tasdiqlanmadi" in result.reason
        assert result.confidence < 0.8

    async def test_short_literal_still_fails_when_absent(self) -> None:
        """Qisqa shablon haqiqiy tekshiruv bo'lib qoladi."""
        v = Verifier()
        step = _step(expected_outcome="maxfiy_so'z")

        result = await v.verify_step(step, _result(output="boshqa matn"))

        assert result.ok is False

    async def test_boundary_three_words_is_still_a_literal(self) -> None:
        """Chegara aniq: 3 so'z — shablon, 4 so'z — tavsif."""
        v = Verifier()

        three = await v.verify_step(_step(expected_outcome="bir ikki uch"), _result(output="x"))
        four = await v.verify_step(_step(expected_outcome="bir ikki uch tort"), _result(output="x"))

        assert three.ok is False
        assert four.ok is True

    async def test_a_matching_long_description_is_still_a_pass(self) -> None:
        """Tasodifan mos kelsa — ishonch yuqori bo'ladi."""
        v = Verifier()
        step = _step(expected_outcome="natija muvaffaqiyatli tayyor boldi")

        result = await v.verify_step(step, _result(output="natija muvaffaqiyatli tayyor boldi"))

        assert result.ok is True
        assert result.confidence >= 0.85


class TestLLMJudgeTier:
    """Uzun jonli-tildagi expected_outcome uchun LLM-judge (V-01).

    Ilgari confidence=0.6 bilan avtomatik 'ok' bo'lardi, hech qanday
    tekshiruv yo'q edi. Endi LLM-judge ulangan bo'lsa haqiqiy tekshiruv."""

    class _FakeJudge:
        """Minimal LLMProvider - `complete()` deterministik javob qaytaradi."""

        def __init__(self, verdict: str) -> None:
            self.verdict = verdict
            self.calls: list[dict[str, object]] = []

        async def complete(self, *, messages, system=None, max_tokens=None, **_):  # type: ignore[no-untyped-def]
            self.calls.append({"messages": messages, "system": system})

            class _R:
                text = self.verdict

            return _R()

    async def test_llm_judge_ok_yields_pass(self) -> None:
        judge = self._FakeJudge("OK: matnda tavsifning barcha nuqtalari bor")
        v = Verifier(llm_judge_provider=judge)
        step = _step(expected_outcome="YouTube videosidan foydali malumot olish")
        result = await v.verify_step(step, _result(output={"summary": "5 key points"}))

        assert result.ok is True
        assert "LLM-judge" in result.reason
        assert result.confidence == 0.75
        assert judge.calls, "judge chaqirilmagan"

    async def test_llm_judge_fail_yields_fail(self) -> None:
        judge = self._FakeJudge("FAIL: chiqishda kutilgan ma'lumot yo'q")
        v = Verifier(llm_judge_provider=judge)
        step = _step(expected_outcome="Sotuv statistikasi 30 kun uchun")
        result = await v.verify_step(step, _result(output={"nothing": "here"}))

        assert result.ok is False
        assert "LLM-judge" in result.reason
        assert result.confidence == 0.75

    async def test_llm_judge_bad_format_falls_open(self) -> None:
        """Format buzilgan javob → eski xatti-harakat (fail-open)."""
        judge = self._FakeJudge("MAYBE — bilmayman")
        v = Verifier(llm_judge_provider=judge)
        step = _step(expected_outcome="uzun tavsif jumlasi ko'p so'zli")
        result = await v.verify_step(step, _result(output="x"))

        # LLM-judge yiqildi → eski yo'l: ok=True, confidence=0.6
        assert result.ok is True
        assert result.confidence == 0.6

    async def test_llm_judge_exception_falls_open(self) -> None:
        """LLM istisno ko'tarsa — eski xatti-harakat, run yiqilmaydi."""

        class _ExplodingJudge:
            async def complete(self, **_):  # type: ignore[no-untyped-def]
                msg = "429 rate limit"
                raise RuntimeError(msg)

        v = Verifier(llm_judge_provider=_ExplodingJudge())
        step = _step(expected_outcome="uzun tavsif jumlasi ko'p so'zli")
        result = await v.verify_step(step, _result(output="x"))

        assert result.ok is True
        assert result.confidence == 0.6

    async def test_llm_judge_not_called_for_short_literal(self) -> None:
        """Qisqa shablon — LLM-judge chaqirilmaydi (arzon bo'lsa ham keraksiz)."""
        judge = self._FakeJudge("OK")
        v = Verifier(llm_judge_provider=judge)
        step = _step(expected_outcome="maxfiy")
        await v.verify_step(step, _result(output="boshqa"))

        assert not judge.calls, "qisqa shablonda judge chaqirilmasligi kerak edi"

    async def test_llm_judge_not_called_when_literal_matches(self) -> None:
        """Literal topilgan bo'lsa — LLM-judge ortiqcha."""
        judge = self._FakeJudge("OK")
        v = Verifier(llm_judge_provider=judge)
        step = _step(expected_outcome="natija muvaffaqiyatli tayyor boldi")
        await v.verify_step(step, _result(output="natija muvaffaqiyatli tayyor boldi"))

        assert not judge.calls
