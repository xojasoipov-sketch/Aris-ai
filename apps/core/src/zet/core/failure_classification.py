"""Failure classification — muvaffaqiyatsizlikni kanonik sinflarga ajratadi (JB-14).

NEGA bu modul kerak (audit topilmasi, JB-13'da ATAYLAB kiritilmagan):
`TaskGraphExecutor._run_task()` va `RecoveryEngine`/`MissionRecoveryAdapter`
hamon BARCHA xatolarni BIR XIL — "log yoz, qayta urin (agar max_retries
tugamagan bo'lsa), aks holda FAILED" — deb ko'rar edi. Kredensial xato
(qayta urinish HECH QACHON yordam bermaydi) bilan tarmoq uzilishi (qayta
urinish ODATDA yordam beradi) orasida FARQ YO'Q edi — ikkalasi ham xuddi
bir xil "N marta qayta urin, keyin FAILED" yo'lidan o'tardi.

Bu modul — MINIMAL, DETERMINISTIK klassifikator: mavjud istisno
turlarini (`zet.tools.base.ToolError` oilasi, `zet.llm.base.LLMError`
oilasi, `zet.agents.runtime`/`registry` xatolari, `zet.security.*`,
h.k.) HAQIQIY sinflarga xaritalaydi — YANGI istisno arxitekturasi
QURMAYDI, faqat MAVJUDlarini o'qiydi. Matn-asoslangan fallback (istisno
turi noma'lum bo'lganda) — kalit so'z qidiruv, LLM chaqiruvi YO'Q.

Bog'liq qarorlar:
    JB-14 PART II — failure classification + intelligent recovery
    JB-11 — `Tool.idempotent` (idempotentlik, bu yerda ishlatilmaydi,
        lekin bir xil "aniqlik yo'q — xavfsiz tomonga xato qil" tamoyili)
"""

from __future__ import annotations

import re
from enum import StrEnum

import structlog

log = structlog.get_logger(__name__)


class FailureClass(StrEnum):
    """Kanonik muvaffaqiyatsizlik sinfi (JB-14 spec so'zlashuvi).

    Majburiy TO'LIQ ro'yxat emas — mavjud har bir istisno shu 13
    sinfdan BIRIGA xaritalanadi (majburiy 1:1 emas, "eng yaqin mos
    keluvchi").
    """

    TRANSIENT = "transient"
    MODEL = "model"
    TOOL = "tool"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    RATE_LIMIT = "rate_limit"
    NETWORK = "network"
    EXTERNAL_UNCERTAIN = "external_uncertain"
    INVALID_PLAN = "invalid_plan"
    VALIDATION = "validation"
    USER_REQUIRED = "user_required"
    SYSTEM = "system"
    UNKNOWN = "unknown"


class RecoveryAction(StrEnum):
    """`FailureClass`ga bog'langan tavsiya etilgan tiklash amali.

    Bu — SIYOSAT yorlig'i, majburiy amalga oshiruvchi kod emas: har
    chaqiruvchi (`TaskGraphExecutor`, `MissionEngine.recover()`) o'z
    kontekstida bu tavsiyani qanday amalga oshirishni hal qiladi
    (masalan BOUNDED_RETRY — chaqiruvchining o'z max_retries chegarasi
    bilan, YANGI chegara emas)."""

    BOUNDED_RETRY = "bounded_retry"
    """Chegaralangan qayta urinish — mavjud retry hisoblagichi bilan."""

    MODEL_FALLBACK = "model_fallback"
    """ModelRouter allaqachon provider fallback qilgan bo'lishi kerak
    (`llm/router.py::complete()` — circuit breaker + candidate ro'yxati
    bo'yicha). Bu yerga yetib kelgan MODEL xatosi — BARCHA nomzodlar
    tugagan degani; qayta o'sha chaqiruvni AYNAN takrorlash foyda
    bermaydi (bir xil natija)."""

    ALTERNATE_TOOL_OR_AGENT = "alternate_tool_or_agent"
    """Muqobil tool/agent bilan urinish mumkin bo'lsa — shu, aks holda
    REPLAN'ga tushadi."""

    REPLAN = "replan"
    """Mission-darajasidagi qayta rejalashtirish (mavjud
    `MissionRecoveryAdapter`/`RecoveryEngine` orqali)."""

    STOP_USER_ACTION = "stop_user_action"
    """To'xtatish — foydalanuvchi aralashuvisiz davom etib bo'lmaydi
    (masalan noto'g'ri kredensial)."""

    APPROVAL_REQUIRED = "approval_required"
    """Mavjud approval oqimiga yo'naltiriladi (bu modul approval
    YARATMAYDI — faqat shuni tavsiya qiladi, mavjud
    `ApprovalService`/`PermissionPolicy` haqiqiy qarorni beradi)."""

    VERIFY_BEFORE_RETRY = "verify_before_retry"
    """Qayta urinishdan OLDIN mavjud holatni tekshirish kerak (ko'r-ko'rona
    takrorlamaslik uchun) — `core/verifier.py`ga qarang."""

    PERSIST_AND_RECOVER = "persist_and_recover"
    """Tizim darajasidagi xato — mavjud holat saqlanadi, restart/resume
    orqali tiklanadi (JB-11/JB-13 run-level recovery)."""

    SAFE_FAILURE = "safe_failure"
    """Xavfsiz yiqilish — avtomatik qayta urinish YO'Q (noma'lum sabab)."""


