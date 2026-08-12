"""6 TIZIM retsepti — ega yuborgan tayyor avtomatlashtirishlar (yangi zip).

Slaydlarning yakuniy va'dasi:

    "Sizga qoladi: faqat qaror qabul qilish. Qolgani — yozish,
     tekshirish, eslatish, chop etish — tizimda."

Har bir retsept: TRIGGER → 3 QADAM → NATIJA.

    01 Uchrashuv kotibi   — yozishmani o'qib uchrashuv qo'yadi
    02 Ovozdan rejaga     — ovozli xabar → vazifa + deadline
    03 Guruh razvedkasi   — ish guruhlarini o'qib "nima yonmoqda" hisoboti
    04 Kontent konveyeri  — post tayyorlaydi, sukut bo'lsa chop etadi
    05 Lid yo'li          — izoh/Direct → savol → slot taklifi
    06 Kunlik puls        — doskalarni tekshirib 3 qatorli hisobot

ENG MUHIM QARQOR — HALOL HOLAT.

Retseptlarning ko'pi ZET'da hali BO'LMAGAN tashqi imkoniyatlarga
tayanadi (kalendar, MTProto guruh o'qish, Instagram webhook, haqiqiy
STT). Ikki yo'l bor edi:

    (a) baribir "yoqilgan" deb ko'rsatib, ichida stub ishlatish
    (b) yetishmayotganini OCHIQ aytish

(a) — yolg'on. Ega retsept ishlayapti deb o'ylab, uchrashuvni
tekshirmay qolardi va u hech qachon kalendarga tushmasdi. Shuning
uchun (b): `RecipeStatus.MISSING_CAPABILITY` va aynan qaysi imkoniyat
yetishmayotgani. Bu `apps/web/CLAUDE.md`dagi "Halol holatlar"
standartining backend ko'rinishi.

`install()` faqat READY retseptni o'rnatadi. Yetishmayotgan retsept
o'rnatilmaydi — chala ishlaydigan avtomatlashtirish umuman yo'q
avtomatlashtirishdan yomonroq.

Bog'liq qarorlar:
    Yangi zip — 6 TIZIM retsepti
    docs/12-AUTONOMY-GAP.md — imkoniyat matritsasi
    V-32 — tasdiq (04 va 05 yozuv amallarini o'z ichiga oladi)
    A-05 — izoh/Direct/guruh xabari UNTRUSTED
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Final

import structlog
from pydantic import BaseModel, Field

from zet.automation.autonomy import AutonomyLevel
from zet.automation.scheduler import ScheduleRule
from zet.automation.triggers import EventTrigger, TriggerCondition, TriggerType

if TYPE_CHECKING:
    from zet.automation.engine import AutomationEngine
    from zet.config import Settings
    from zet.tools.registry import ToolRegistry

log = structlog.get_logger(__name__)


class Capability(StrEnum):
    """Retsept ishlashi uchun kerak bo'lgan imkoniyat."""

    LLM = "llm"
    """Matnni tushunish/yozish — hech bo'lmasa bitta model provayderi."""

    CRON = "cron"
    """Vaqt bo'yicha ishga tushirish (`Scheduler` + daemon)."""

    TELEGRAM_SEND = "telegram.send"
    """Telegram orqali xabar yuborish."""

    TELEGRAM_READ_GROUPS = "telegram.read_groups"
    """Ish guruhlari tarixini o'qish.

    Bot API buni BERMAYDI: bot faqat o'zi qo'shilgan guruhdagi yangi
    xabarlarni ko'radi, tarixni emas. To'liq o'qish uchun MTProto
    (Telethon) sessiyasi kerak — ZET'da hali yo'q.
    """

    CALENDAR = "calendar"
    """Bo'sh slot topish va uchrashuv yozish. ZET'da hali yo'q."""

    MEETING_LINK = "meeting_link"
    """Zoom/Meet havolasi yaratish. ZET'da hali yo'q."""

    STT = "stt"
    """Ovozdan matnga. `voice/stt.py` hozir `StubSTT` — transkripsiya qilmaydi."""

    CONTENT_PUBLISH = "content.publish"
    """Kontentni chop etish (Instagram/YouTube/Telegram kanal)."""

    INSTAGRAM_WEBHOOK = "instagram.webhook"
    """Izoh/Direct hodisalarini qabul qilish. Obuna sozlanmagan."""

    CRM = "crm"
    """Kontakt/lid yozuvlari."""

    TASK_BOARD = "task_board"
    """Loyiha doskasi (vazifa holatlari). ZET'da ma'lumot modeli yo'q."""

    TIMED_APPROVAL = "approval.timed"
    """"Sukut = rozilik" taymerli tasdiq.

    V-32 faqat ANIQ tasdiqni biladi; "belgilangan vaqtgacha e'tiroz
    bo'lmasa davom et" rejimi hali yo'q.
    """


