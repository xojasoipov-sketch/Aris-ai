"""Brain-level Model Router — kognitiv bosqich/vazifa mazmuniga qarab TaskClass tanlash (JB-7).

AUDIT TOPILMASI (JB-7 boshlanishidan oldin): `zet.llm.router.ModelRouter` +
`zet.llm.catalog` (`ModelSpec`, `candidates_for`) — provider/tier/narx/
kvota/vision-tool-calling metadata bilan TO'LIQ, sinovdan o'tgan Model
Registry + Router + Fallback (circuit breaker, budjet, kvota) tizimi
ALLAQACHON mavjud. `IntentRecognizer`/`Planner`/`RecoveryEngine` ham
`TaskClass`ni allaqachon LLM orqali klassifikatsiya qilib, pastga
uzatadi (`intent.task_class` → `plan.task_class` → `recovery`).

HAQIQIY BO'SHLIQ: `AgentRuntime`/`TaskGraphExecutor` yo'lida (Bo'lim 3,
JB-5) `task_class` HAR DOIM `agent.model_policy`ning STATIK tier'idan
(`RoutedLLMProvider.task_class_for_tier`) kelib chiqadi — bitta agent
BUTUN umri davomida BIR XIL tierga bog'langan, garchi ikkita turli task
(masalan oddiy `weather.now` va murakkab `github.write` reasoning)
haqiqatda boshqa-boshqa chuqurlik talab qilsa ham. Bu modul shu
bo'shliqni yopadi: HAR BIR task uchun ALOHIDA, tushuntirilgan
marshrutlash qarori.

NEGA DETERMINISTIK (LLM emas): JB-7 spetsifikatsiyasi (§15) aylanma
bog'liqlikni aniq taqiqlaydi — "Brain → Router → LLM → Router → LLM →
... No uncontrolled recursion." Bu qatlam oddiy, tushuntiriladigan
qoidalar to'plami. Kelajakda ustiga LLM-asoslangan/o'rganilgan router
qo'shilishi mumkin (§15: `DeterministicRouter + OptionalIntelligentRouter
→ FinalRoutingPolicy`), lekin bu DETERMINISTIK siyosat yakuniy, xavfsiz
fallback bo'lib qoladi.

Bog'liq qarorlar:
    V-29 — task_class model marshrutlash
    ADR-0006 — 4 tier, Model Router
    JB-5 — Task Graph (RoutingSignal shu yerdan quriladi)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from zet.domain.enums import RiskLevel, TaskClass

_CODING_NAMESPACES = frozenset({"github", "deploy", "shell"})
"""Tool namespace'i shu to'plamda bo'lsa — kod/infratuzilma amali (CODING)."""

_VISION_NAMESPACES = frozenset({"camera", "vision", "desktop"})
"""Tool namespace'i shu to'plamda bo'lsa — vizual kirish/chiqish (VISION).

`desktop.*` ham shu yerda: `desktop.screenshot` natijasi rasm (JB-5
`AgentRuntime._extract_image` konvensiyasi bilan bir xil mantiq)."""

_LONG_TEXT_CHARS = 4000
"""Bu chegaradan uzunroq buyruq matni — COMPLEX deb hisoblanadi (uzoq
kontekst/ko'p tafsilot taxminiy belgisi — haqiqiy token hisobi emas,
`ModelRouter.estimate_usage()` bilan bir xil oddiy taxmin darajasi)."""


class CognitiveStage(StrEnum):
    """Brain ichidagi bosqich — `RoutingSignal` shu bosqich uchun tuziladi.

    NEGA kerak: bir xil "murakkablik" signali PLANNING bosqichida
    boshqacha, TASK_EXECUTION bosqichida boshqacha og'irlik olishi
    mumkin (masalan reja tuzish har doim chuqurroq reasoning talab
    qiladi, oddiy bitta-tool bajarish esa ko'pincha yo'q)."""

    INTENT = "intent"
    PLANNING = "planning"
    TASK_EXECUTION = "task_execution"
    EVALUATION = "evaluation"
    RECOVERY = "recovery"
    RESPONSE = "response"


