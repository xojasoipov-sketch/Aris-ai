"""6 TIZIM retsepti — ega yuborgan tayyor avtomatlashtirishlar (yangi zip).

Slaydlarning yakuniy va'dasi:

    "Sizga qoladi: faqat qaror qabul qilish. Qolgani — yozish,
     tekshirish, eslatish, chop etish — tizimda."

Har bir retsept: TRIGGER → 3 QADAM → NATIJA.

    01 Uchrashuv kotibi   — yozishmani o'qib uchrashuv qo'yadi
    02 Ovozdan rejaga     — ovozli xabar → vazifa + deadline
    03 Guruh razvedkasi   — ish guruhlarini o'qib "nima yonmoqda" hisoboti
    04 Kontent konveyeri  — post tayyorlaydi, ega ANIQ tasdiqlagach chop etadi
    05 Lid yo'li          — izoh/Direct → savol → slot taklifi
    06 Kunlik puls        — doskalarni tekshirib 3 qatorli hisobot

ENG MUHIM QARQOR — HALOL HOLAT.

Retseptlarning bir qismi ZET'da hali BO'LMAGAN tashqi imkoniyatlarga
tayanadi (MTProto guruh o'qish, Instagram webhook, uchrashuv havolasi).
Ikki yo'l bor edi:

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

MUHIM TUZATISH (KONSOLIDATSIYA v2, tungi reja Bo'lim B, B2): T04
ilgari "TIMED_APPROVAL" ("sukut = rozilik" — javob berilmasa
belgilangan vaqtda avtomatik nashr) deb nomlangan HALI QURILMAGAN
imkoniyatga tayanardi. Bu boshqa to'rtta yetishmovchilikdan (MTProto,
Instagram webhook, uchrashuv havolasi) TUBDAN FARQLI edi: ular
"hali yo'q, lekin qo'shilishi mumkin" — TIMED_APPROVAL esa V-32
("EXECUTE — DOIM ANIQ tasdiq, sukut ovoz emas") tamoyiliga TO'G'RIDAN
-TO'G'RI zid, ya'ni HECH QACHON qo'shilmasligi kerak bo'lgan dizayn
edi. Ega buyrug'i aniq: "'sukut=rozilik' rejimini TAKLIF QILMA".
Shuning uchun `Capability.TIMED_APPROVAL` BUTUNLAY OLIB TASHLANDI (nafaqat
T04'dan — konsepsiyaning o'zi kod bazasidan chiqarildi) va T04 endi
ODDIY, ALLAQACHON ISHLAYDIGAN `ApprovalService` yo'lidan foydalanadi:
kontent tayyorlanadi → ega ANIQ tasdig'i so'raladi (`content.publish`
tool'lari `security/risk.py`da HIGH-risk, `PermissionPolicy` orqali
avtomatik `ApprovalRequiredError`) → FAQAT tasdiqdan keyin nashr
qilinadi. Bonus: bu T04'ni ENDI YANGI IMKONIYAT KUTMAYDIGAN qildi —
`content.publish` allaqachon aniqlanadigan (`detect_capabilities()`)
imkoniyat, ya'ni Telegram/Instagram/YouTube ulanishi bo'lsa T04
darhol READY bo'ladi.

Bog'liq qarorlar:
    Yangi zip — 6 TIZIM retsepti
    docs/12-AUTONOMY-GAP.md — imkoniyat matritsasi
    V-32 — tasdiq (04 va 05 yozuv amallarini o'z ichiga oladi, HECH QACHON
        taymerli/sukut emas — faqat ANIQ tasdiq)
    A-05 — izoh/Direct/guruh xabari UNTRUSTED
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

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
    """Uchrashuv yozish va jadvalni o'qish.

    ZET'ning ICHKI kalendari (Z46 jadvali + Z48 `calendar.add`/`calendar.list`
    tool'lari). Google Calendar sinxronizatsiyasi ALOHIDA ish — u yo'qligi
    ichki kalendarga yozishga to'sqinlik qilmaydi."""

    MEETING_LINK = "meeting_link"
    """Zoom/Meet havolasi yaratish. ZET'da hali yo'q."""

    STT = "stt"
    """Ovozdan matnga.

    `ELEVENLABS_API_KEY` bo'lsa — `ElevenLabsSTT` (Scribe) haqiqiy
    transkripsiya qiladi. Kalitsiz `StubSTT` qotgan matn qaytaradi,
    ya'ni imkoniyat YO'Q."""

    CONTENT_PUBLISH = "content.publish"
    """Kontentni chop etish (Instagram/YouTube/Telegram kanal)."""

    INSTAGRAM_WEBHOOK = "instagram.webhook"
    """Izoh/Direct hodisalarini qabul qilish. Obuna sozlanmagan."""

    CRM = "crm"
    """Kontakt/lid yozuvlari."""

    TASK_BOARD = "task_board"
    """Loyiha doskasi (vazifa holatlari).

    Z46'da `project`/`task` jadvallari, Z48'da esa `task.list`/`task.create`/
    `task.update`/`task.pulse` tool'lari qo'shildi — ya'ni agent doskani
    HAQIQATAN o'qiy va yoza oladi."""

    # `TIMED_APPROVAL` ("approval.timed" — "sukut = rozilik" taymerli
    # tasdiq) ATAYLAB OLIB TASHLANDI (KONSOLIDATSIYA v2, B2). Bu
    # boshqa "hali yo'q" imkoniyatlardan farqli — V-32'ga ("EXECUTE
    # har doim ANIQ tasdiq talab qiladi") to'g'ridan-to'g'ri zid dizayn
    # edi, shuning uchun "hali qurilmagan" emas, "hech qachon
    # qurilmaydi" toifasiga tegishli. T04 endi ODDIY `content.publish`
    # + mavjud `ApprovalService` (aniq tasdiq) orqali ishlaydi —
    # pastdagi T04 ta'rifiga qarang.


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

    also_at: tuple[str, ...] = ()
    """Qo'shimcha cron ifodalari (faqat TIME retseptlari uchun).

    Slaydda "Kunlik puls" KUNIGA IKKI MARTA ishlaydi: 09:20 va 18:40.
    Bitta 5-maydonli cron ifodasi buni bera olmaydi — daqiqalar har xil
    (20 va 40), `20,40 9,18 * * *` esa kunda TO'RT marta ishlab ketardi
    (09:40 va 18:20 ham). Shuning uchun har bir vaqt alohida qoida
    bo'ladi."""

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
        # B3 audit fix (KONSOLIDATSIYA v2): ilgari bu matn 3-qadam
        # (havola yaratish, MEETING_LINK — ZET'da hali yo'q, doim
        # bloklangan) muvaffaqiyatli bo'lgandek "ikkala tomonga 10
        # daqiqalik eslatma"ni SO'ZSIZ va'da qilardi. Endi natija
        # matnining o'zi shartli: eslatma FAQAT havola yaratilgach
        # yuboriladi — bu shart hozir ham, MEETING_LINK qo'shilgan
        # kunda ham TO'G'RI qoladi.
        result=(
            "Kalendarda vaqt taklif qilinadi; ikkala tomonga eslatma "
            "FAQAT uchrashuv havolasi yaratilgach yuboriladi (bu "
            "funksiya hozircha yo'q — 3-qadam bloklangan)."
        ),
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
                title="Ega ANIQ tasdiqlagach nashr qilish",
                agent_name="smm",
                # B2 audit fix (KONSOLIDATSIYA v2): ilgari
                # `Capability.TIMED_APPROVAL` ("sukut = rozilik") ham
                # talab qilinardi — bu ZET'da HECH QACHON qurilmaydigan,
                # V-32'ga zid dizayn edi (ega buyrug'i: "TAKLIF QILMA").
                # Endi bu qadam ODDIY, allaqachon ishlaydigan yo'ldan
                # boradi: `content.publish` toollari (instagram.publish_
                # photo/youtube.publish/telegram.channel_post) HIGH-risk
                # (`security/risk.py`), `PermissionPolicy` ularni avtomatik
                # `ApprovalRequiredError`ga yo'naltiradi — ega ANIQ
                # tasdiqlamaguncha (yoki rad etmaguncha) nashr BO'LMAYDI.
                needs=frozenset({Capability.CONTENT_PUBLISH}),
            ),
        ],
        result=(
            "Kontent tayyor bo'lgach ega tasdig'i so'raladi — FAQAT "
            "aniq 'ha/tasdiqlayman' javobidan keyin nashr qilinadi va "
            "havola yuboriladi. Sukut = hech narsa qilinmaydi, nashr EMAS."
        ),
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
        also_at=("40 18 * * *",),
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

    if settings.elevenlabs_api_key is not None:
        # `get_stt()` kalit bo'lganda `ElevenLabsSTT` (Scribe) tanlaydi —
        # ovoz HAQIQATAN matnga o'giriladi. Kalitsiz `StubSTT` qotgan matn
        # qaytaradi, ya'ni imkoniyat yo'q.
        available.add(Capability.STT)

    tools = list(tool_registry.list_tools()) if tool_registry is not None else []
    tool_names = {tool.name for tool in tools}
    publish_tools = {"instagram.publish_photo", "youtube.publish", "telegram.channel_post"}
    if tool_names & publish_tools:
        available.add(Capability.CONTENT_PUBLISH)

    # Doska va kalendar — tool ro'yxatda TURISHI yetarli emas: DB fabrikasi
    # ulanmagan bo'lsa tool chaqirilganda yiqiladi. `connected` aynan shuni
    # ajratadi, shuning uchun "imkoniyat bor" degani yolg'on bo'lmaydi.
    if _connected(tools, "task.list", "task.create", "task.pulse"):
        available.add(Capability.TASK_BOARD)
    if _connected(tools, "calendar.list", "calendar.add"):
        available.add(Capability.CALENDAR)

    # Quyidagilar ATAYLAB qo'shilmaydi — ZET'da hali yo'q. Ular
    # qo'shilganda shu yerga bitta qator yoziladi, retseptlar esa
    # o'zgarishsiz "ready" bo'ladi:
    #   MEETING_LINK, TELEGRAM_READ_GROUPS (MTProto), INSTAGRAM_WEBHOOK
    # (`TIMED_APPROVAL` bu ro'yxatda YO'Q — u "hali qurilmagan" emas,
    # KONSOLIDATSIYA v2 B2'da butunlay OLIB TASHLANGAN, chunki V-32'ga
    # zid edi va hech qachon qo'shilmaydi.)
    return frozenset(available)


