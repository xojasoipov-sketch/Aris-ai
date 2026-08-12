"""Kuzatuv triggeri (watcher) — agentning 3-xususiyati (yangi zip, slayd 10).

Ega ta'rifi: *"Kuzatuv — metrikani kuzatib turadi, o'zgarganda uyg'onadi."*

Farqi `ScheduleRule`dan: jadval **vaqtga** qaraydi, watcher **qiymatga**.
Farqi `EventTrigger`dan: trigger tashqaridan kelgan hodisani **kutadi**,
watcher esa o'zi **borib o'lchaydi**.

Ish tartibi:

    1. `MetricReader` metrikaning joriy qiymatini qaytaradi
    2. `WatchRule` uni oldingi qiymat bilan solishtiradi
    3. Shart bajarilsa — `AutomationEvent` chiqadi (`watch.<metric>`)
    4. `AutomationEngine.process_event()` mos triggerlarni topib bajaradi

Ya'ni watcher **o'zi agent ishga tushirmaydi** — u hodisa ishlab
chiqaradi. Shu sabab watcher va webhook bitta yo'ldan boradi va bitta
xavfsizlik tekshiruvidan o'tadi.

Birinchi o'lchov — **baza qiymat**: hech qachon ishga tushirmaydi.
Aks holda tizim har qayta ishga tushganda soxta signal berardi.

Xavfsizlik:
    - `cooldown_s` — bir xil signal ketma-ket yog'ilishining oldini oladi
    - `max_fires` — cheksiz tsiklga tormoz (A-07)
    - Kill-switch/uyqu — `AutomationDaemon` darajasida tekshiriladi

Bog'liq qarorlar:
    Yangi zip — 3-xususiyat (kuzatuv)
    Bo'lim 9 — avtomatlashtirish
    A-07 — tormozlar
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import StrEnum

import structlog
from pydantic import BaseModel, Field

from zet.automation.events import AutomationEvent

log = structlog.get_logger(__name__)

MetricReader = Callable[[str], Awaitable[float | None]]
"""Metrika o'quvchi: nom → joriy qiymat (None = o'lchab bo'lmadi)."""


class WatchComparison(StrEnum):
    """Watcher qachon uyg'onishi kerakligini belgilaydigan shart."""

    CHANGED = "changed"
    """Qiymat oldingisidan farq qilsa (qaysi tomonga — muhim emas)."""

    ABOVE = "above"
    """Qiymat chegaradan yuqori bo'lgan HAR o'lchovda (daraja-triggeri)."""

    BELOW = "below"
    """Qiymat chegaradan past bo'lgan HAR o'lchovda (daraja-triggeri)."""

    CROSSES_ABOVE = "crosses_above"
    """Chegarani pastdan yuqoriga KESIB o'tgan payt (qirra-triggeri)."""

    CROSSES_BELOW = "crosses_below"
    """Chegarani yuqoridan pastga KESIB o'tgan payt (qirra-triggeri)."""

    DELTA_PCT = "delta_pct"
    """Oldingi qiymatdan foizda `threshold` dan ko'proq siljigan bo'lsa."""