_RECOVERY_POLICY: dict[FailureClass, RecoveryAction] = {
    FailureClass.TRANSIENT: RecoveryAction.BOUNDED_RETRY,
    FailureClass.NETWORK: RecoveryAction.BOUNDED_RETRY,
    FailureClass.RATE_LIMIT: RecoveryAction.BOUNDED_RETRY,
    FailureClass.MODEL: RecoveryAction.MODEL_FALLBACK,
    FailureClass.TOOL: RecoveryAction.ALTERNATE_TOOL_OR_AGENT,
    FailureClass.AUTHENTICATION: RecoveryAction.STOP_USER_ACTION,
    FailureClass.AUTHORIZATION: RecoveryAction.APPROVAL_REQUIRED,
    FailureClass.EXTERNAL_UNCERTAIN: RecoveryAction.VERIFY_BEFORE_RETRY,
    FailureClass.INVALID_PLAN: RecoveryAction.REPLAN,
    FailureClass.VALIDATION: RecoveryAction.REPLAN,
    FailureClass.USER_REQUIRED: RecoveryAction.STOP_USER_ACTION,
    FailureClass.SYSTEM: RecoveryAction.PERSIST_AND_RECOVER,
    FailureClass.UNKNOWN: RecoveryAction.SAFE_FAILURE,
}


def recovery_action_for(failure_class: FailureClass) -> RecoveryAction:
    """`FailureClass` → tavsiya etilgan `RecoveryAction` (spec §11 jadvali)."""
    return _RECOVERY_POLICY[failure_class]


_FUTILE_RETRY_CLASSES: frozenset[FailureClass] = frozenset(
    {
        FailureClass.AUTHENTICATION,
        FailureClass.AUTHORIZATION,
        FailureClass.VALIDATION,
        FailureClass.INVALID_PLAN,
        FailureClass.USER_REQUIRED,
    }
)
"""NEGA `UNKNOWN` bu ro'yxatda YO'Q (spec §11 "UNKNOWN → safe failure, no
blind retry" bilan bir qarashda ziddek ko'ringan qaror, ATAYLAB): eski
`TaskGraphExecutor` istisno turidan qat'i nazar HAR doim `max_retries`
marta urinardi (`test_task_graph.py::TestRetryAndTimeout` — mavjud,
JB-14'dan OLDINGI regressiya testlari — buni aniq qulflaydi). `UNKNOWN`
— aynan "biz bu xatoni ANIQ tanimadik" degani, "bu xato ANIQ doimiy"
degani EMAS — shu farq sabab uni FUTILE (qayta urinish naf bermaydi)
deb belgilash noto'g'ri bo'lardi: chinakam vaqtinchalik (masalan tarmoq
uzilishi tasodifiy `RuntimeError` sifatida ko'tarilgan) xatoni ham
abadiy to'sib qo'yardi. "No blind retry" tamoyili UNKNOWN uchun MAVJUD
`max_retries` chegarasining O'ZI orqali ta'minlanadi (cheksiz emas) —
qo'shimcha "ERTA chiqish" YO'Q, lekin ALTERNATE_TOOL_OR_AGENT/REPLAN
kabi "aqlliroq" chora ham qo'llanilmaydi (`_RECOVERY_POLICY[UNKNOWN] =
SAFE_FAILURE`, TaskGraph faqat TOOL sinfida alt-agent sinaydi)."""


