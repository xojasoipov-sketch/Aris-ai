"""Avtomatlashtirish holati qayta ishga tushishdan omon qoladi (Z48.2).

NEGA BU TESTLAR BOR.

`AutomationEngine` `lru_cache` singleton — to'liq xotirada. Ega TIZIM
retseptini yoqsa, u ishlardi, lekin konteyner qayta ishga tushishi
bilan JIMGINA yo'qolardi (Railway redeploy yetarli).

Bu soxta tugmadan ham yomonroq holat: soxta tugma darhol ko'rinadi,
bu esa bir necha kun ishlaydi va keyin sababsiz to'xtaydi — ega buni
faqat hisobot kelmaganda sezadi, ya'ni ishonch kerak bo'lgan paytda.

"Qayta ishga tushish" bu yerda YANGI `AutomationEngine` obyekti bilan
modellashtiriladi — jarayon o'lib qayta ko'tarilgani bilan bir xil.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from zet.automation.engine import AutomationEngine
from zet.automation.persistence import AutomationStore, restore, snapshot
from zet.automation.recipes import RECIPES, Capability, get_recipe, install
from zet.automation.scheduler import ScheduleRule, ScheduleStatus
from zet.automation.triggers import EventTrigger, TriggerCondition, TriggerType
from zet.automation.watcher import WatchComparison, WatchRule
from zet.db.models import Owner

ALL_CAPABILITIES = frozenset(Capability)


@pytest.fixture
def store(session: AsyncSession, owner: Owner) -> AutomationStore:
    return AutomationStore(session, owner_id=owner.id)


def _engine_with_rules() -> AutomationEngine:
    engine = AutomationEngine()
    engine.add_schedule(
        ScheduleRule(
            name="Kunlik hisobot",
            agent_name="operations",
            cron_expr="20 9 * * *",
            command="Doskani tekshir",
        )
    )
    engine.add_trigger(
        EventTrigger(
            name="Kamera signali",
            trigger_type=TriggerType.WEBHOOK,
            agent_name="operations",
            conditions=[TriggerCondition(field="event_type", operator="eq", value="motion")],
        )
    )
    engine.add_watch(
        WatchRule(
            name="Xarajat o'sdi",
            metric="cost.today_usd",
            comparison=WatchComparison.ABOVE,
            threshold=5.0,
        )
    )
    return engine


class TestSnapshotRoundTrip:
    def test_rules_survive_a_restart(self) -> None:
        before = _engine_with_rules()

        after = AutomationEngine()
        restored = restore(after, snapshot(before))

        assert restored == 3
        assert [r.name for r in after.scheduler.list_rules()] == ["Kunlik hisobot"]
        assert [t.name for t in after.triggers.list_triggers()] == ["Kamera signali"]
        assert [w.name for w in after.watchers.list_rules()] == ["Xarajat o'sdi"]

    def test_identifiers_are_preserved(self) -> None:
        """ID saqlanishi SHART.

        Yangi ID berilsa ega interfeysdagi "o'chirish" tugmasi mavjud
        bo'lmagan qoidaga murojaat qilib 404 olardi."""
        before = _engine_with_rules()
        original = before.scheduler.list_rules()[0].id

        after = AutomationEngine()
        restore(after, snapshot(before))

        assert after.scheduler.list_rules()[0].id == original

    def test_paused_rule_stays_paused(self) -> None:
        """To'xtatilgan qoida qayta ishga tushishda O'ZIDAN yoqilmasligi kerak."""
        before = _engine_with_rules()
        rule_id = before.scheduler.list_rules()[0].id
        before.scheduler.pause_rule(rule_id)

        after = AutomationEngine()
        restore(after, snapshot(before))

        assert after.scheduler.list_rules()[0].status is ScheduleStatus.PAUSED
        assert after.scheduler.active_rules == []

    def test_broken_entry_does_not_lose_the_others(self) -> None:
        """Bitta buzuq yozuv qolgan hammasini yo'qotmaydi."""
        data = snapshot(_engine_with_rules())
        data["schedules"].insert(0, {"nonsense": True})

        after = AutomationEngine()
        restored = restore(after, data)

        assert restored == 3
        assert len(after.scheduler.list_rules()) == 1

    def test_snapshot_is_json_serialisable(self) -> None:
        """`datetime`/`StrEnum` maydonlari JSON ustuniga yozilishi kerak."""
        import json

        json.dumps(snapshot(_engine_with_rules()))


class TestStore:
    async def test_saved_state_loads_into_a_fresh_engine(self, store: AutomationStore) -> None:
        await store.save(_engine_with_rules())

        fresh = AutomationEngine()
        loaded = await store.load(fresh)

        assert loaded == 3
        assert len(fresh.scheduler.list_rules()) == 1

    async def test_load_on_empty_database_is_not_an_error(self, store: AutomationStore) -> None:
        """Birinchi ishga tushishda hech narsa saqlanmagan — bu normal."""
        assert await store.load(AutomationEngine()) == 0

    async def test_second_save_replaces_the_first(self, store: AutomationStore) -> None:
        """Snapshot QO'SHILMAYDI, ALMASHADI — aks holda o'chirilgan qoida
        qayta ishga tushishda tirilib kelardi."""
        await store.save(_engine_with_rules())

        emptied = AutomationEngine()
        await store.save(emptied)

        fresh = AutomationEngine()
        assert await store.load(fresh) == 0

    async def test_installed_recipe_survives_a_restart(self, store: AutomationStore) -> None:
        """Eng muhim holat: yoqilgan TIZIM retsepti yo'qolmaydi."""
        engine = AutomationEngine()
        recipe = get_recipe("T06")
        assert recipe is not None
        install(recipe, engine, ALL_CAPABILITIES)
        await store.save(engine)

        fresh = AutomationEngine()
        await store.load(fresh)

        crons = {rule.cron_expr for rule in fresh.scheduler.list_rules()}
        assert crons == {"20 9 * * *", "40 18 * * *"}

    async def test_persist_without_a_database_does_not_raise(self) -> None:
        """FAIL-OPEN: baza yiqilgan bo'lsa ham so'rov 500 bo'lmaydi.

        Ega qo'shgan qoida XOTIRADA ishlab turaveradi; yagona yo'qotish —
        qayta ishga tushishdan omon qolmaslik, va u log'da ko'rinadi."""
        from zet.automation.persistence import persist_automation

        def broken() -> object:
            raise RuntimeError("baza yo'q")

        await persist_automation(
            _engine_with_rules(),
            broken,  # type: ignore[arg-type]
            owner_external_id="owner",
        )

    async def test_every_recipe_survives_a_restart(self, store: AutomationStore) -> None:
        """Oltita retseptning HAMMASI — kelajakda tayyor bo'lganda ham."""
        engine = AutomationEngine()
        for recipe in RECIPES:
            install(recipe, engine, ALL_CAPABILITIES)
        expected = len(engine.scheduler.list_rules()) + len(engine.triggers.list_triggers())
        await store.save(engine)

        fresh = AutomationEngine()

        assert await store.load(fresh) == expected
