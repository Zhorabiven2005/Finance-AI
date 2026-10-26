"""Вопросы о целях в POST /api/v1/assistant/chat.

Проверяется, что расчёт плана делает backend и передаёт модели готовые
числа, а не просит её считать. Синтетические данные, in-memory БД
(tests/conftest.py) и фейковый сервер Ollama.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from app import clock
from app.api.v1.assistant import get_ollama_client
from app.assistant.goal_planner import ASK_TERM_OR_CONTRIBUTION
from app.assistant.ollama import OllamaClient
from app.main import app
from tests.assistant_fakes import StreamRoute, chat_chunks, fake_ollama, healthy_routes

TODAY = date(2026, 10, 25)
URL = "/api/v1/assistant/chat"
REAL_QUESTION = "Сколько мне нужно времени и по сколько нужно отложить, чтобы накопить на мою цель?"
CLARIFY = "За какой срок вы хотите накопить или какую сумму готовы откладывать в месяц?"


@pytest.fixture(autouse=True)
def fixed_dates(monkeypatch):
    monkeypatch.setattr(clock, "today", lambda: TODAY)
    monkeypatch.setattr(clock, "utc_today", lambda: TODAY)


def ask(client, question, history=None, answer="Ок."):
    """(события ответа, системный промпт, ушедший в модель)."""
    routes = healthy_routes()
    routes["/api/chat"] = StreamRoute(chat_chunks(answer))
    with fake_ollama(routes) as srv:
        app.dependency_overrides[get_ollama_client] = lambda: OllamaClient(srv.url, 2.0)
        messages = [*(history or []), {"role": "user", "content": question}]
        with client.stream("POST", URL, json={"messages": messages}) as r:
            assert r.status_code == 200, r.read()
            events = [json.loads(line) for line in r.iter_lines() if line.strip()]
        (body,) = srv.chat_bodies()
    return events, body["messages"][0]["content"]


def add_goal(c, name="Машина", target=20_000_000, currency="RUB", target_date=None, saved=0):
    g = c.post("/api/v1/goals", json={"name": name, "target_amount_minor": target, "currency": currency, "target_date": target_date})
    assert g.status_code == 201, g.text
    if saved:
        e = c.post(f"/api/v1/goals/{g.json()['id']}/entries", json={"type": "contribution", "amount_minor": saved, "occurred_at": "2026-10-01T09:00:00Z"})
        assert e.status_code == 201, e.text
    return g.json()


def calc_of(events):
    assert events[0]["type"] == "meta"
    return events[0]["goal_calculation"]


class TestGoalQuestions:
    def test_real_question_goal_without_date(self, seeded_client):
        """Как в реальных данных: цель 200 000 ₽ без срока и без накоплений."""
        add_goal(seeded_client)
        events, system = ask(seeded_client, REAL_QUESTION)
        calc = calc_of(events)
        assert calc["kind"] == "needs_input" and calc["goal"]["remaining"] == 20_000_000
        assert "## Расчёт по цели" in system and ASK_TERM_OR_CONTRIBUTION in system
        assert "план взносов не рассчитан" not in system
        assert "срок цели не задан: ежемесячный взнос зависит от срока" in system  # раздел «Цели» сводки
        assert events[-1]["type"] == "done"

    def test_follow_up_with_term_is_calculated_by_backend(self, seeded_client):
        add_goal(seeded_client, target=12_000_000, saved=1_200_000)  # осталось 108 000 ₽
        history = [{"role": "user", "content": REAL_QUESTION}, {"role": "assistant", "content": CLARIFY}]
        answer = "Чтобы накопить за 6 месяцев, откладывайте 18 000,00 ₽ в месяц."
        events, system = ask(seeded_client, "За 6 месяцев", history=history, answer=answer)
        calc = calc_of(events)
        assert calc["kind"] == "required_contribution" and calc["periods"] == 6
        assert calc["required"] == {"minor": 1_800_000, "currency": "RUB"}
        assert "18 000,00 ₽ в месяц" in system
        # Все числа ответа модели сверены с расчётом приложения и вопросом.
        assert events[-1]["grounding"] == {"checked": 2, "unverified": []}

    def test_wrong_number_from_model_is_flagged(self, seeded_client):
        add_goal(seeded_client, target=12_000_000, saved=1_200_000)
        events, _ = ask(seeded_client, "Сколько откладывать на цель за 6 месяцев?", answer="Нужно 20 000 ₽ в месяц.")
        assert events[-1]["grounding"]["unverified"] == ["20 000"]

    def test_contribution_gives_time(self, seeded_client):
        add_goal(seeded_client)
        events, system = ask(seeded_client, "Если откладывать по 15 000 в месяц, когда накоплю на цель?")
        calc = calc_of(events)
        assert calc["kind"] == "time_to_goal" and calc["periods_needed"] == 14
        assert calc["contribution_last"] == {"minor": 500_000, "currency": "RUB"}
        assert "понадобится 14 взносов" in system

    def test_goal_with_date(self, seeded_client):
        add_goal(seeded_client, target=18_000_000, target_date="2027-04-01")
        events, system = ask(seeded_client, "Какой ежемесячный взнос нужен, чтобы успеть к сроку цели?")
        calc = calc_of(events)
        assert calc["kind"] == "required_contribution" and calc["term_source"] == "goal"
        assert calc["required"]["minor"] == 3_000_000 and calc["periods"] == 6
        assert "30 000,00 ₽ в месяц" in system

    def test_completed_goal(self, seeded_client):
        add_goal(seeded_client, target=100_000, saved=100_000)
        events, system = ask(seeded_client, "Сколько осталось накопить до цели?")
        assert calc_of(events)["kind"] == "completed"
        assert "Цель уже достигнута" in system

    def test_currency_is_not_converted(self, seeded_client):
        add_goal(seeded_client, currency="USD", target=500_000)
        events, system = ask(seeded_client, "Если откладывать по 20 000 ₽ в месяц, когда накоплю на цель?")
        calc = calc_of(events)
        assert calc["kind"] == "currency_mismatch" and calc["contribution"] is None
        assert calc["periods_needed"] is None

    def test_zero_contribution(self, seeded_client):
        add_goal(seeded_client)
        events, _ = ask(seeded_client, "Если откладывать по 0 в месяц, когда накоплю на цель?")
        calc = calc_of(events)
        assert calc["kind"] == "contribution_not_positive" and calc["periods_needed"] is None and calc["finish_date"] is None

    def test_several_goals_and_name(self, seeded_client):
        add_goal(seeded_client, "Машина")
        add_goal(seeded_client, "Отпуск", target=30_000_000)
        events, system = ask(seeded_client, "Сколько откладывать на цель за год?")
        assert calc_of(events)["kind"] == "choose_goal" and "Для какой цели посчитать" in system
        events, _ = ask(seeded_client, "Сколько откладывать на отпуск за год?")
        calc = calc_of(events)
        assert calc["goal"]["label"] == "Отпуск" and calc["required"]["minor"] == 2_500_000

    def test_archived_goal_is_not_planned(self, seeded_client):
        g = add_goal(seeded_client)
        seeded_client.patch(f"/api/v1/goals/{g['id']}", json={"is_archived": True})
        events, _ = ask(seeded_client, "Сколько откладывать на цель за год?")
        assert calc_of(events)["kind"] == "no_goals"

    def test_no_goals(self, seeded_client):
        events, system = ask(seeded_client, REAL_QUESTION)
        assert calc_of(events)["kind"] == "no_goals" and "Целей в приложении нет" in system

    def test_unrelated_question_has_no_goal_section(self, seeded_client):
        add_goal(seeded_client)
        events, system = ask(seeded_client, "Что с бюджетами в этом месяце?")
        assert calc_of(events) is None and "## Расчёт по цели" not in system

    def test_rules_require_using_backend_calculation(self, seeded_client):
        add_goal(seeded_client)
        _, system = ask(seeded_client, REAL_QUESTION)
        assert "Расчёт по цели" in system.split("<<<ДАННЫЕ")[0]  # правило 10 — в правилах, до данных
        assert "прошлый доход не гарантирует будущий" in system

    def test_goal_question_does_not_write_to_db(self, seeded_client, db_session):
        add_goal(seeded_client, target=12_000_000, saved=1_200_000)
        before = seeded_client.get("/api/v1/goals").json()
        ask(seeded_client, "Сколько откладывать на цель за 6 месяцев?")
        assert seeded_client.get("/api/v1/goals").json() == before
        assert len(seeded_client.get(f"/api/v1/goals/{before[0]['id']}/entries").json()) == 1
