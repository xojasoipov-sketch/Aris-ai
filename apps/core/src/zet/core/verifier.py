"""Verifier — natijani tekshiradi (Z1.11).

Uch xil verifikatsiya (V-01):
    1. deterministic — success flag, matn/regex taqqoslash
    2. tool-based — tool orqali tekshirish (kelajakda: fayl mavjudligi)
    3. llm-judge — arzon LLM (T1_FREE) bilan tekshirish

Ilgari faqat deterministic bor edi. Uzun `expected_outcome` (>3 so'z,
ya'ni jonli tildagi TAVSIF) confidence=0.6 bilan avtomatik 'ok'
hisoblanardi — hech qanday tekshiruv bo'lmasdan. Bu Bo'lim 1'ning
tanlangan taqiqi edi ("keyingi bo'limda") va yashirin false-pass
manbai. Endi LLM-judge ulangan bo'lsa shu holatda haqiqiy tekshiruv
so'ralad: T1_FREE model tool chiqishini kutilgan natija bilan
solishtirib "ha/yo'q + sabab" qaytaradi.

FAIL-OPEN: LLM-judge yiqilsa (tarmoq, rate limit, timeout) — eski
xatti-harakat (matnli tavsifni 'ok' deb qabul qilish) qaytadi. Ya'ni
LLM-judge yolg'on 'FAIL' bermaydi, u faqat qo'shimcha tekshiruv qatlami.

Bog'liq qarorlar:
    V-01 — har bir natija tekshiriladi
    V-35 — tekshiruv natijasi Verification modelida
    ADR-0006 — Model Router (T1_FREE — arzon tekshiruv)
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import TYPE_CHECKING

import structlog

from zet.domain.plan import PlanStep
from zet.domain.tool import ToolResult, Verification

if TYPE_CHECKING:
    from zet.llm.base import LLMProvider

log = structlog.get_logger(__name__)


class VerificationOutcome(StrEnum):
    """JB-14 PART I — `Verification`ning TaskGraph darajasidagi talqini.

    NEGA yangi enum, `Verification.ok`ning o'zi YETARLI EMAS: `ok=True`
    ikkita TUBDAN farqli holatni yashiradi — "haqiqatan tasdiqlandi"
    (masalan matn/regex mos keldi, `confidence>=0.9`) va "tool
    muvaffaqiyat deb aytdi, lekin biz buni HAQIQATDA tekshira olmadik"
    (uzoq `expected_outcome`, LLM-judge yo'q — fail-open, `confidence=0.6`).
    Ikkinchisi — spec so'zlashuvidagi "UNCERTAIN": Mission bu holatni
    COMPLETED emas, degan qaror qabul qilishi kerak.

    `NOT_REQUIRED` — tool yo'q (fikrlash qadami) yoki `expected_outcome`
    berilmagan (faqat success flag) hollari uchun — bu ATAYLAB "kam
    ishonchli" emas, "tekshiruv so'ralmagan" degani.
    """

    VERIFIED = "verified"
    VERIFICATION_FAILED = "verification_failed"
    VERIFICATION_UNCERTAIN = "verification_uncertain"
    NOT_REQUIRED = "not_required"


UNCERTAIN_CONFIDENCE_THRESHOLD = 0.65
"""Shu qiymatdan PAST `confidence` bilan kelgan `ok=True` — VERIFIED emas,
VERIFICATION_UNCERTAIN deb hisoblanadi.

NEGA aynan 0.65: `Verifier`ning mavjud confidence darajalari — 1.0
(fikrlash/hech narsa tekshirilmagan), 0.9 (aniq matn mos keldi), 0.85
(regex mos keldi), 0.8 (faqat success flag, expected_outcome yo'q),
0.75 (LLM-judge tasdiqladi), 0.6 (uzoq tavsif, LLM-judge YO'Q — ko'r
fail-open). 0.65 chegara — 0.6 (haqiqiy noaniqlik) bilan 0.75+ (haqiqiy
tekshiruv, LLM yoki qisqa shablon) orasidan AYNAN o'tadi."""


def classify_verification(
    verification: Verification, *, required: bool = True
) -> VerificationOutcome:
    """`Verification` → `VerificationOutcome` (JB-14 PART I §2).

    Args:
        verification: `Verifier.verify_step()`/`verify_run()` natijasi.
        required: `False` bo'lsa — tekshiruv umuman so'ralmagan edi
            (masalan tool yo'q/faqat fikrlash qadami) — natija har doim
            `NOT_REQUIRED` (Verification'ning o'zi `ok=True` bo'lsa ham).
    """
    if not required:
        return VerificationOutcome.NOT_REQUIRED
    if not verification.ok:
        return VerificationOutcome.VERIFICATION_FAILED
    if verification.confidence < UNCERTAIN_CONFIDENCE_THRESHOLD:
        return VerificationOutcome.VERIFICATION_UNCERTAIN
    return VerificationOutcome.VERIFIED


MAX_LITERAL_WORDS = 3
"""Shu so'zdan ko'p bo'lgan `expected_outcome` — TAVSIF, shablon emas.

NEGA BU CHEGARA BOR.

`expected_outcome` Planner sxemasida "kutilgan natija TAVSIFI" deb
e'lon qilingan, ya'ni model u yerga jonli tildagi jumla yozadi:

    "YouTube videosidan foydali ma'lumotlarni olish va ajratib olish"

Verifier esa uni tool chiqishi ichidan **so'zma-so'z** qidirardi.
Bunday jumla JSON chiqish ichida hech qachon uchramaydi, natijada
hammasi mukammal bajarilgan run ham FAILED bo'lardi. Jonli misol:

    video_learn.done  key_points=5 terms=7
    tool.ok           latency_ms=18779
    orchestrator.run_finished  status="failed"   ← yolg'on

Ega to'liq va to'g'ri natijani oldi, lekin ZET uni "muvaffaqiyatsiz"
deb ko'rsatdi.

Qisqa shablon (`natija`, `\\d{3}`) — haqiqatan tekshiriladi va topilmasa
qadam yiqiladi. Uzun jumla esa: LLM-judge ulangan bo'lsa haqiqiy
tekshiruv o'tadi, aks holda ishonchni pasaytiradi va sababi yoziladi,
lekin muvaffaqiyatli tool natijasini yolg'ondan yiqitmaydi."""


LLM_JUDGE_MAX_OUTPUT_CHARS = 4000
"""Tool chiqishining LLM'ga uzatiladigan qismi.

Uzun (10k+ token) natijalar bir T1 chaqiruvining butun budjetini
yeyishi mumkin. 4k belgi — o'zaro kelishuv: kontekst yetarli, tanaffuz
kichik."""


class Verifier:
    """Qadam natijasini kutilgan natijaga tekshiradi.

    Deterministic (default) + LLM-judge (ixtiyoriy).
    """

    def __init__(
        self,
        *,
        llm_judge_provider: LLMProvider | None = None,
    ) -> None:
        """
        Args:
            llm_judge_provider: LLM-judge uchun T1_FREE provayder. Berilmasa
                — eski deterministic-only xatti-harakat (backward compat).
        """
        self._llm_judge = llm_judge_provider

    async def verify_step(
        self,
        step: PlanStep,
        tool_result: ToolResult | None,
        *,
        chat_output: str | None = None,
    ) -> Verification:
        """Qadam natijasini tekshiradi.

        Args:
            step: bajarilgan qadam
            tool_result: tool natijasi (None bo'lsa — fikrlash qadami)
            chat_output: fikrlash/chat qadamining matnli chiqishi (JB-17).
                Faqat `step.tool_name is None and tool_result is None`
                holatida ishlatiladi — boshqa hollarda e'tiborsiz.

        Returns:
            Verification
        """
        # Fikrlash qadami — tool yo'q
        if step.tool_name is None and tool_result is None:
            return await self._verify_chat_step(step, chat_output)

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
            return await self._verify_against_expectation(
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

    async def _verify_chat_step(
        self, step: PlanStep, chat_output: str | None
    ) -> Verification:
        """Fikrlash/chat qadami — ixtiyoriy, shartli LLM-judge tekshiruvi (JB-17).

        ILGARI bu holat SHARTSIZ `ok=True, confidence=1.0` qaytarardi —
        chat javobining MAZMUNI hech qachon tekshirilmasdi (JB-16 audit
        topilmasi). Endi, FAQAT quyidagi UCHTA shart BIRGALIKDA
        bajarilsa, mavjud `_llm_judge_verify()` (tool natijalari uchun
        allaqachon bor, o'zgarishsiz) chat matniga ham qo'llaniladi:
            1. LLM-judge provayder ulangan (`self._llm_judge is not None`)
            2. Chiqish matni bor (`chat_output` bo'sh emas)
            3. Planner haqiqatan tekshiriladigan, JONLI TILDAGI
               `expected_outcome` bergan (`MAX_LITERAL_WORDS`dan uzun —
               qisqa shablon EMAS)

        Qisqa shablon (`MAX_LITERAL_WORDS` va past)ga LITERAL/REGEX
        qat'iy moslik TALAB QILINMAYDI (tool JSON'dan farqli, erkin
        tabiiy til matnida so'zma-so'z moslik kutish yolg'on-FAIL
        manbai bo'lardi) — bunday holatda ham eski, o'zgarishsiz
        xatti-harakat qaytadi.

        FAIL-OPEN: judge chaqiruvi yiqilsa/format buzilsa — eski
        `ok=True, confidence=1.0` qaytadi, HECH QACHON yangi yolg'on
        FAIL yaratmaydi (Verifier'ning umumiy fail-open shartnomasi).
        """
        default = Verification(
            ok=True,
            reason="Fikrlash qadami — tekshiruv kerak emas",
            auto=True,
            confidence=1.0,
        )
        if self._llm_judge is None or not chat_output or not step.expected_outcome:
            return default
        if len(step.expected_outcome.split()) <= MAX_LITERAL_WORDS:
            return default
        judged = await self._llm_judge_verify(step.expected_outcome, chat_output)
        if judged is not None:
            return judged
        return default

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

    async def _verify_against_expectation(
        self,
        expected: str,
        result: ToolResult,
    ) -> Verification:
        """Natijani kutilgan natijaga tekshiradi.

        Oddiy matn taqqoslash + regex + (ixtiyoriy) LLM-judge.
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

        # Jonli tildagi jumla — literal/regex tekshiruv iloji yo'q.
        if len(expected.split()) > MAX_LITERAL_WORDS:
            # LLM-judge ulangan bo'lsa haqiqiy tekshiruv — bu darslikda
            # aytilgan "keyingi bo'lim" edi. Ulanmagan bo'lsa eski
            # xatti-harakat (`ok=True, confidence=0.6`) davom etadi.
            if self._llm_judge is not None:
                judged = await self._llm_judge_verify(expected, output_str)
                if judged is not None:
                    return judged

            return Verification(
                ok=True,
                reason=(
                    f"Kutilgan natija matnan tasdiqlanmadi (tavsif): '{expected}'. "
                    "Tool muvaffaqiyat deb qaytardi."
                ),
                auto=True,
                confidence=0.6,
            )

        return Verification(
            ok=False,
            reason=f"Kutilgan natija topilmadi: '{expected}' → '{output_str[:200]}'",
            auto=True,
            confidence=0.7,
        )

    async def _llm_judge_verify(self, expected: str, output: str) -> Verification | None:
        """LLM-judge: arzon model tool chiqishini kutilgan natija bilan solishtiradi.

        Returns:
            Verification (ok=True/False, reason bilan) — LLM muvaffaqiyatli
            javob bergan bo'lsa. `None` — LLM yiqildi/timeout/parse xato,
            chaqiruvchi eski (fail-open) yo'lga tushsin.
        """
        from zet.llm.base import ChatMessage, LLMError

        truncated = output[:LLM_JUDGE_MAX_OUTPUT_CHARS]
        system = (
            "Sen — natija tekshiruvchi (verifier). Bir qadamning KUTILGAN NATIJASI "
            "va TOOL CHIQISHI beriladi. Tool chiqishi kutilgan natijaga to'g'ri "
            "keldimi degan savolga javob ber.\n\n"
            "JAVOB FORMATI (aynan, boshqa hech narsa qo'shma):\n"
            "  OK: <bir gapda sabab>\n"
            "yoki\n"
            "  FAIL: <nima yetishmayotgani>\n\n"
            "Jonli tildagi tasvirlar uchun MATNMA-MATN mos kelishi shart emas — "
            "MA'NO mos kelsa yetarli. Tool JSON qaytargan bo'lsa strukturasi va "
            "qiymatlariga qara, so'zma-so'z izlama."
        )
        user = (
            f"KUTILGAN NATIJA:\n{expected}\n\n"
            f"TOOL CHIQISHI:\n{truncated}\n\n"
            "Yechim (OK: yoki FAIL: bilan boshla):"
        )
        try:
            response = await self._llm_judge.complete(
                messages=[ChatMessage(role="user", content=user)],
                system=system,
                max_tokens=120,
            )
        except (LLMError, Exception):
            log.debug("verifier.llm_judge_failed", expected=expected[:80])
            return None

        text = response.text.strip()
        if not text:
            return None

        # `OK: ...` — muvaffaqiyat
        upper = text.upper()
        if upper.startswith("OK"):
            reason = text.split(":", 1)[1].strip() if ":" in text else "LLM tasdiqladi"
            return Verification(
                ok=True,
                reason=f"LLM-judge: {reason[:200]}",
                auto=True,
                confidence=0.75,
            )
        if upper.startswith("FAIL"):
            reason = text.split(":", 1)[1].strip() if ":" in text else "LLM rad etdi"
            return Verification(
                ok=False,
                reason=f"LLM-judge: {reason[:200]}",
                auto=True,
                confidence=0.75,
            )

        # Format buzilgan — fail-open (eski yo'l)
        log.debug("verifier.llm_judge_bad_format", text=text[:200])
        return None
