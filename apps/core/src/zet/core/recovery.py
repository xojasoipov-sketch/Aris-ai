"""RecoveryEngine — FAIL→DIAGNOSE→FIX→RETRY→VERIFY sikli (Master Spec PART 6).

NEGA bu modul kerak: Verifier `ok=False` qaytarganda ilgari Orchestrator
darhol RunStatus.FAILED ga o'tardi va ega hech qanday tuzatish urinishini
ko'rmasdi. Master Spec PART 6 va AUTONOMY_AUDIT §2.5 aynan aksini talab
qiladi — arzon T1_FREE LLM'dan "nima xato bo'ldi va uni qanday
tuzataylik" so'rash va tuzatish qadamlarini rejaga qo'shib qayta
urinish. Bu — soxta muvaffaqiyat emas, HALOL avtonomiya: hamma
tuzatish urinishlari yoziladi (audit), qattiq MAX_RETRIES=2 chegara
uncontrolled loop'ni to'sadi va exhaust bo'lsa recovered=False halol
qaytariladi (Orchestrator FAILED ga o'tkazadi, tuzatilgan deb ko'rsatmaydi).

Ilgari (bo'lim 6'gacha) recovery umuman yo'q edi:
    verify_run(FAIL) → RunStatus.FAILED darhol
Endi:
    verify_run(FAIL) → RunStatus.RECOVERING → diagnose → fix → retry
    → verify → (ok yoki max_retries) → DONE yoki FAILED

Bog'liq qarorlar:
    Master Spec PART 6 — recovery loop
    AUTONOMY_AUDIT §2.5 — halol tuzatish (soxta yiqish emas)
    PART 8 — halol yiqilish (never fake autonomy)
    A-01 — RunStatus.RECOVERING davomli holat
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

from zet.core.executor import ApprovalRequiredError
from zet.domain.enums import PermissionLevel, StepStatus, TrustLevel
from zet.domain.plan import Plan, PlanStep, PlanValidationError
from zet.domain.tool import ToolResult, Verification
from zet.llm.base import ChatMessage, LLMError
from zet.security.permissions import PermissionDecision

if TYPE_CHECKING:
    from zet.core.executor import ExecutionContext, Executor
    from zet.core.verifier import Verifier
    from zet.llm.base import LLMProvider

log = structlog.get_logger(__name__)

MAX_RETRIES: int = 2
"""FAIL→DIAGNOSE→FIX→RETRY sikllarining qattiq chegarasi (Master Spec PART 6).

NEGA aynan 2: Executor'ning `_MAX_RETRIES` bilan bir xil — arzon LLM
chaqiruvi va tuzatish qadami xarajati nazorat ostida bo'lsin. Uchtadan
ko'p urinish deyarli hech qachon boshqa natija bermaydi (jonli
kuzatuv), lekin budjetni behuda yeyadi."""

_ABSOLUTE_MAX_RETRIES: int = 5
"""D3 audit (KONSOLIDATSIYA v2) — SO'NGGI qattiq shift, `__init__`dagi
`max_retries` argumentidan MUSTAQIL.