@dataclass(frozen=True, slots=True)
class RoutingSignal:
    """Bitta marshrutlash qarori uchun kirish — task/mission haqidagi ma'lum signallar.

    Barcha maydonlar IXTIYORIY (default'lar bilan) — chaqiruvchi nimani
    bilsa, shuni beradi; noma'lum signal "past" deb hisoblanadi
    (fail-safe: noaniqlik qimmatroq modelga emas, standart yo'lga olib
    boradi — xarajat tomonidan xavfsiz)."""

    stage: CognitiveStage
    tool: str | None = None
    risk_level: RiskLevel = RiskLevel.LOW
    text_length: int = 0
    requires_tools: bool = False


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """Marshrutlash qarori — HAR DOIM tushuntirilgan (audit uchun, JB-7 §14/§36).

    `reason` — inson o'qiy oladigan bir gaplik izoh, log'ga yoziladi
    (`task_graph.py` `task_graph.model_routed` hodisasida)."""

    task_class: TaskClass
    reason: str


class BrainModelRouter:
    """`RoutingSignal` → `RoutingDecision` — kognitiv bosqich + vazifa mazmuniga qarab.

    Qoidalar ustuvorlik tartibida (birinchi mos kelgani g'olib):
        1. Tool namespace vizual bo'lsa → VISION
        2. Tool namespace kod/infratuzilma bo'lsa → CODING
        3. Risk HIGH+ bo'lsa → COMPLEX (ehtiyotkor reasoning)
        4. Matn uzun bo'lsa → COMPLEX
        5. Bosqich chuqur reasoning talab qilsa (PLANNING/EVALUATION/
           RECOVERY) → COMPLEX
        6. Bosqich INTENT bo'lsa → SIMPLE (arzon, tez klassifikatsiya)
        7. Aks holda → NORMAL (standart ijro)

    Bu — `zet.llm.router.ModelRouter`ni ALMASHTIRMAYDI: u faqat QAYSI
    `TaskClass`ni so'rash kerakligini hal qiladi; haqiqiy provider/model
    tanlovi, budjet, kvota, circuit breaker — barchasi ModelRouter'da
    (o'zgartirilmagan) qoladi.
    """

    def route(self, signal: RoutingSignal) -> RoutingDecision:
        namespace = (signal.tool or "").split(".", 1)[0]

        if namespace in _VISION_NAMESPACES:
            return RoutingDecision(
                TaskClass.VISION, f"tool '{signal.tool}' vizual kirish/chiqish talab qiladi"
            )
        if namespace in _CODING_NAMESPACES:
            return RoutingDecision(
                TaskClass.CODING, f"tool '{signal.tool}' kod/infratuzilma amali"
            )
        if signal.risk_level.rank >= RiskLevel.HIGH.rank:
            return RoutingDecision(
                TaskClass.COMPLEX,
                f"{signal.risk_level.value} risk — ehtiyotkor, sifatli reasoning kerak",
            )
        if signal.text_length > _LONG_TEXT_CHARS:
            return RoutingDecision(
                TaskClass.COMPLEX, f"uzun kontekst ({signal.text_length} belgi)"
            )
        if signal.stage in (
            CognitiveStage.PLANNING,
            CognitiveStage.EVALUATION,
            CognitiveStage.RECOVERY,
        ):
            return RoutingDecision(
                TaskClass.COMPLEX, f"'{signal.stage.value}' bosqichi chuqur reasoning talab qiladi"
            )
        if signal.stage == CognitiveStage.INTENT:
            return RoutingDecision(
                TaskClass.SIMPLE, "intent klassifikatsiyasi — qisqa, arzon model yetarli"
            )
        return RoutingDecision(TaskClass.NORMAL, "standart ijro — maxsus signal topilmadi")


__all__ = [
    "BrainModelRouter",
    "CognitiveStage",
    "RoutingDecision",
    "RoutingSignal",
]