class RecipeStatus(StrEnum):
    """Retseptning haqiqiy holati."""

    READY = "ready"
    """Barcha imkoniyat bor — o'rnatilishi mumkin."""

    MISSING_CAPABILITY = "missing_capability"
    """Kamida bitta imkoniyat yetishmaydi — o'rnatilmaydi."""


class TriggerKind(StrEnum):
    """Retsept qanday uyg'onadi (slayddagi 'vaqt' / 'xodisa')."""

    TIME = "time"
    EVENT = "event"


class RecipeStep(BaseModel, frozen=True):
    """Retseptning bitta qadami (slaydda uchtadan)."""

    order: int = Field(ge=1, le=5)
    """Qadam raqami."""

    title: str = Field(min_length=1)
    """Qadam nomi (ega o'qiydi)."""

    agent_name: str = Field(min_length=1)
    """Qadamni bajaradigan agent."""

    needs: frozenset[Capability] = frozenset()
    """Aynan shu qadam uchun kerak bo'lgan imkoniyatlar."""


class Recipe(BaseModel, frozen=True):
    """Bitta TIZIM retsepti."""

    code: str = Field(pattern=r"^T0[1-6]$")
    """Retsept kodi (T01..T06) — slayddagi raqam."""

    name: str = Field(min_length=1)
    """Nomi (slayddagidek)."""

    promise: str = Field(min_length=1)
    """Ega uchun va'da — slayddagi bir qatorlik natija."""

    trigger_kind: TriggerKind
    """Vaqt yoki hodisa."""

    trigger_spec: str
    """Cron ifodasi (TIME) yoki hodisa turi (EVENT)."""

    steps: list[RecipeStep]
    """Qadamlar."""

    result: str = Field(min_length=1)
    """Natija — nima bo'lib chiqadi."""

    autonomy_level: AutonomyLevel = AutonomyLevel.L2_PIPELINE
    """Retsept talab qiladigan avtonomiya darajasi."""

    @property
    def required(self) -> frozenset[Capability]:
        """Barcha qadamlarning imkoniyatlari birlashmasi."""
        needed: set[Capability] = set()
        for step in self.steps:
            needed |= step.needs
        return frozenset(needed)


class RecipeReadiness(BaseModel, frozen=True):
    """Retseptning tayyorligi — halol hisobot."""

    code: str
    """Retsept kodi."""

    name: str
    """Retsept nomi."""

    status: RecipeStatus
    """READY yoki MISSING_CAPABILITY."""

    missing: list[Capability] = Field(default_factory=list)
    """Yetishmayotgan imkoniyatlar (bo'sh = hammasi bor)."""

    blocked_steps: list[int] = Field(default_factory=list)
    """Qaysi qadamlar bajarilmaydi."""

    @property
    def is_ready(self) -> bool:
        """O'rnatilishi mumkinmi."""
        return self.status == RecipeStatus.READY


# ── 6 retsept (slayddagi tartibda) ────────────────────────────────