def is_retry_futile(failure_class: FailureClass) -> bool:
    """`True` — AYNAN SHU chaqiruvni ko'r-ko'rona qayta urinish naf
    bermaydi (masalan noto'g'ri parol yana ham noto'g'ri bo'lib qoladi).

    NEGA muhim: `TaskGraphExecutor`ning eski xatti-harakati — HAR qanday
    xato uchun `max_retries` marta qayta urinardi, hatto natija
    OLDINDAN ma'lum bo'lsa ham (masalan AUTHENTICATION — 3 marta bir xil
    "401" olish). Bu — behuda vaqt/xarajat va (agentlar uchun) LLM
    budjetini yeydi. `is_retry_futile` — TaskGraph qayta urinish
    tsiklidan ERTA chiqishi uchun signal — FAQAT ishonchli aniqlangan
    sinflar uchun (`UNKNOWN` bunga KIRMAYDI, yuqoridagi izohga qarang)."""
    return failure_class in _FUTILE_RETRY_CLASSES


# ── Matn-asoslangan (fallback) klassifikatsiya ─────────────────────

_TEXT_RULES: tuple[tuple[FailureClass, tuple[str, ...]], ...] = (
    (FailureClass.RATE_LIMIT, ("429", "rate limit", "rate-limit", "too many requests", "kvota tugagan")),
    (FailureClass.AUTHENTICATION, ("401", "unauthorized", "invalid credential", "invalid api key", "authentication failed", "kredensial")),
    (FailureClass.AUTHORIZATION, ("403", "forbidden", "permission denied", "ruxsat yo'q", "ruxsat berilmadi")),
    (FailureClass.NETWORK, ("connection", "dns", "unreachable", "econnrefused", "ulanib bo'lmadi")),
    (FailureClass.TRANSIENT, ("timeout", "timed out", "vaqt tugadi", "temporarily unavailable")),
    (FailureClass.VALIDATION, ("validation", "invalid input", "schema", "yaroqsiz")),
    (
        FailureClass.INVALID_PLAN,
        ("invalid plan", "noto'g'ri reja", "reja generatsiyasi xato", "tool topilmadi"),
    ),
    # `AgentMaxToolCallsError`/`AgentMaxStepsError` matn shakli
    # (`agents/runtime.py`) — `classify_exception()` bu turlarni
    # to'g'ridan-to'g'ri TOOL'ga xaritalaydi (pastda), lekin
    # `AgentRuntime.run()` ularni ICHKARIDA tutib `AgentRunResult(
    # success=False, error=str(exc))` qaytaradi — istisno hech qachon
    # `run_agent_command()`dan chiqmaydi. Shu sabab `TaskGraphExecutor`
    # bu holatni FAQAT matn orqali ko'radi; matn qoidasi tur-asoslangan
    # xaritalash bilan izchil bo'lishi uchun qo'shildi.
    (FailureClass.TOOL, ("tool chaqiruviga yetdi", "qadamga yetdi")),
)


_EXPLICIT_CLASS_TOKEN = re.compile(r"failure_class=([a-z_]+)")
"""`mission.py::_execute_task_graph()` task-darajasida ALLAQACHON
ANIQ klassifikatsiya qilingan `MissionTask.failure_class`ni shu aniq
token shaklida (`failure_class=authentication` kabi) Mission-darajasidagi
`recover()`ning erkin-matn `last_failure`siga qo'shadi — bu PRECIZ
qayta o'qish uchun (pastdagi fuzzy kalit-so'z evristikasidan OLDIN
tekshiriladi, chunki aniq ma'lumot mavjud bo'lsa, uni taxmin bilan
almashtirish noto'g'ri bo'lardi)."""


def classify_text(text: str) -> FailureClass:
    """Xato matnidan aniqlaydi (LLM chaqiruvisiz, deterministik).

    Avval `failure_class=<qiymat>` aniq tokenini qidiradi (task
    darajasida ALLAQACHON ma'lum klassifikatsiyani yo'qotmaslik uchun),
    keyin kalit-so'z evristikasiga tushadi. Hech narsa mos kelmasa —
    UNKNOWN."""
    lowered = text.lower()
    explicit = _EXPLICIT_CLASS_TOKEN.search(lowered)
    if explicit:
        try:
            return FailureClass(explicit.group(1))
        except ValueError:
            pass  # noma'lum token — pastdagi evristikaga tushadi
    for failure_class, keywords in _TEXT_RULES:
        if any(kw in lowered for kw in keywords):
            return failure_class
    return FailureClass.UNKNOWN


