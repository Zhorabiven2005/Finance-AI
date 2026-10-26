"""План накоплений: формулы engine/goals.py и разбор вопроса goal_planner.

Чистые функции, без БД и без модели. Даты фиксированы.
"""

from __future__ import annotations

import re
from datetime import date

import pytest

from app.assistant import goal_planner as gp
from app.assistant.digest import money
from app.engine.goals import contribution_for_periods, last_contribution, periods_for_contribution
from app.engine.money import CurrencyMismatchError, Money
from app.schemas.assistant import DigestGoal
from app.schemas.money import MoneyOut

TODAY = date(2026, 10, 25)
RUB = lambda minor: Money.of(minor, "RUB")  # noqa: E731


def goal(name="Машина", target=20_000_000, saved=0, target_date=None, currency="RUB", status="active") -> DigestGoal:
    m = lambda v: money(MoneyOut(minor=v, currency=currency))  # noqa: E731
    return DigestGoal(
        label=name, status=status, currency=currency, target=m(target), saved=m(saved),
        remaining=m(max(0, target - saved)), progress_percent=0.0, target_date=target_date,
        months_left=None, required_monthly=None, plan_null_reason=None,
    )


def plan(question: str, goals=None, history=None):
    dialogue = [*(history or []), {"role": "user", "content": question}]
    return gp.plan_for_dialogue(dialogue, [goal()] if goals is None else goals, TODAY)


# --- формулы -----------------------------------------------------------------------


class TestFormulas:
    def test_example_from_spec(self):
        # Осталось 108 000 ₽, срок 6 месяцев → 18 000 ₽ в месяц ровно.
        per = contribution_for_periods(RUB(10_800_000), 6)
        assert per == RUB(1_800_000)
        assert last_contribution(RUB(10_800_000), per, 6) == RUB(1_800_000)

    def test_rounds_up_to_kopeck_and_last_payment_is_smaller(self):
        per = contribution_for_periods(RUB(20_000_000), 6)
        assert per == RUB(3_333_334)  # 33 333,34 ₽ — вверх, чтобы успеть
        last = last_contribution(RUB(20_000_000), per, 6)
        assert last == RUB(3_333_330)
        assert per * 5 + last == RUB(20_000_000)  # ровно цель, без лишней копейки

    def test_periods_for_contribution(self):
        assert periods_for_contribution(RUB(20_000_000), RUB(1_500_000)) == 14  # 13,33 → 14 взносов
        assert last_contribution(RUB(20_000_000), RUB(1_500_000), 14) == RUB(500_000)
        assert periods_for_contribution(RUB(10_800_000), RUB(1_800_000)) == 6

    @pytest.mark.parametrize("bad", [0, -100])
    def test_non_positive_contribution_has_no_term(self, bad):
        with pytest.raises(ValueError):
            periods_for_contribution(RUB(100_000), RUB(bad))

    def test_currencies_are_not_mixed(self):
        with pytest.raises(CurrencyMismatchError):
            periods_for_contribution(RUB(100_000), Money.of(100_000, "USD"))

    def test_nothing_left(self):
        assert contribution_for_periods(RUB(0), 6) == RUB(0)
        assert periods_for_contribution(RUB(0), RUB(100)) == 0

    def test_zero_periods_rejected(self):
        with pytest.raises(ValueError):
            contribution_for_periods(RUB(100), 0)

    def test_currency_without_minor_units(self):
        assert contribution_for_periods(Money.of(100_000, "JPY"), 3) == Money.of(33_334, "JPY")


# --- разбор вопроса --------------------------------------------------------------------


