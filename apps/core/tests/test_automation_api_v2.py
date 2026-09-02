"""Watcher / Goal / Recipe API testlari (Z39-Z40).

`test_automation_api.py` — jadval/trigger/workflow endpointlari (Bo'lim 9).
Bu fayl — yangi zip qo'shgan uchta sirt: kuzatuv, maqsad, retsept.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from starlette.testclient import TestClient

from zet.agents.registry import AgentRegistry
from zet.api.app import create_app
from zet.api.deps import get_automation_engine, get_goal_registry
from zet.automation.autonomy import AutonomyLevel
from zet.automation.builtin_metrics import (
    AGENTS_ACTIVE,
    AUTOMATION_EVENTS,
    register_builtin_metrics,
)
from zet.automation.engine import AutomationEngine
from zet.automation.goal import GoalRegistry
from zet.domain.agent import AgentSpec
from zet.domain.enums import AgentStatus


@pytest.fixture()
def client() -> Iterator[TestClient]:
    """Toza engine va goal registry bilan ilova.

    `TestClient` ATAYLAB `with` blokisiz — repo'dagi boshqa API testlari
    kabi. `with` lifespan'ni ishga tushiradi: kunlik daemon, automation
    daemon va Telegram long-polling. Ular fon task'lari sifatida qolib,
    keyingi testlarga aralashadi (to'liq to'plamda fixture xatosi shundan
    chiqqan edi). Bu testlar route'larni sinaydi, ishga tushish tsiklini
    emas — u `test_main_entrypoint.py`da.
    """
    get_automation_engine.cache_clear()
    get_goal_registry.cache_clear()

    engine = AutomationEngine()
    agents = AgentRegistry()
    agents.register(
        AgentSpec(name="worker", description="Ishchi", system_prompt="Sen ishchisan."),
        status=AgentStatus.ACTIVE,
    )
    register_builtin_metrics(engine, agents)

    app = create_app()
    app.dependency_overrides[get_automation_engine] = lambda: engine
    yield TestClient(app)

    app.dependency_overrides.clear()
    get_automation_engine.cache_clear()
    get_goal_registry.cache_clear()


class TestMetricsEndpoint:
    """Kuzatish mumkin bo'lgan metrikalar."""

    def test_builtin_metrics_are_listed(self, client: TestClient) -> None:
        response = client.get("/api/v1/automation/metrics")
        assert response.status_code == 200
        assert AGENTS_ACTIVE in response.json()


class TestWatcherEndpoints:
    """Kuzatuv qoidalari (3-xususiyat)."""

    def test_create_watcher(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/automation/watchers",
            json={
                "name": "Agent xatolari oshdi",
                "metric": AGENTS_ACTIVE,
                "comparison": "crosses_above",
                "threshold": 5,
            },
        )
        assert response.status_code == 201
        assert response.json()["metric"] == AGENTS_ACTIVE

    def test_unknown_metric_is_refused(self, client: TestClient) -> None:
        """Jimgina hech qachon ishlamaydigan qoida yaratilmaydi."""
        response = client.post(
            "/api/v1/automation/watchers",
            json={"name": "Yo'q metrika", "metric": "mavjud.emas"},
        )
        assert response.status_code == 422
        assert "mavjud.emas" in response.json()["detail"]

    def test_list_and_delete(self, client: TestClient) -> None:
        created = client.post(
            "/api/v1/automation/watchers",
            json={"name": "Test", "metric": AGENTS_ACTIVE},
        ).json()

        assert len(client.get("/api/v1/automation/watchers").json()) == 1

        assert client.delete(f"/api/v1/automation/watchers/{created['id']}").status_code == 204
        assert client.get("/api/v1/automation/watchers").json() == []

    def test_delete_missing_is_404(self, client: TestClient) -> None:
        assert client.delete("/api/v1/automation/watchers/yoq").status_code == 404

    def test_first_poll_only_sets_baseline(self, client: TestClient) -> None:
        """Birinchi o'lchov signal bermaydi — soxta signalning oldini oladi."""
        client.post(
            "/api/v1/automation/watchers",
            json={"name": "Test", "metric": AGENTS_ACTIVE, "comparison": "changed"},
        )

        response = client.post("/api/v1/automation/watchers/poll")

        assert response.status_code == 200
        assert response.json()["fired"] == []

    def test_second_poll_reports_the_fired_rule(self, client: TestClient) -> None:
        """Metrika o'zgargach qoida signal beradi — TRIGGER bo'lmasa ham.

        Bu ajratish muhim: `fired` (signal bergan qoidalar) va `actions`
        (uyg'ongan agentlar) bir xil son emas. Ilgari javob faqat
        `len(actions)` ni qaytarardi va triggersiz qoida "0" ko'rinib,
        kuzatuv ishlamayaptidek taassurot berardi.
        """
        client.post(
            "/api/v1/automation/watchers",
            json={
                "name": "Hodisalar o'zgardi",
                "metric": AUTOMATION_EVENTS,
                "comparison": "changed",
                "cooldown_s": 0,
            },
        )
        client.post("/api/v1/automation/watchers/poll")  # baza

        # Metrikani siljitamiz — hodisa yuborish `event_count`ni oshiradi.
        client.post("/api/v1/automation/events", json={"event_type": "test.ping"})

        body = client.post("/api/v1/automation/watchers/poll").json()

        assert len(body["fired"]) == 1
        assert body["fired"][0]["metric"] == AUTOMATION_EVENTS
        assert body["fired"][0]["direction"] == "up"
        assert body["actions"] == []  # ulangan trigger yo'q

    def test_watchers_appear_in_stats(self, client: TestClient) -> None:
        client.post(
            "/api/v1/automation/watchers",
            json={"name": "Test", "metric": AGENTS_ACTIVE},
        )
        stats = client.get("/api/v1/automation/stats").json()
        assert stats["watchers"]["total"] == 1