def _connected(tools: list[Any], *names: str) -> bool:
    """Nomlangan tool'larning HAMMASI mavjud va ulangan bo'lsa — True.

    `connected` xossasi bo'lmagan tool "ulangan" deb hisoblanadi: bu
    xossa faqat tashqi manbaga bog'liq tool'larda bor va uni bilmagan
    tool o'zi ishlaydi."""
    by_name = {tool.name: tool for tool in tools}
    return all(name in by_name and getattr(by_name[name], "connected", True) for name in names)


def evaluate(recipe: Recipe, available: frozenset[Capability]) -> RecipeReadiness:
    """Retsept hozir ishlay oladimi — va ishlamasa, nega.

    B4 audit fix (KONSOLIDATSIYA v2, tungi reja): qadamlar bitta agent
    chaqiruvida KETMA-KET bajariladi (`_command_for()` barcha qadam
    sarlavhalarini bitta buyruqqa yig'adi, alohida bajarish mexanizmi
    YO'Q) — demak N-qadam O'Z ehtiyojini qondirsa ham, undan OLDIN
    biror qadam bloklangan bo'lsa, N-qadamga navbat UMUMAN yetmaydi.

    Ilgari har qadam faqat O'Z ehtiyojiga qarab mustaqil bloklanardi.
    Natijada masalan T05'da (1-qadam INSTAGRAM_WEBHOOK'ga muhtoj, hali
    yo'q) 2/3-qadamlar o'z ehtiyoji (LLM/CRM/CALENDAR) mavjud bo'lgani
    uchun interfeysda "ishlaydi" bo'lib ko'rinardi — garchi 1-qadam
    hech qachon bajarilmagani uchun ular ham hech qachon ishga
    tushmasa ham. Endi bloklangan birinchi qadamdan KEYINGI barcha
    qadamlar ham blocked_steps'ga qo'shiladi.
    """
    missing = sorted(recipe.required - available)
    own_blocked = {step.order for step in recipe.steps if step.needs - available}
    first_blocked = min(own_blocked) if own_blocked else None
    blocked = sorted(
        step.order
        for step in recipe.steps
        if step.order in own_blocked or (first_blocked is not None and step.order > first_blocked)
    )

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
        Yaratilgan qoida/trigger ID (`also_at` bo'lsa — birinchisi)

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
        ids = [
            engine.add_schedule(
                ScheduleRule(
                    name=f"{recipe.code} · {recipe.name}",
                    agent_name=lead_agent,
                    cron_expr=cron_expr,
                    command=command,
                )
            ).id
            for cron_expr in (recipe.trigger_spec, *recipe.also_at)
        ]
        log.info("recipe.installed", code=recipe.code, kind="schedule", ids=ids)
        return ids[0]

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