class TestParsing:
    @pytest.mark.parametrize(
        ("text", "target", "source"),
        [
            ("за 6 месяцев", date(2027, 4, 25), "months"),
            ("через три года", date(2029, 10, 25), "months"),
            ("за год", date(2027, 10, 25), "months"),
            ("за полгода", date(2027, 4, 25), "months"),
            ("за полтора года", date(2028, 4, 25), "months"),
            ("за 2 года и 3 месяца", date(2029, 1, 25), "months"),
            ("за 10 недель", date(2027, 1, 3), "weeks"),
            ("к 01.06.2027", date(2027, 6, 1), "date"),
            ("до 2027-03-15", date(2027, 3, 15), "date"),
            ("к марту 2027", date(2027, 3, 1), "date"),
            ("к марту", date(2027, 3, 1), "date"),
            ("до конца декабря", date(2026, 12, 31), "date"),
            ("к концу года", date(2026, 12, 31), "date"),
            ("к концу следующего года", date(2027, 12, 31), "date"),
        ],
    )
    def test_term(self, text, target, source):
        term = gp.parse_request(f"сколько откладывать на цель {text}?", TODAY).term
        assert term is not None and term.target_date == target and term.source == source

    @pytest.mark.parametrize(
        ("text", "amount", "currency", "period"),
        [
            ("по 20 000 в месяц", "20000", None, "month"),
            ("откладывать 15 тыс в месяц", "15000", None, "month"),
            ("по 5к в неделю", "5000", None, "week"),
            ("ежемесячно по 12 500,50 ₽", "12500.50", "RUB", "month"),
            ("по 500 $ в месяц", "500", "USD", "month"),
            ("по 0 в месяц", "0", None, "month"),
            ("по -1000 в месяц", "-1000", None, "month"),
        ],
    )
    def test_contribution(self, text, amount, currency, period):
        c = gp.parse_request(f"Если {text}, когда накоплю на цель?", TODAY).contribution
        assert c is not None and str(c.amount) == amount and c.currency == currency and c.period == period

    @pytest.mark.parametrize(
        "text",
        [
            "Сколько я потратил в 2026 году?",  # год — не взнос и не срок
            "чтобы накопить 300 000 на машину",  # сумма цели, а не взнос
            "Сколько мне нужно времени и по сколько нужно отложить?",
            "Какие расходы в месяц?",
        ],
    )
    def test_no_false_parameters(self, text):
        r = gp.parse_request(text, TODAY)
        assert r.contribution is None
        if "2026" in text or "в месяц" in text:
            assert r.term is None

    def test_term_numbers_are_not_taken_as_contribution(self):
        r = gp.parse_request("хочу накопить за 12 месяцев", TODAY)
        assert r.term is not None and r.contribution is None


# --- расчёт по диалогу -------------------------------------------------------------------