class WatchRule(BaseModel, frozen=True):
    """Bitta kuzatuv qoidasi — bitta metrika, bitta shart."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    """Unikal qoida ID."""

    name: str = Field(min_length=1, max_length=100)
    """Qoida nomi (masalan: 'Kanal obunachilari tushib ketdi')."""

    metric: str = Field(min_length=1, max_length=120)
    """Kuzatiladigan metrika nomi (`MetricRegistry`dagi kalit)."""

    comparison: WatchComparison = WatchComparison.CHANGED
    """Uyg'onish sharti."""

    threshold: float = 0.0
    """Chegara qiymati (`CHANGED` uchun ishlatilmaydi)."""

    enabled: bool = True
    """Qoida yoqilganmi."""

    cooldown_s: int = Field(default=300, ge=0)
    """Ikki signal orasidagi minimal vaqt (standart 5 daqiqa)."""

    max_fires: int | None = None
    """Maksimal signal soni (None = cheksiz)."""

    fire_count: int = 0
    """Nechta signal berilgan."""

    last_value: float | None = None
    """Oxirgi o'lchangan qiymat (baza)."""

    last_checked_at: datetime | None = None
    """Oxirgi o'lchov vaqti."""

    last_fired_at: datetime | None = None
    """Oxirgi signal vaqti."""

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    """Yaratilgan vaqt."""

    @property
    def is_active(self) -> bool:
        """Qoida hali ishlaydimi."""
        if not self.enabled:
            return False
        return not (self.max_fires is not None and self.fire_count >= self.max_fires)

    def in_cooldown(self, now: datetime) -> bool:
        """Oxirgi signaldan beri `cooldown_s` o'tmaganmi."""
        if self.cooldown_s <= 0 or self.last_fired_at is None:
            return False
        return (now - self.last_fired_at).total_seconds() < self.cooldown_s

    def should_fire(self, value: float) -> bool:
        """Yangi qiymat signal berishga arziydimi.

        Birinchi o'lchov (`last_value is None`) hech qachon signal bermaydi —
        u faqat baza o'rnatadi.
        """
        previous = self.last_value
        if previous is None:
            return False

        match self.comparison:
            case WatchComparison.CHANGED:
                return not math.isclose(value, previous, rel_tol=1e-9, abs_tol=1e-12)
            case WatchComparison.ABOVE:
                return value > self.threshold
            case WatchComparison.BELOW:
                return value < self.threshold
            case WatchComparison.CROSSES_ABOVE:
                return previous <= self.threshold < value
            case WatchComparison.CROSSES_BELOW:
                return previous >= self.threshold > value
            case WatchComparison.DELTA_PCT:
                if math.isclose(previous, 0.0, abs_tol=1e-12):
                    # Noldan har qanday siljish — cheksiz foiz; faqat
                    # haqiqiy o'zgarish bo'lsa signal beramiz.
                    return not math.isclose(value, 0.0, abs_tol=1e-12)
                return abs(value - previous) / abs(previous) * 100.0 >= self.threshold

    def describe(self) -> str:
        """Ega o'qiydigan shart tavsifi."""
        match self.comparison:
            case WatchComparison.CHANGED:
                return f"{self.metric} o'zgarganda"
            case WatchComparison.ABOVE:
                return f"{self.metric} > {self.threshold:g}"
            case WatchComparison.BELOW:
                return f"{self.metric} < {self.threshold:g}"
            case WatchComparison.CROSSES_ABOVE:
                return f"{self.metric} {self.threshold:g} dan oshib ketganda"
            case WatchComparison.CROSSES_BELOW:
                return f"{self.metric} {self.threshold:g} dan tushib ketganda"
            case WatchComparison.DELTA_PCT:
                return f"{self.metric} ≥{self.threshold:g}% siljiganda"


def _with(rule: WatchRule, **changes: object) -> WatchRule:
    """Frozen qoidaning yangilangan nusxasi (repo uslubi: o'zgarmas modellar)."""
    return WatchRule.model_validate({**rule.model_dump(), **changes})


class MetricRegistry:
    """Metrika manbalari registri — nom → o'lchovchi funksiya.

    Watcher hech qanday tizimga to'g'ridan-to'g'ri bog'lanmaydi: kim
    metrikani bera olsa, shu yerga o'zini ro'yxatdan o'tkazadi. Shu sabab
    testda ham, produksiyada ham bitta kod yo'li ishlaydi.
    """

    def __init__(self) -> None:
        self._probes: dict[str, Callable[[], Awaitable[float | None]]] = {}

    def register(self, metric: str, probe: Callable[[], Awaitable[float | None]]) -> None:
        """Metrika manbasini ro'yxatdan o'tkazish."""
        self._probes[metric] = probe
        log.info("watcher.metric_registered", metric=metric)

    def unregister(self, metric: str) -> bool:
        """Metrika manbasini olib tashlash."""
        return self._probes.pop(metric, None) is not None

    @property
    def known(self) -> list[str]:
        """Ro'yxatdan o'tgan metrikalar."""
        return sorted(self._probes)

    async def read(self, metric: str) -> float | None:
        """Metrikani o'qish. Manba yo'q yoki xato bersa — `None`."""
        probe = self._probes.get(metric)
        if probe is None:
            return None
        try:
            return await probe()
        except Exception:
            log.exception("watcher.metric_read_failed", metric=metric)
            return None