RECIPES: Final[tuple[Recipe, ...]] = (
    Recipe(
        code="T01",
        name="Uchrashuv kotibi",
        promise="Kun tartibi o'zi yig'iladi — siz yozishmani qayta o'qimaysiz",
        trigger_kind=TriggerKind.EVENT,
        trigger_spec="chat.meeting_intent",
        steps=[
            RecipeStep(
                order=1,
                title="Yozishmani o'qib mavzuni tushunish",
                agent_name="operations",
                needs=frozenset({Capability.LLM}),
            ),
            RecipeStep(
                order=2,
                title="Bo'sh vaqtni topib taklif qilish",
                agent_name="operations",
                needs=frozenset({Capability.CALENDAR}),
            ),
            RecipeStep(
                order=3,
                title="Uchrashuv havolasini yaratish",
                agent_name="operations",
                needs=frozenset({Capability.MEETING_LINK, Capability.CALENDAR}),
            ),
        ],
        result="Kalendarda uchrashuv + ikkala tomonga 10 daqiqalik eslatma",
    ),
    Recipe(
        code="T02",
        name="Ovozdan rejaga",
        promise="'Keyin eslab qolaman' degan yo'qotish tugaydi",
        trigger_kind=TriggerKind.EVENT,
        trigger_spec="telegram.voice_message",
        steps=[
            RecipeStep(
                order=1,
                title="Ovozni matnga o'girib asosiy fikrni ajratish",
                agent_name="operations",
                needs=frozenset({Capability.STT, Capability.LLM}),
            ),
            RecipeStep(
                order=2,
                title="Aniq vazifalarga bo'lish",
                agent_name="operations",
                needs=frozenset({Capability.LLM}),
            ),
            RecipeStep(
                order=3,
                title="Muddat va mas'ul biriktirish",
                agent_name="operations",
                needs=frozenset({Capability.TASK_BOARD, Capability.CALENDAR}),
            ),
        ],
        result="Hech narsa yozmasdan kalendar va vazifalar ro'yxati to'ladi",
    ),
    Recipe(
        code="T03",
        name="Guruh razvedkasi",
        promise="12 ta guruhni o'zingiz varaqlab chiqmaysiz",
        trigger_kind=TriggerKind.TIME,
        trigger_spec="0 19 * * *",
        steps=[
            RecipeStep(
                order=1,
                title="Barcha ish guruhlarini o'qish",
                agent_name="operations",
                needs=frozenset({Capability.TELEGRAM_READ_GROUPS}),
            ),
            RecipeStep(
                order=2,
                title="Vazifa / shikoyat / muammoni ajratish",
                agent_name="operations",
                needs=frozenset({Capability.LLM}),
            ),
            RecipeStep(
                order=3,
                title="Kim mas'ul va nima kutilayotganini belgilash",
                agent_name="ceo",
                needs=frozenset({Capability.LLM, Capability.TELEGRAM_SEND}),
            ),
        ],
        result="Bitta qisqa hisobot: 'bugun nima yonmoqda'",
    ),
    Recipe(
        code="T04",
        name="Kontent konveyeri",
        promise="Kanal siz band bo'lgan kunlarda ham yashaydi",
        trigger_kind=TriggerKind.TIME,
        trigger_spec="0 10 * * *",
        steps=[
            RecipeStep(
                order=1,
                title="Navbatdagi postni olib matnini tayyorlash",
                agent_name="smm",
                needs=frozenset({Capability.LLM}),
            ),
            RecipeStep(
                order=2,
                title="Vizualni yig'ib ko'rsatish",
                agent_name="smm",
                needs=frozenset({Capability.LLM, Capability.TELEGRAM_SEND}),
            ),
            RecipeStep(
                order=3,
                title="'To'xta' demasangiz davom etadi",
                agent_name="smm",
                needs=frozenset({Capability.TIMED_APPROVAL, Capability.CONTENT_PUBLISH}),
            ),
        ],
        result="17:00 da avtomatik chop etadi va havolani yuboradi",
    ),
    Recipe(
        code="T05",
        name="Lid yo'li",
        promise="Kontent shunchaki ko'rsatmaydi — sotadi",
        trigger_kind=TriggerKind.EVENT,
        trigger_spec="instagram.comment_or_direct",
        steps=[
            RecipeStep(
                order=1,
                title="Sizning ohangingizda javob berish",
                agent_name="sales",
                needs=frozenset({Capability.INSTAGRAM_WEBHOOK, Capability.LLM}),
            ),
            RecipeStep(
                order=2,
                title="Savollar bilan ehtiyoj va budjetni aniqlash",
                agent_name="sales",
                needs=frozenset({Capability.LLM, Capability.CRM}),
            ),
            RecipeStep(
                order=3,
                title="Bo'sh vaqtni taklif qilish",
                agent_name="sales",
                needs=frozenset({Capability.CALENDAR}),
            ),
        ],
        result="Qo'lda yozmasdan uchrashuv band qilinadi",
    ),
    Recipe(
        code="T06",
        name="Kunlik puls",
        promise="Nazorat yo'qolmaydi — hisobot so'rashingiz shart emas",
        trigger_kind=TriggerKind.TIME,
        trigger_spec="20 9 * * *",
        steps=[
            RecipeStep(
                order=1,
                title="Barcha loyiha doskalarini tekshirish",
                agent_name="operations",
                needs=frozenset({Capability.TASK_BOARD}),
            ),
            RecipeStep(
                order=2,
                title="Siljiganini va turib qolganini ajratish",
                agent_name="operations",
                needs=frozenset({Capability.LLM}),
            ),
            RecipeStep(
                order=3,
                title="Qaroringizni kutayotganini yig'ish",
                agent_name="ceo",
                needs=frozenset({Capability.LLM, Capability.TELEGRAM_SEND}),
            ),
        ],
        result="3 qatorli xabar: siljidi / turib qoldi / qaror kutilmoqda",
    ),
)


def get_recipe(code: str) -> Recipe | None:
    """Kod bo'yicha retsept."""
    return next((r for r in RECIPES if r.code == code.upper()), None)