def classify_exception(exc: BaseException) -> FailureClass:
    """Mavjud istisno turini `FailureClass`ga xaritalaydi.

    Import'lar funksiya ICHIDA — aylanma import xavfini oldini oladi
    (`tools.base`/`llm.base`/`agents.*`/`security.*` barchasi bu
    modulni import qilmaydi, lekin ehtiyot chorasi sifatida — bu modul
    ularning barchasini import qiladigan yagona joy, dependency
    yo'nalishi bitta tomonga qaraydi).
    """
    from zet.agents.registry import AgentNotActiveError, AgentNotFoundError
    from zet.agents.runtime import AgentMaxStepsError, AgentMaxToolCallsError, AgentTimeoutError
    from zet.automation.executor import AgentUnavailableError
    from zet.core.executor import ApprovalRequiredError
    from zet.core.intent import AmbiguousCommandError
    from zet.core.planner import PlannerError
    from zet.domain.plan import PlanValidationError
    from zet.llm.base import (
        BudgetExceededError,
        NoProviderAvailableError,
        ProviderConfigError,
        ProviderUnavailableError,
        QuotaExhaustedError,
        RateLimitError,
    )
    from zet.security.approvals import ApprovalExpiredError, ApprovalRejectedError
    from zet.security.killswitch import KillSwitchEngagedError
    from zet.tools.base import (
        ToolPermissionDeniedError,
        ToolQuotaError,
        ToolTimeoutError,
        ToolValidationError,
    )
    from zet.tools.registry import ToolNotFoundError

    # Aniq turlar — eng maxsusidan eng umumiysiga.
    if isinstance(exc, RateLimitError | ToolQuotaError | QuotaExhaustedError):
        return FailureClass.RATE_LIMIT
    if isinstance(exc, ToolTimeoutError | TimeoutError):
        return FailureClass.NETWORK
    if isinstance(exc, ToolPermissionDeniedError):
        return FailureClass.AUTHORIZATION
    if isinstance(exc, ApprovalRequiredError | ApprovalRejectedError | ApprovalExpiredError):
        return FailureClass.USER_REQUIRED
    if isinstance(exc, ToolValidationError | PlanValidationError):
        return FailureClass.VALIDATION
    if isinstance(exc, AmbiguousCommandError):
        return FailureClass.USER_REQUIRED
    if isinstance(exc, PlannerError):
        return FailureClass.INVALID_PLAN
    if isinstance(exc, ProviderConfigError | NoProviderAvailableError | ProviderUnavailableError):
        return FailureClass.MODEL
    if isinstance(exc, BudgetExceededError):
        return FailureClass.SYSTEM
    if isinstance(exc, AgentNotFoundError | AgentNotActiveError | AgentUnavailableError):
        return FailureClass.TOOL
    if isinstance(exc, AgentMaxStepsError | AgentMaxToolCallsError):
        return FailureClass.TOOL
    if isinstance(exc, AgentTimeoutError):
        return FailureClass.NETWORK
    if isinstance(exc, ToolNotFoundError):
        return FailureClass.INVALID_PLAN
    if isinstance(exc, KillSwitchEngagedError):
        return FailureClass.SYSTEM

    # `LLMError`/`ToolError`/`AgentRuntimeError` bazaviy sinflari — aniq
    # subklass mos kelmasa, matn heuristikasiga tushamiz (masalan
    # provider-o'ziga xos xato matni "connection refused" bo'lishi
    # mumkin, lekin turi shunchaki generic `LLMError`).
    text_guess = classify_text(str(exc))
    if text_guess is not FailureClass.UNKNOWN:
        return text_guess

    from zet.llm.base import LLMError
    from zet.tools.base import ToolError

    if isinstance(exc, LLMError):
        return FailureClass.MODEL
    if isinstance(exc, ToolError):
        return FailureClass.TOOL

    return FailureClass.UNKNOWN


def classify_failure(
    exc: BaseException | None = None,
    *,
    text: str | None = None,
) -> FailureClass:
    """Bosh kirish nuqtasi: istisno BERILSA tur-asoslangan, aks holda
    (faqat matn bor — masalan `AgentRunResult.error` string) matn-
    asoslangan klassifikatsiya.
    """
    if exc is not None:
        return classify_exception(exc)
    if text:
        return classify_text(text)
    return FailureClass.UNKNOWN


__all__ = [
    "FailureClass",
    "RecoveryAction",
    "classify_exception",
    "classify_failure",
    "classify_text",
    "is_retry_futile",
    "recovery_action_for",
]