class WatcherRegistry:
    """Kuzatuv qoidalari registri (xotirada, `TriggerRegistry` bilan bir uslubda)."""

    def __init__(self) -> None:
        self._rules: dict[str, WatchRule] = {}

    def add(self, rule: WatchRule) -> WatchRule:
        """Yangi kuzatuv qoidasi."""
        self._rules[rule.id] = rule
        log.info(
            "watcher.added",
            id=rule.id,
            name=rule.name,
            metric=rule.metric,
            comparison=rule.comparison.value,
        )
        return rule

    def get(self, rule_id: str) -> WatchRule | None:
        """Qoidani olish."""
        return self._rules.get(rule_id)

    def list_rules(self, *, metric: str | None = None) -> list[WatchRule]:
        """Qoidalar ro'yxati."""
        rules = list(self._rules.values())
        if metric is None:
            return rules
        return [r for r in rules if r.metric == metric]

    def remove(self, rule_id: str) -> bool:
        """Qoidani o'chirish."""
        if rule_id in self._rules:
            del self._rules[rule_id]
            log.info("watcher.removed", id=rule_id)
            return True
        return False

    def disable(self, rule_id: str) -> WatchRule | None:
        """Qoidani to'xtatish."""
        rule = self._rules.get(rule_id)
        if rule is None:
            return None
        updated = _with(rule, enabled=False)
        self._rules[rule_id] = updated
        return updated

    def enable(self, rule_id: str) -> WatchRule | None:
        """Qoidani qayta yoqish."""
        rule = self._rules.get(rule_id)
        if rule is None:
            return None
        updated = _with(rule, enabled=True)
        self._rules[rule_id] = updated
        return updated

    async def poll(
        self, metrics: MetricRegistry, *, now: datetime | None = None
    ) -> list[AutomationEvent]:
        """Barcha faol qoidalarni bir marta o'lchash.

        Args:
            metrics: Metrika manbalari
            now: O'lchov vaqti (cooldown uchun; standart — joriy vaqt)

        Returns:
            Signal bergan qoidalar uchun hodisalar ro'yxati
        """
        moment = now or datetime.now(UTC)
        events: list[AutomationEvent] = []

        for rule_id, rule in list(self._rules.items()):
            if not rule.is_active:
                continue

            value = await metrics.read(rule.metric)
            if value is None:
                log.debug("watcher.metric_unavailable", rule_id=rule_id, metric=rule.metric)
                continue

            fires = rule.should_fire(value) and not rule.in_cooldown(moment)
            previous = rule.last_value

            self._rules[rule_id] = _with(
                rule,
                last_value=value,
                last_checked_at=moment,
                **({"fire_count": rule.fire_count + 1, "last_fired_at": moment} if fires else {}),
            )

            if not fires:
                continue

            events.append(
                AutomationEvent(
                    event_type=f"watch.{rule.metric}",
                    source=f"watcher.{rule_id}",
                    data={
                        "watch_rule_id": rule_id,
                        "watch_rule_name": rule.name,
                        "metric": rule.metric,
                        "comparison": rule.comparison.value,
                        "value": f"{value:g}",
                        "previous": "" if previous is None else f"{previous:g}",
                        "threshold": f"{rule.threshold:g}",
                        "direction": _direction(previous, value),
                    },
                    timestamp=moment,
                )
            )
            log.info(
                "watcher.fired",
                rule_id=rule_id,
                metric=rule.metric,
                value=value,
                previous=previous,
            )

        return events

    @property
    def stats(self) -> dict[str, int]:
        """Statistika."""
        rules = list(self._rules.values())
        return {
            "total": len(rules),
            "active": sum(1 for r in rules if r.is_active),
            "disabled": sum(1 for r in rules if not r.enabled),
            "fired_total": sum(r.fire_count for r in rules),
        }


def _direction(previous: float | None, value: float) -> str:
    """O'zgarish yo'nalishi — buyruq shablonida `{direction}` uchun."""
    if previous is None:
        return "unknown"
    if value > previous:
        return "up"
    if value < previous:
        return "down"
    return "flat"


__all__ = [
    "MetricReader",
    "MetricRegistry",
    "WatchComparison",
    "WatchRule",
    "WatcherRegistry",
]