NEGA kerak: `max_retries: int = MAX_RETRIES` parametri chaqiruvchiga
(masalan kelajakda `Settings`dan o'qiladigan konfiguratsiya) katta son
uzatish imkonini beradi. `MAX_RETRIES=2` — ishlatiladigan amaldagi
default, lekin bu o'zi hech kimni cheklamaydi (faqat default qiymat).
Cheksiz retry loop imkonsizligini KOD DARAJASIDA (konfiguratsiya bilan
chetlab o'tib bo'lmaydigan tarzda) kafolatlash uchun `__init__` har doim
`min(max_retries, _ABSOLUTE_MAX_RETRIES)` qiladi — hech qanday argument
bu sonni oshira olmaydi. Test: `test_absolute_ceiling_cannot_be_exceeded`
(`test_recovery.py`)."""

DIAGNOSIS_MAX_OUTPUT_CHARS: int = 4000
"""LLM'ga uzatiladigan tool chiqishining maksimal uzunligi.

Verifier'dagi `LLM_JUDGE_MAX_OUTPUT_CHARS` bilan bir xil — 10k+ tokenli
chiqish bir T1 chaqiruvining butun budjetini yeb qo'yadi."""

DIAGNOSIS_MAX_FIX_STEPS: int = 3
"""LLM taklif qiladigan tuzatish qadamlarining maksimal soni.

NEGA: LLM ba'zida 10-20 qadamli "eng yaxshi yechim" chizadi va butun
reja bir tuzatishdan portlab ketadi. Rejaga qo'shimcha qadamlar
DAG'ning hajmini kattalashtiradi va budjet yeydi. Uchtadan ko'p
tuzatish qadami — deyarli hamma vaqt LLM'ning haddan tashqari
qizishi, real tuzatish emas."""

AuditFn = Callable[..., Awaitable[None]]
"""Audit yozish funksiyasi (Executor'dagi bilan bir xil naqsh)."""


class RecoveryEngineError(RuntimeError):
    """Recovery engine darajasidagi umumiy xato."""


class RecoveryExhaustedError(RecoveryEngineError):
    """MAX_RETRIES ga yetildi, hali ham verify FAIL.

    NEGA: `attempt()` odatda buni KO'TARMAYDI — buning o'rniga
    `RecoveryOutcome(recovered=False, ...)` qaytaradi va Orchestrator
    error path'i bitta shoxli qoladi (Master Spec PART 8, halol
    yiqilish). Bu istisno faqat programma xatosi (bo'sh kirish, dastur
    invariantining buzilishi) uchun ajratilgan."""


class DiagnosisParseError(RecoveryEngineError):
    """LLM javobini structural aylanmadi — parse xato.

    NEGA istisno emas, `Diagnosis` maydonlarida yoziladi: bir buzilgan
    LLM javob butun urinishni yiqitmasin, faqat shu urinish attempts
    hisoblagichini bir kamaytirsin. Aks holda buzilgan LLM cheksiz T1
    chaqiruv yeydi."""


class RecoveryApprovalRequiredError(ApprovalRequiredError):
    """D1 audit (KONSOLIDATSIYA v2, MAJBURIY talab) — recovery fix qadami
    HIGH-risk bo'lib chiqdi, Executor'ning oddiy approval darvozasi
    ko'targan.

    NEGA alohida tur kerak (oddiy `ApprovalRequiredError` emas): tasdiqdan
    keyin `Orchestrator.resume()` ASL emas, TUZATILGAN (fix qadamlari
    qo'shilgan) rejani bajarishi kerak — aks holda ega tasdiqlagan qadam
    umuman bajarilmay qoladi (rejada yo'q). `extended_plan` shu ma'lumotni
    olib yuradi; `Orchestrator._handle_approval_required` uni ko'rib
    `record.plan`ni yangilaydi. `isinstance(exc, ApprovalRequiredError)`
    baribir True qoladi — Orchestrator'ning umumiy `except
    ApprovalRequiredError` handleri ikkalasini ham bir xil ushlaydi."""

    def __init__(
        self, step: PlanStep, decision: PermissionDecision, *, extended_plan: Plan
    ) -> None:
        super().__init__(step, decision)
        self.extended_plan = extended_plan


@dataclass(frozen=True)
class Diagnosis:
    """Bir tuzatish urinishida yig'ilgan LLM diagnosis va tuzatish qadamlari.

    Ilgari (bo'lim 6'gacha): tuzatish umuman yo'q — natijada har xatoli
    run "muvaffaqiyatsiz" deb yozilardi, sabab bilinmasdi. Endi har
    urinishning `root_cause` matni audit log'ga tushadi va ega
    "nima xato bo'ldi va nima urinildi" ni ko'radi.
    """

    root_cause: str
    """LLM'ning bir gapli tushuntirishi — audit log'ga."""

    fix_steps: list[PlanStep] = field(default_factory=list)
    """LLM taklif qilgan tuzatish qadamlari (pozitsiyalar va depends_on
    to'g'irlangan holda)."""

    confidence: float = 0.0
    """LLM'ning o'z-o'ziga bahosi (0..1). Past bo'lsa log'ga yoziladi,
    lekin qayta urinishni to'smaydi."""

    raw: dict[str, Any] = field(default_factory=dict)
    """LLM'ning xom JSON javobi — debug/audit uchun (kaping'gacha)."""


@dataclass(frozen=True)
class RecoveryOutcome:
    """Recovery loop yakuni.

    `recovered=True` bo'lsa Orchestrator DONE ga o'tadi (extended_plan
    yozib qo'yiladi); `recovered=False` — FAILED, `final_verification.reason`
    xatoning ochiq sababini beradi.
    """

    recovered: bool
    """Oxirgi urinishda verify muvaffaqiyatli bo'ldimi."""

    attempts: int
    """Sarflangan FIX→RETRY sikllari soni (0..MAX_RETRIES)."""

    diagnoses: list[Diagnosis]
    """Tartibda barcha diagnoslar — audit izi."""

    extended_plan: Plan
    """Tuzatish qadamlari qo'shilgan reja (attempts=0 bo'lsa asl reja)."""

    final_verification: Verification
    """Oxirgi urinishdagi verify natijasi."""


class RecoveryEngine:
    """FAIL→DIAGNOSE→FIX→RETRY→VERIFY sikli implementatsiyasi.

    Orchestrator `_run_plan` ichida `verify_run` FAIL qaytargan zahoti
    `attempt()` chaqiradi. Engine T1_FREE LLM'dan diagnos so'raydi,
    tuzatish qadamlarini rejaga qo'shadi, yangi Executor bilan qayta
    ishga tushiradi va asl yiqilgan qadamning `expected_outcome`
    ini qayta tekshiradi.

    Invariantlar (Master Spec PART 6):
        - MAX_RETRIES chegarasi qattiq — hech bir yo'l undan oshib
          o'tolmaydi (`range(max_retries)` sikli), va `_ABSOLUTE_MAX_
          RETRIES` konstruktor argumentidan MUSTAQIL qattiq shift beradi
          (D3 audit, KONSOLIDATSIYA v2 — konfiguratsiya bu sonni oshira
          olmaydi)
        - Kirish `Plan` HECH QACHON mutatsiya qilinmaydi — yangi frozen
          instansi yaratiladi
        - Har T1_FREE chaqiruv chegaralangan (max_tokens ~600, kesilgan
          kontekst) — recovery narxi O(MAX_RETRIES * arzon chaqiruv)
        - `attempt()` exhaust'da ISTISNO KO'TARMAYDI — Orchestrator error
          path'i bitta shoxli qoladi (PART 8 halol yiqilish)
        - `attempt()` HIGH-risk fix qadamida `RecoveryApprovalRequiredError`
          KO'TARADI (D1 audit, KONSOLIDATSIYA v2, MAJBURIY) — Recovery
          Engine hech qachon o'zining "men tuzataman" holatidan foydalanib
          Approval Engine'ni chetlab o'tolmaydi; LOW/MEDIUM-risk fix
          qadamlari esa Executor'ning oddiy avtomatik yo'lidan
          (approval kerak emas) o'tadi (D2)
    """

    def __init__(
        self,
        *,
        llm_provider: LLMProvider,
        executor_factory: Callable[[], Executor],
        verifier: Verifier,
        max_retries: int = MAX_RETRIES,
        audit_fn: AuditFn | None = None,
        tool_names: set[str] | None = None,
    ) -> None:
        """
        Args:
            llm_provider: T1_FREE tier provayder (Verifier LLM-judge bilan
                bir xil tier) — arzon model yiqilgan qadamning
                kirish/chiqishi bo'yicha fikr yuritish uchun yetarli.
            executor_factory: `Executor` qaytaruvchi zero-arg callable —
                Orchestrator uni beradi (u har run uchun yangi Executor
                quradi, budjet/policy/registry allaqachon bog'langan).
                Callable ekanligi RecoveryEngine'ni per-run holatdan
                ozod qiladi.
            verifier: Orchestrator ishlatgan aynan shu Verifier — ok/reason
                shartnomasi asl run va recovery re-verify o'rtasida bir xil
                qolsin.
            max_retries: Qattiq chegara (default MAX_RETRIES=2, Master
                Spec PART 6 loop-guard qoidasi).
            audit_fn: Ixtiyoriy audit yozuvchi — har diagnos va har
                urinish uchun strukturli yozuv (event='recovery.attempt'
                / 'recovery.diagnosis' / 'recovery.gave_up') chiqadi.
            tool_names: LLM taklif qilgan tuzatish qadamlari tekshirilishi
                uchun mavjud tool nomlari to'plami. Berilmasa — validation
                o'tkazib yuboriladi (fail-open, faqat DAG tekshiruvi qoladi).
        """
        self._llm = llm_provider
        self._executor_factory = executor_factory
        self._verifier = verifier
        # D3 audit fix (KONSOLIDATSIYA v2): `_ABSOLUTE_MAX_RETRIES` — hech
        # qanday chaqiruvchi (konfiguratsiya, kelajakdagi Settings
        # maydoni, test) bu sonni oshira olmaydi. `max(0, ...)` — manfiy
        # qiymat himoyasi (avvalgidek).
        self._max_retries = min(max(0, int(max_retries)), _ABSOLUTE_MAX_RETRIES)
        self._audit_fn = audit_fn
        self._tool_names = tool_names

    async def attempt(
        self,
        *,
        plan: Plan,
        ctx: ExecutionContext,
        failed_verifications: list[tuple[PlanStep, Verification]],
        trust: TrustLevel,
        approved_steps: set[int] | None = None,
    ) -> RecoveryOutcome:
        """Recovery siklini yakuniy natija (recovered=True/False) gacha aylantiradi.

        Args:
            plan: Asl reja (mutatsiya qilinmaydi).
            ctx: Asl bajarilish konteksti — yiqilgan qadamning
                `tool_result` diagnos promptiga kiradi.
            failed_verifications: FAIL bo'lgan `(step, verification)`
                juftliklari (Orchestrator yig'ib beradi).
            trust: Recovery bajarilish trust darajasi.
            approved_steps: Oldindan tasdiqlangan qadamlar. D1 audit fix
                (KONSOLIDATSIYA v2): yangi fix qadamlar bu to'plamga
                QO'SHILMAYDI — har biri Executor'ning o'z ichki
                `policy.check()` darvozasidan o'tadi (pastga qarang).

        Returns:
            `RecoveryOutcome` — hech qachon `RecoveryExhaustedError`
            ko'tarmaydi.

        Raises:
            RecoveryApprovalRequiredError: bir fix qadam HIGH-risk deb
                baholandi (D1, MAJBURIY) — Orchestrator buni ushlab
                AWAITING_APPROVAL'ga o'tkazishi SHART, hech qachon
                yutib yubormasligi kerak.
        """
        # Defensive: bo'sh kirish — hech qanday tuzatish kerak emas
        if not failed_verifications:
            log.debug("recovery.no_failures")
            return RecoveryOutcome(
                recovered=True,
                attempts=0,
                diagnoses=[],
                extended_plan=plan,
                final_verification=Verification(
                    ok=True,
                    reason="Tekshiriladigan yiqilishlar yo'q",
                    auto=True,
                    confidence=1.0,
                ),
            )

        # Bir qadamli recovery — birinchi yiqilgan qadamdan boshlaymiz.
        # Ko'p yiqilish bo'lsa, chaqiruvchi outcome asosida qayta chaqiradi.
        failed_step, failed_verification = failed_verifications[0]

        diagnoses: list[Diagnosis] = []
        extended_plan: Plan = plan
        approved: set[int] = set(approved_steps or set())
        last_verification: Verification = failed_verification

        # `range(max_retries)` — qattiq chegara. Hech bir shart shu
        # sikldan oshib o'tolmaydi (Master Spec PART 6 invariant).
        for attempt_no in range(1, self._max_retries + 1):
            await self._emit_audit(
                event="recovery.attempt",
                detail={
                    "attempt": attempt_no,
                    "step": failed_step.position,
                    "reason": failed_verification.reason[:200],
                },
            )

            # 1. DIAGNOSE — LLM'dan tuzatish so'rash. Parse/LLM xato ham
            #    Diagnos'ga aylantiriladi (diagnoslar audit izi bo'lib
            #    qoladi, urinish soni hisoblanadi).
            tool_result = self._tool_result_for(ctx, failed_step)
            diagnosis = await self._diagnose(
                step=failed_step,
                tool_result=tool_result,
                verification=failed_verification,
                plan=extended_plan,
            )
            diagnoses.append(diagnosis)
            await self._emit_audit(
                event="recovery.diagnosis",
                detail={
                    "attempt": attempt_no,
                    "root_cause": diagnosis.root_cause[:200],
                    "fix_steps": len(diagnosis.fix_steps),
                    "confidence": diagnosis.confidence,
                },
            )

            # 2. Parse buzilgan yoki tuzatish qadamlari yo'q — bu urinish
            #    natijasiz, keyingi urinishga o'tamiz (limit hisoblanadi).
            if not diagnosis.fix_steps:
                log.warning(
                    "recovery.no_fix_steps",
                    attempt=attempt_no,
                    root_cause=diagnosis.root_cause[:120],
                )
                last_verification = Verification(
                    ok=False,
                    reason=f"Recovery {attempt_no}-urinish: {diagnosis.root_cause}",
                    auto=True,
                    confidence=0.5,
                )
                continue

            # 3. Rejani kengaytiramiz — asl reja o'zgarmaydi, yangi Plan
            #    instansi. PlanValidationError bo'lsa — buzilgan LLM javobi
            #    deb qaraymiz va urinish sarflaymiz.
            try:
                extended_plan = self._extend_plan(
                    extended_plan, diagnosis.fix_steps, anchor=failed_step
                )
            except PlanValidationError as exc:
                log.warning("recovery.plan_invalid", attempt=attempt_no, error=str(exc))
                last_verification = Verification(
                    ok=False,
                    reason=f"Recovery {attempt_no}-urinish: reja DAG buzildi: {exc}",
                    auto=True,
                    confidence=0.5,
                )
                continue

            # D1 audit fix (KONSOLIDATSIYA v2, MAJBURIY talab): ILGARI shu
            # yerda `approved = approved | new_positions` bo'lardi — bu
            # LLM taklif qilgan BARCHA yangi fix qadamni ko'r-ko'rona
            # oldindan tasdiqlangan deb belgilardi, HAQIQIY risk darajasidan
            # QAT'I NAZAR. Natija: `file.delete`/`network.request`/
            # `config.modify` kabi HIGH-risk fix qadami ham Executor'ning
            # approval darvozasini (`step.position not in ctx.approved_
            # steps`) bypass qilardi — bu aynan V-32'ning MUTLAQO
            # taqiqlagan holati (Recovery Engine "men tuzataman" deb
            # Approval Engine'ni chetlab o'tishi).
            #
            # ENDI: yangi fix qadamlar `approved`ga UMUMAN QO'SHILMAYDI.
            # `approved` faqat CHAQIRUVCHIDAN kelgan (asl rejaning oldindan
            # tasdiqlangan qadamlari) holicha qoladi. Buning o'rniga har
            # bir yangi qadam quyida Executor'ning O'ZINING ICHKI
            # `policy.check()` darvozasidan — AYNAN oddiy reja qadami kabi
            # — o'tadi:
            #   - LOW/MEDIUM risk (masalan READ, yoki auto_approve_write=
            #     True bo'lgan WRITE) → `decision.needs_approval=False` →
            #     `approved_steps`da bo'lish-bo'lmasligidan qat'i nazar
            #     AVTOMATIK bajariladi (D2).
            #   - HIGH_RISK_TOOLS yoki EXECUTE/ADMIN → `decision.
            #     needs_approval=True` va pozitsiya `approved`da yo'q →
            #     `ApprovalRequiredError` TABIIY tarzda ko'tariladi —
            #     quyida ushlanadi va `RecoveryApprovalRequiredError`
            #     sifatida TASHQARIGA chiqariladi (D1).
            new_positions = sorted(
                s.position
                for s in extended_plan.steps
                if s.position not in {orig.position for orig in plan.steps}
            )
            log.debug(
                "recovery.fix_steps_added",
                attempt=attempt_no,
                new_positions=new_positions,
            )

            # 4. RETRY — yangi Executor bilan kengaytirilgan rejani
            #    ishga tushiramiz. Har urinish yangi Executor oladi
            #    (budjet hisobi toza, per-run holat izolyatsiyalangan).
            #
            # HIGH #2 audit fix (KONSOLIDATSIYA v2): `executor.execute_
            # plan()` har chaqiruvda YANGI bo'sh ExecutionContext bilan
            # BOSHIDAN bajaradi — bu yerdagi `ctx` (kiruvchi parametr
            # yoki oldingi urinishning natijasi) ALLAQACHON DONE bo'lgan
            # qadamlarni o'z ichiga oladi. Ular `completed_steps` orqali
            # uzatilmasa, HAR bir recovery urinishi ASL rejaning
            # muvaffaqiyatli WRITE/EXECUTE qadamlarini (masalan xabar
            # yuborish) QAYTA bajarib yuborardi — bu D1'ning "approval
            # bypass yo'q" kafolatidan MUSTAQIL, alohida idempotentlik
            # xatosi edi (approval umuman kerak bo'lmagan, allaqachon
            # bajarilgan qadamlar uchun).
            already_done = {
                pos: res for pos, res in ctx.results.items() if res.status == StepStatus.DONE
            }
            executor = self._executor_factory()
            try:
                ctx = await executor.execute_plan(
                    extended_plan,
                    approved_steps=approved,
                    trust=trust,
                    completed_steps=already_done,
                )
            except ApprovalRequiredError as exc:
                # D1 (MAJBURIY): fix qadami HIGH-risk — Recovery Engine
                # BU YERDA TO'XTAYDI va istisnoni tashqariga chiqaradi.
                # Orchestrator buni oddiy mission-qadam approval'i kabi
                # AWAITING_APPROVAL'ga aylantiradi (`_handle_approval_
                # required`). Recovery loop davom ETMAYDI — qolgan
                # urinishlar (agar bo'lsa) ega tasdig'idan KEYIN, yangi
                # `resume()` chaqiruvida qayta boshlanadi.
                log.warning(
                    "recovery.fix_step_requires_approval",
                    attempt=attempt_no,
                    step=exc.step.position,
                    tool=exc.step.tool_name,
                    reason=exc.decision.reason,
                )
                await self._emit_audit(
                    event="recovery.fix_requires_approval",
                    detail={
                        "attempt": attempt_no,
                        "step": exc.step.position,
                        "tool": exc.step.tool_name or "",
                        "reason": exc.decision.reason[:200],
                    },
                )
                raise RecoveryApprovalRequiredError(
                    exc.step, exc.decision, extended_plan=extended_plan
                ) from exc
            except Exception as exc:
                # Executor darajasidagi boshqa istisno (budjet, killswitch)
                # — recovery bu yerda to'xtaydi va halol yiqiladi.
                log.warning("recovery.executor_failed", attempt=attempt_no, error=str(exc))
                last_verification = Verification(
                    ok=False,
                    reason=f"Recovery {attempt_no}-urinish: executor xato: {exc}",
                    auto=True,
                    confidence=0.5,
                )
                continue

            # 5. VERIFY — asl yiqilgan qadamning qayta tekshiruvi (yangi
            #    tool_result ustidan). Verifier o'zi Orchestrator bilan
            #    bir xil — ok/reason kontrakti asl run bilan bir xil.
            new_tool_result = self._tool_result_for(ctx, failed_step)
            last_verification = await self._verifier.verify_step(failed_step, new_tool_result)
            if last_verification.ok:
                log.info(
                    "recovery.succeeded",
                    attempt=attempt_no,
                    step=failed_step.position,
                )
                return RecoveryOutcome(
                    recovered=True,
                    attempts=attempt_no,
                    diagnoses=diagnoses,
                    extended_plan=extended_plan,
                    final_verification=last_verification,
                )

            failed_verification = last_verification

        # Sikl tugadi — hali ham FAIL. Halol yiqilamiz (PART 8).
        await self._emit_audit(
            event="recovery.gave_up",
            detail={
                "attempts": self._max_retries,
                "last_reason": last_verification.reason[:200],
                "root_cause": (diagnoses[-1].root_cause[:200] if diagnoses else ""),
            },
        )
        log.warning(
            "recovery.exhausted",
            attempts=self._max_retries,
            step=failed_step.position,
            reason=last_verification.reason[:200],
        )
        return RecoveryOutcome(
            recovered=False,
            attempts=self._max_retries,
            diagnoses=diagnoses,
            extended_plan=extended_plan,
            final_verification=last_verification,
        )

    # ── Internal ────────────────────────────────────────────────────

    @staticmethod
    def _tool_result_for(
        ctx: ExecutionContext,
        step: PlanStep,
    ) -> ToolResult | None:
        """Kontekstdagi qadam natijasidan `ToolResult` ni oladi (bor bo'lsa)."""
        step_result = ctx.results.get(step.position)
        if step_result is None:
            return None
        return step_result.tool_result

    async def _diagnose(
        self,
        *,
        step: PlanStep,
        tool_result: ToolResult | None,
        verification: Verification,
        plan: Plan,
    ) -> Diagnosis:
        """LLM'dan diagnos va tuzatish qadamlari so'raydi.

        LLM/parse xato — Diagnos empty fix_steps bilan qaytadi (urinish
        yo'qotilmaydi, lekin sarflandi hisoblanadi)."""
        system = _DIAGNOSIS_SYSTEM
        user = self._build_diagnosis_prompt(
            step=step, tool_result=tool_result, verification=verification, plan=plan
        )
        try:
            response = await self._llm.complete(
                messages=[ChatMessage(role="user", content=user)],
                system=system,
                max_tokens=600,
            )
        except (LLMError, Exception) as exc:
            log.warning("recovery.llm_error", error=str(exc)[:200])
            return Diagnosis(
                root_cause=f"LLM error: {exc}",
                fix_steps=[],
                confidence=0.0,
                raw={},
            )

        text = (response.text or "").strip()
        if not text:
            return Diagnosis(root_cause="LLM bo'sh javob qaytardi", fix_steps=[])

        # JSON ni ajratamiz — LLM ba'zida ```json fences qo'shadi
        payload = _extract_json(text)
        if payload is None:
            return Diagnosis(
                root_cause=f"Parse failure: LLM javobida JSON topilmadi ({text[:120]})",
                fix_steps=[],
                raw={"text": text[:1000]},
            )

        try:
            root_cause = str(payload.get("root_cause", "")).strip() or "sabab ko'rsatilmagan"
            confidence = float(payload.get("confidence", 0.0) or 0.0)
            raw_steps = payload.get("fix_steps") or []
            if not isinstance(raw_steps, list):
                raise ValueError("fix_steps ro'yxat emas")
            # Chegaralaymiz — plan explosion bo'lmasin (audit uchun raw
            # to'liq qoladi).
            capped = raw_steps[:DIAGNOSIS_MAX_FIX_STEPS]
            fix_steps = self._parse_fix_steps(capped)
        except (ValueError, TypeError, KeyError) as exc:
            return Diagnosis(
                root_cause=f"Parse failure: {exc}",
                fix_steps=[],
                raw=payload if isinstance(payload, dict) else {"text": text[:1000]},
            )

        if not fix_steps:
            return Diagnosis(
                root_cause=root_cause or "Parse failure: hech qanday to'g'ri tuzatish qadami yo'q",
                fix_steps=[],
                confidence=max(0.0, min(1.0, confidence)),
                raw=payload,
            )

        return Diagnosis(
            root_cause=root_cause,
            fix_steps=fix_steps,
            confidence=max(0.0, min(1.0, confidence)),
            raw=payload,
        )

    def _parse_fix_steps(self, raw_steps: list[Any]) -> list[PlanStep]:
        """Xom LLM step ta'riflaridan PlanStep obyektlariga aylantiradi.

        Bu bosqichda pozitsiyalar va depends_on hali qo'yilmagan —
        `_extend_plan` ularni to'g'irlaydi."""
        parsed: list[PlanStep] = []
        for i, raw in enumerate(raw_steps):
            if not isinstance(raw, dict):
                continue
            description = str(raw.get("description", "")).strip()
            if not description:
                continue
            tool_name = raw.get("tool_name")
            if tool_name is not None:
                tool_name = str(tool_name).strip() or None
            if (
                tool_name is not None
                and self._tool_names is not None
                and tool_name not in self._tool_names
            ):
                # Noma'lum tool — LLM hayolot qildi, tashlab yuboramiz
                log.warning("recovery.unknown_tool", tool=tool_name, description=description[:80])
                continue
            tool_params = raw.get("tool_params") or {}
            if not isinstance(tool_params, dict):
                tool_params = {}
            expected_outcome = raw.get("expected_outcome")
            if expected_outcome is not None:
                expected_outcome = str(expected_outcome)
            perm_raw = str(raw.get("permission_required", "read")).lower()
            try:
                permission = PermissionLevel(perm_raw)
            except ValueError:
                permission = PermissionLevel.READ
            # Placeholder position=i — `_extend_plan` qayta yozadi.
            parsed.append(
                PlanStep(
                    position=i,
                    description=description,
                    tool_name=tool_name,
                    tool_params=tool_params,
                    expected_outcome=expected_outcome,
                    permission_required=permission,
                )
            )
        return parsed

    def _extend_plan(
        self,
        plan: Plan,
        fix_steps: list[PlanStep],
        *,
        anchor: PlanStep,
    ) -> Plan:
        """Rejaga tuzatish qadamlarini qo'shadi (yangi Plan qaytaradi).

        - Yangi pozitsiyalar: max(existing)+1..+N
        - Birinchi tuzatish qadami `anchor.position` ga bog'lanadi (DAG)
        - Qolganlari chiziqli — oldingi tuzatish qadamiga bog'lanadi
        - Chegara: DIAGNOSIS_MAX_FIX_STEPS

        Plan `_validate_dag` orqali sikllarni topsa PlanValidationError
        ko'taradi (chaqiruvchi buni ushlaydi va urinishni yo'qotgan
        hisoblaydi)."""
        if not fix_steps:
            return plan
        capped = fix_steps[:DIAGNOSIS_MAX_FIX_STEPS]

        max_pos = max((s.position for s in plan.steps), default=-1)
        prior_dep: int = anchor.position

        new_steps: list[PlanStep] = []
        for i, raw in enumerate(capped):
            new_position = max_pos + 1 + i
            depends_on = [prior_dep]
            new_step = raw.model_copy(update={"position": new_position, "depends_on": depends_on})
            new_steps.append(new_step)
            prior_dep = new_position

        return Plan(
            summary=f"{plan.summary} [+recovery]",
            steps=[*plan.steps, *new_steps],
            task_class=plan.task_class,
            estimated_usd=plan.estimated_usd,
            raw_llm_output=plan.raw_llm_output,
        )

    def _build_diagnosis_prompt(
        self,
        *,
        step: PlanStep,
        tool_result: ToolResult | None,
        verification: Verification,
        plan: Plan,
    ) -> str:
        """Diagnos so'rovi uchun user prompt yasaydi.

        Kontekstga aynan yiqilgan qadamning tavsifi, kutilgan natijasi,
        tool xatosi va verification sababi kiradi — LLM'sizsiz diagnos
        qila olmasligini oldini oladi (T8 test)."""
        tool_name = step.tool_name or "(fikrlash qadami)"
        params_json = _safe_json(step.tool_params)
        error_text = ""
        output_text = ""
        if tool_result is not None:
            error_text = (tool_result.error or "").strip()
            if tool_result.output is not None:
                output_text = str(tool_result.output)[:DIAGNOSIS_MAX_OUTPUT_CHARS]
        tool_names_hint = ""
        if self._tool_names:
            names = sorted(self._tool_names)[:40]
            joined = ", ".join(names)
            tool_names_hint = f"\nMAVJUD TOOL'LAR (faqat shulardan tanla):\n{joined}\n"
        none_marker = "(yo'q)"
        empty_marker = "(bo'sh)"
        expected_str = step.expected_outcome or none_marker
        error_str = error_text or none_marker
        output_str = output_text or empty_marker
        return (
            "REJA:\n"
            f"{plan.summary}\n\n"
            "YIQILGAN QADAM:\n"
            f"- position: {step.position}\n"
            f"- description: {step.description}\n"
            f"- tool_name: {tool_name}\n"
            f"- tool_params: {params_json}\n"
            f"- expected_outcome: {expected_str}\n"
            f"- permission_required: {step.permission_required.value}\n\n"
            "TOOL NATIJASI:\n"
            f"- error: {error_str}\n"
            f"- output (kesilgan): {output_str}\n\n"
            "VERIFICATION SABABI:\n"
            f"{verification.reason}\n"
            f"{tool_names_hint}\n"
            "Yuqoridagi JSON schema bo'yicha diagnos qaytar."
        )

    async def _emit_audit(self, *, event: str, detail: dict[str, Any]) -> None:
        """Audit hook — fail-open (audit yozuvchi yiqilsa recovery yiqilmaydi)."""
        if self._audit_fn is None:
            return
        try:
            await self._audit_fn(
                actor="agent",
                action=event,
                target="recovery_engine",
                permission_level=PermissionLevel.READ,
                detail=detail,
            )
        except Exception:
            log.warning("recovery.audit_failed", event=event)


_DIAGNOSIS_SYSTEM = (
    "Sen — recovery diagnostikasi. Bir reja qadami yiqildi. Sening vazifang: "
    "nima xato bo'lganini bir gapda tushuntirish va qayta urinish uchun 1..3 "
    "ta tuzatish qadamini taklif qilish. Hech qachon soxta 'ok' yozma — halol "
    "diagnoz ber. Faqat mavjud tool'lardan foydalanmoq mumkin.\n\n"
    "JAVOB FORMATI (aynan JSON, boshqa hech narsa qo'shma):\n"
    "{\n"
    '  "root_cause": "bir gapda nima xato",\n'
    '  "confidence": 0.0..1.0,\n'
    '  "fix_steps": [\n'
    "    {\n"
    '      "description": "qadam tavsifi",\n'
    '      "tool_name": "tool.name yoki null",\n'
    '      "tool_params": {},\n'
    '      "expected_outcome": "kutilgan natija",\n'
    '      "permission_required": "read|write|execute|admin"\n'
    "    }\n"
    "  ]\n"
    "}\n\n"
    "Agar diagnos qila olmasang — bo'sh fix_steps ro'yxati bilan qaytar."
)


def _safe_json(value: Any) -> str:
    """dict/list ni qisqa JSON matnga aylantiradi (LLM promptiga)."""
    try:
        return json.dumps(value, ensure_ascii=False)[:800]
    except (TypeError, ValueError):
        return str(value)[:800]


def _extract_json(text: str) -> dict[str, Any] | None:
    """Matn ichidan birinchi JSON obyektni ajratib oladi.

    LLM ba'zida ```json ... ``` fences yoki qo'shimcha prose qo'shadi;
    biz sof `{...}` blokini tortib olamiz."""
    stripped = text.strip()
    # Fenced code bloklarini olib tashlaymiz
    if stripped.startswith("```"):
        # ``` yoki ```json bilan boshlanadi
        first_nl = stripped.find("\n")
        if first_nl != -1:
            stripped = stripped[first_nl + 1 :]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
        stripped = stripped.strip()
    # Birinchi '{' dan oxirgi '}' gacha
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    blob = stripped[start : end + 1]
    try:
        parsed = json.loads(blob)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


__all__ = [
    "DIAGNOSIS_MAX_FIX_STEPS",
    "DIAGNOSIS_MAX_OUTPUT_CHARS",
    "MAX_RETRIES",
    "AuditFn",
    "Diagnosis",
    "DiagnosisParseError",
    "RecoveryApprovalRequiredError",
    "RecoveryEngine",
    "RecoveryEngineError",
    "RecoveryExhaustedError",
    "RecoveryOutcome",
]
