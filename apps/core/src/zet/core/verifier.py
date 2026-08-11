"""Verifier — natijani tekshiradi (Z1.11).

Uch xil verifikatsiya:
    1. deterministic — exit code, regex, schema tekshiruvi
    2. tool-based — tool orqali tekshirish (masalan: fayl mavjudligi)
    3. llm-judge — LLM bilan tekshirish (oxirgi chora, arzon model)

Bo'lim 1 uchun faqat deterministic verifikatsiya.

Bog'liq qarorlar:
    V-01 — har bir natija tekshiriladi
    V-35 — tekshiruv natijasi Verification modelida
"""

from __future__ import annotations

import re

import structlog

from zet.domain.plan import PlanStep
from zet.domain.tool import ToolResult, Verification

log = structlog.get_logger(__name__)


class Verifier:
    """Qadam natijasini kutilgan natijaga tekshiradi.

    Bo'lim 1: deterministic verifikatsiya (success flag + matn taqqoslash).
    """

    def verify_step(
        self,
        step: PlanStep,
        tool_result: ToolResult | None,
    ) -> Verification:
        """Qadam natijasini tekshiradi.

        Args:
            step: bajarilgan qadam
            tool_result: tool natijasi (None bo'lsa — fikrlash qadami)

        Returns:
            Verification
        """
        # Fikrlash qadami — tool yo'q
        if step.tool_name is None and tool_result is None:
            return Verification(
                ok=True,
                reason="Fikrlash qadami — tekshiruv kerak emas",
                auto=True,
                confidence=1.0,
            )

        # Tool natijasi yo'q lekin tool kerak edi
        if tool_result is None:
            return Verification(
                ok=False,
                reason=f"Qadam {step.position}: tool natijasi yo'q",
                auto=True,
                confidence=1.0,
            )

        # Tool muvaffaqiyatsiz
        if not tool_result.success:
            return Verification(
                ok=False,
                reason=f"Tool xato: {tool_result.error or 'nomalum'}",
                auto=True,
                confidence=1.0,
            )

        # expected_outcome mavjud — matn taqqoslash
        if step.expected_outcome:
            return self._verify_against_expectation(
                step.expected_outcome,
                tool_result,
            )

        # expected_outcome yo'q — faqat success flag
        return Verification(
            ok=True,
            reason="Tool muvaffaqiyatli bajarildi",
            auto=True,
            confidence=0.8,  # expected_outcome yo'q → pastroq ishonch
        )

    def verify_run(
        self,
        verifications: list[Verification],
    ) -> Verification:
        """Butun run natijasini umumlashtiradi.

        Bitta ham ok=False bo'lsa — run muvaffaqiyatsiz.
        """
        if not verifications:
            return Verification(
                ok=True,
                reason="Tekshiriladigan qadamlar yo'q",
                auto=True,
                confidence=1.0,
            )

        failed = [v for v in verifications if not v.ok]
        if failed:
            reasons = "; ".join(v.reason for v in failed)
            return Verification(
                ok=False,
                reason=f"{len(failed)} qadam muvaffaqiyatsiz: {reasons}",
                auto=True,
                confidence=min(v.confidence for v in verifications),
            )

        avg_confidence = sum(v.confidence for v in verifications) / len(verifications)
        return Verification(
            ok=True,
            reason=f"Barcha {len(verifications)} qadam muvaffaqiyatli",
            auto=True,
            confidence=round(avg_confidence, 2),
        )

    def _verify_against_expectation(
        self,
        expected: str,
        result: ToolResult,
    ) -> Verification:
        """Natijani kutilgan natijaga tekshiradi.

        Oddiy matn taqqoslash + regex.
        """
        output_str = str(result.output) if result.output is not None else ""

        # Kutilgan natija output'da bormi
        if expected.lower() in output_str.lower():
            return Verification(
                ok=True,
                reason=f"Kutilgan natija topildi: '{expected}'",
                auto=True,
                confidence=0.9,
            )

        # Regex sifatida sinash
        try:
            if re.search(expected, output_str, re.IGNORECASE):
                return Verification(
                    ok=True,
                    reason=f"Regex mos keldi: '{expected}'",
                    auto=True,
                    confidence=0.85,
                )
        except re.error:
            pass  # Regex emas — oddiy matn sifatida qaralsin

        return Verification(
            ok=False,
            reason=f"Kutilgan natija topilmadi: '{expected}' → '{output_str[:200]}'",
            auto=True,
            confidence=0.7,
        )