class TestPlan:
    def test_real_question_without_term_and_contribution_asks_one_question(self):
        calc = plan("Сколько мне нужно времени и по сколько нужно отложить, чтобы накопить на мою цель?")
        assert calc.kind == "needs_input"
        text = gp.render(calc, TODAY)
        assert "не рассчитан" not in text
        assert gp.ASK_TERM_OR_CONTRIBUTION in text
        # Никаких придуманных сроков и сумм: в тексте только суммы самой цели.
        amounts = set(re.findall(r"\d[\d  ]*,\d\d", text))
        assert amounts == {"200 000,00", "0,00"}

    def test_term_from_question(self):
        calc = plan("Хочу накопить на цель за 6 месяцев", goals=[goal(target=12_000_000, saved=1_200_000)])
        assert calc.kind == "required_contribution"
        assert calc.periods == 6 and calc.required == RUB(1_800_000) and calc.required_last == RUB(1_800_000)
        text = gp.render(calc, TODAY)
        assert "18 000,00 ₽ в месяц" in text and "108 000,00" in text and "Допущения" in text

    def test_follow_up_answer_to_clarifying_question(self):
        history = [
            {"role": "user", "content": "Сколько откладывать на мою цель?"},
            {"role": "assistant", "content": "За какой срок вы хотите накопить или какую сумму готовы откладывать в месяц?"},
        ]
        calc = plan("6 месяцев", history=history)
        assert calc.kind == "required_contribution" and calc.required == RUB(3_333_334)

    def test_contribution_gives_time(self):
        calc = plan("Если откладывать по 15 000 в месяц, когда накоплю на цель?")
        assert calc.kind == "time_to_goal"
        assert calc.periods_needed == 14 and calc.contribution_last == RUB(500_000)
        assert calc.finish_date == date(2027, 12, 25)

    def test_weekly_contribution(self):
        calc = plan("Если откладывать по 5к в неделю, когда накоплю на цель?")
        assert calc.kind == "time_to_goal" and calc.period == "week" and calc.periods_needed == 40
        assert "в неделю" in gp.render(calc, TODAY)

    def test_feasibility_not_enough(self):
        calc = plan("Реально ли накопить на цель за год, если откладывать по 10000 в месяц?")
        assert calc.kind == "feasibility" and calc.feasible is False
        assert calc.required == RUB(1_666_667) and calc.shortfall == RUB(8_000_000)
        assert calc.accumulated_by_term == RUB(12_000_000)

    def test_feasibility_enough(self):
        calc = plan("Успею накопить на цель за год, если откладывать по 20 000 в месяц?")
        assert calc.kind == "feasibility" and calc.feasible is True and calc.shortfall == RUB(0)
        assert calc.periods_needed == 10

    def test_goal_date_is_used_when_question_has_no_term(self):
        calc = plan("Какой ежемесячный взнос нужен для цели?", goals=[goal(target_date=date(2027, 4, 1))])
        assert calc.kind == "required_contribution" and calc.term_from_goal is True
        assert calc.periods == 6 and calc.required == RUB(3_333_334)

    def test_question_term_overrides_goal_date(self):
        calc = plan("А если накопить на цель за год?", goals=[goal(target_date=date(2027, 4, 1))])
        assert calc.term_from_goal is False and calc.periods == 12

    def test_goal_date_with_contribution_checks_feasibility(self):
        calc = plan("Хватит ли по 40 000 в месяц на цель?", goals=[goal(target_date=date(2027, 4, 1))])
        assert calc.kind == "feasibility" and calc.feasible is True

    def test_completed_goal(self):
        calc = plan("Сколько осталось накопить до цели?", goals=[goal(target=100_000, saved=150_000, status="completed")])
        assert calc.kind == "completed"
        assert "уже достигнута" in gp.render(calc, TODAY)

    @pytest.mark.parametrize("q", ["Если откладывать по 0 в месяц на цель?", "Если откладывать по -500 в месяц на цель?"])
    def test_non_positive_contribution_no_term(self, q):
        calc = plan(q)
        assert calc.kind == "contribution_not_positive" and calc.periods_needed is None and calc.finish_date is None
        assert "срок накопления не определён" in gp.render(calc, TODAY)

    def test_non_positive_contribution_with_term_still_gives_required(self):
        calc = plan("Если откладывать по 0 в месяц, накоплю на цель за год?")
        assert calc.kind == "contribution_not_positive" and calc.periods_needed is None
        assert calc.required == RUB(1_666_667)

    def test_other_currency_is_not_converted(self):
        calc = plan("Если откладывать по 500 $ в месяц, когда накоплю на цель?")
        assert calc.kind == "currency_mismatch" and calc.contribution is None
        assert "Курсов валют в приложении нет" in gp.render(calc, TODAY)

    def test_passed_date(self):
        calc = plan("Сколько откладывать на цель до 01.01.2026?")
        assert calc.kind == "date_passed" and calc.required is None

    def test_goal_own_passed_date(self):
        calc = plan("Сколько откладывать на цель?", goals=[goal(target_date=date(2026, 1, 1))])
        assert calc.kind == "date_passed"

    def test_too_long(self):
        calc = plan("Если откладывать по 1 рублю в месяц, когда накоплю на цель?")
        assert calc.kind == "too_long" and calc.finish_date is None

    def test_no_goals(self):
        assert plan("Сколько откладывать на цель?", goals=[]).kind == "no_goals"

    def test_several_goals_need_choice(self):
        goals = [goal("Машина"), goal("Отпуск", target=30_000_000)]
        calc = plan("Сколько откладывать на цель за год?", goals=goals)
        assert calc.kind == "choose_goal" and calc.candidates == ("Машина", "Отпуск")
        assert "Для какой цели посчитать" in gp.render(calc, TODAY)

    def test_goal_by_name_in_any_form(self):
        goals = [goal("Машина"), goal("Отпуск", target=30_000_000)]
        calc = plan("Сколько откладывать на отпуск за год?", goals=goals)
        assert calc.kind == "required_contribution" and calc.goal.label == "Отпуск"
        assert calc.required == RUB(2_500_000)

    def test_not_a_goal_question(self):
        assert plan("Что с бюджетами в этом месяце?") is None
        assert plan("Сколько я потратил в 2026 году?") is None

    def test_structured_result_in_minor_units(self):
        d = plan("Хочу накопить на цель за 6 месяцев", goals=[goal(target=12_000_000, saved=1_200_000)]).as_dict()
        assert d["kind"] == "required_contribution"
        assert d["required"] == {"minor": 1_800_000, "currency": "RUB"}
        assert d["goal"]["remaining"] == 10_800_000 and d["periods"] == 6 and d["term_source"] == "months"