def detect_capabilities(
    settings: Settings,
    tool_registry: ToolRegistry | None = None,
) -> frozenset[Capability]:
    """Hozir HAQIQATAN mavjud imkoniyatlarni aniqlash.

    Faqat konfiguratsiya va ro'yxatdan o'tgan tool'larga qaraydi —
    tarmoqqa chiqmaydi. "Kalit bor" degani "ishlaydi" degani emas,
    lekin "kalit yo'q" degani aniq "ishlamaydi" — biz shu ikkinchisini
    ishonchli aytamiz.
    """
    available: set[Capability] = {Capability.CRON, Capability.CRM}

    if settings.has_any_llm_provider:
        available.add(Capability.LLM)

    if settings.telegram_bot_token is not None:
        available.add(Capability.TELEGRAM_SEND)

    tool_names = (
        {tool.name for tool in tool_registry.list_tools()} if tool_registry is not None else set()
    )
    publish_tools = {"instagram.publish_photo", "youtube.publish", "telegram.channel_post"}
    if tool_names & publish_tools:
        available.add(Capability.CONTENT_PUBLISH)

    # Quyidagilar ATAYLAB qo'shilmaydi — ZET'da hali yo'q. Ular
    # qo'shilganda shu yerga bitta qator yoziladi, retseptlar esa
    # o'zgarishsiz "ready" bo'ladi:
    #   CALENDAR, MEETING_LINK, TASK_BOARD, TIMED_APPROVAL,
    #   TELEGRAM_READ_GROUPS (MTProto), INSTAGRAM_WEBHOOK,
    #   STT (voice/stt.py hozir StubSTT)
    return frozenset(available)


def evaluate(recipe: Recipe, available: frozenset[Capability]) -> RecipeReadiness:
    """Retsept hozir ishlay oladimi — va ishlamasa, nega."""
    missing = sorted(recipe.required - available)
    blocked = sorted(step.order for step in recipe.steps if step.needs - available)

    return RecipeReadiness(
        code=recipe.code,
        name=recipe.name,
        status=RecipeStatus.MISSING_CAPABILITY if missing else RecipeStatus.READY,
        missing=missing,
        blocked_steps=blocked,
    )


def evaluate_all(available: frozenset[Capability]) -> list[RecipeReadiness]:
    """Oltita retseptning tayyorlik hisoboti."""
    return [evaluate(recipe, available) for recipe in RECIPES]


class RecipeNotReadyError(RuntimeError):
    """Imkoniyati yetishmagan retseptni o'rnatishga urinish."""


def install(
    recipe: Recipe,
    engine: AutomationEngine,
    available: frozenset[Capability],
) -> str:
    """Tayyor retseptni Automation Engine'ga o'rnatish.

    TIME retsepti — `ScheduleRule`; EVENT retsepti — `EventTrigger`.
    Har ikkalasi ham mavjud yo'ldan boradi, ya'ni retseptlar uchun
    alohida bajarish mexanizmi YO'Q.

    Returns:
        Yaratilgan qoida/trigger ID

    Raises:
        RecipeNotReadyError: imkoniyat yetishmaydi
    """
    readiness = evaluate(recipe, available)
    if not readiness.is_ready:
        names = ", ".join(c.value for c in readiness.missing)
        msg = (
            f"'{recipe.name}' ({recipe.code}) o'rnatilmaydi — "
            f"quyidagi imkoniyatlar yo'q: {names}. "
            f"Chala ishlaydigan avtomatlashtirish o'rnatilmaydi."
        )
        raise RecipeNotReadyError(msg)

    command = _command_for(recipe)
    lead_agent = recipe.steps[0].agent_name

    if recipe.trigger_kind == TriggerKind.TIME:
        rule = engine.add_schedule(
            ScheduleRule(
                name=f"{recipe.code} · {recipe.name}",
                agent_name=lead_agent,
                cron_expr=recipe.trigger_spec,
                command=command,
            )
        )
        log.info("recipe.installed", code=recipe.code, kind="schedule", id=rule.id)
        return rule.id

    trigger = engine.add_trigger(
        EventTrigger(
            name=f"{recipe.code} · {recipe.name}",
            trigger_type=TriggerType.WEBHOOK,
            agent_name=lead_agent,
            conditions=[
                TriggerCondition(field="event_type", operator="eq", value=recipe.trigger_spec)
            ],
            command_template=command,
        )
    )
    log.info("recipe.installed", code=recipe.code, kind="trigger", id=trigger.id)
    return trigger.id


def _command_for(recipe: Recipe) -> str:
    """Retseptdan agent buyrug'ini yasash — qadamlar ro'yxati sifatida."""
    lines = [f"TIZIM {recipe.code}: {recipe.name}", "", "Qadamlar:"]
    lines.extend(f"{step.order}. {step.title}" for step in recipe.steps)
    lines.extend(["", f"Kutilayotgan natija: {recipe.result}"])
    return "\n".join(lines)


__all__ = [
    "RECIPES",
    "Capability",
    "Recipe",
    "RecipeNotReadyError",
    "RecipeReadiness",
    "RecipeStatus",
    "RecipeStep",
    "TriggerKind",
    "detect_capabilities",
    "evaluate",
    "evaluate_all",
    "get_recipe",
    "install",
]