class TestGoalEndpoints:
    """Maqsadlar (5-xususiyat)."""

    def _create(self, client: TestClient, **overrides: object) -> dict[str, object]:
        body: dict[str, object] = {
            "name": "Hisobot",
            "outcome": "Haftalik hisobot tayyor bo'lsin",
            "agent_name": "worker",
        }
        body.update(overrides)
        response = client.post("/api/v1/automation/goals", json=body)
        assert response.status_code == 201
        return dict(response.json())

    def test_create_goal(self, client: TestClient) -> None:
        goal = self._create(client)
        assert goal["status"] == "pending"
        assert goal["autonomy_level"] == AutonomyLevel.L3_AGENT.value

    def test_get_goal(self, client: TestClient) -> None:
        goal = self._create(client)
        response = client.get(f"/api/v1/automation/goals/{goal['id']}")
        assert response.status_code == 200

    def test_get_missing_goal_is_404(self, client: TestClient) -> None:
        assert client.get("/api/v1/automation/goals/yoq").status_code == 404

    def test_list_goals(self, client: TestClient) -> None:
        self._create(client)
        self._create(client, name="Ikkinchi")
        assert len(client.get("/api/v1/automation/goals").json()) == 2

    def test_low_autonomy_cannot_pursue(self, client: TestClient) -> None:
        """L2 maqsad tsikliga ruxsat bermaydi — 409, sababi bilan."""
        goal = self._create(client, autonomy_level=AutonomyLevel.L2_PIPELINE.value)

        response = client.post(f"/api/v1/automation/goals/{goal['id']}/pursue")

        assert response.status_code == 409
        assert "self_planning" in response.json()["detail"]

    def test_pursue_missing_goal_is_404(self, client: TestClient) -> None:
        assert client.post("/api/v1/automation/goals/yoq/pursue").status_code == 404


class TestRecipeEndpoints:
    """TIZIM retseptlari — halol holat."""

    def test_all_six_listed(self, client: TestClient) -> None:
        recipes = client.get("/api/v1/automation/recipes").json()
        assert len(recipes) == 6
        assert [r["code"] for r in recipes] == ["T01", "T02", "T03", "T04", "T05", "T06"]

    def test_blocked_recipe_names_what_is_missing(self, client: TestClient) -> None:
        """Ega aynan nima yetishmayotganini ko'radi.

        T01 "Uchrashuv kotibi" — kalendar Z48'da ochildi, lekin uchrashuv
        HAVOLASINI yaratish (Zoom/Meet) hali yo'q, shuning uchun retsept
        baribir bloklangan va sababi aynan shu."""
        recipe = client.get("/api/v1/automation/recipes/T01").json()
        assert recipe["status"] == "missing_capability"
        assert "meeting_link" in recipe["missing"]
        assert recipe["blocked_steps"]

    def test_unknown_code_is_404(self, client: TestClient) -> None:
        assert client.get("/api/v1/automation/recipes/T99").status_code == 404

    def test_daily_pulse_is_ready_and_installs(self, client: TestClient) -> None:
        """T06 "Kunlik puls" — Z48 doskani ochgach HAQIQATAN o'rnatiladi.

        Ilgari `task_board` yo'q edi va bu retsept 409 qaytarardi: jadval
        bor edi, lekin agent unga yeta olmasdi."""
        recipe = client.get("/api/v1/automation/recipes/T06").json()
        assert recipe["status"] == "ready", recipe["missing"]

        response = client.post("/api/v1/automation/recipes/T06/install")

        assert response.status_code in {200, 201}
        rules = client.get("/api/v1/automation/schedules").json()
        assert any("T06" in rule["name"] for rule in rules)

    def test_install_refuses_incomplete_recipe(self, client: TestClient) -> None:
        """Chala avtomatlashtirish o'rnatilmaydi."""
        response = client.post("/api/v1/automation/recipes/T01/install")

        assert response.status_code == 409
        assert "meeting_link" in response.json()["detail"]
        assert client.get("/api/v1/automation/triggers").json() == []


class TestGoalRegistrySingleton:
    """Registry dependency haqiqatan singleton."""

    def test_same_instance_across_calls(self) -> None:
        get_goal_registry.cache_clear()
        first = get_goal_registry()
        assert isinstance(first, GoalRegistry)
        assert get_goal_registry() is first
        get_goal_registry.cache_clear()
