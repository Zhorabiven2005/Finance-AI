"""План накоплений по вопросу пользователя.

Вопросы вида «сколько откладывать, чтобы накопить за 6 месяцев», «за сколько
накоплю по 20 000 в месяц», «успею ли к марту» требуют расчёта, которого нет в
сводке: срок или взнос называет сам пользователь. Модель такие расчёты не
выполняет — их делает этот модуль, детерминированно:

  1. из последней реплики пользователя извлекаются параметры: срок (число
     месяцев/лет/недель или дата) и размер регулярного взноса;
  2. выбирается цель (по названию в вопросе, а если цель одна — она);
  3. engine/goals.py считает взнос, число взносов и последний взнос в целых
     минорных единицах валюты цели;
  4. результат (GoalCalculation) превращается в раздел блока ДАННЫЕ — модель
     только пересказывает готовые числа.

Чего модуль не делает: не придумывает срок или взнос, если пользователь их не
назвал (вместо этого — один уточняющий вопрос); не переводит валюты (взнос в
другой валюте не считается); не опирается на прошлые доходы как на будущие;
не обращается к БД — вход только сводка Stage 3A и текст диалога.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from app.assistant.digest import GOAL_STATUS_TEXT, label
from app.context.indicators import months_left
from app.engine.goals import contribution_for_periods, last_contribution, periods_for_contribution
from app.engine.money import Money
from app.engine.recurring import _add_months
from app.schemas.assistant import DigestGoal

Period = Literal["month", "week"]
CalculationKind = Literal[
    "no_goals",
    "choose_goal",
    "completed",
    "needs_input",
    "required_contribution",
    "time_to_goal",
    "feasibility",
    "date_passed",
    "contribution_not_positive",
    "currency_mismatch",
    "too_long",
]

# Дальше ста лет план не считается: такой «срок» — не план, а сигнал, что
# взнос слишком мал.
MAX_PERIODS: dict[Period, int] = {"month": 1200, "week": 5200}
PERIOD_TEXT: dict[Period, tuple[str, str]] = {"month": ("в месяц", "мес."), "week": ("в неделю", "нед.")}
MONTHS_GENITIVE = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]

ASSUMPTIONS = (
    "Допущения расчёта: равные регулярные взносы, без процентов, инфляции и снятий с цели; остатки на счетах "
    "в цель не входят. Будущий доход не гарантирован — средний доход прошлых месяцев не обещание."
)
ASK_TERM_OR_CONTRIBUTION = (
    "За какой срок вы хотите накопить (число месяцев или дата) или какую сумму готовы откладывать в месяц? "
    "Я посчитаю план."
)

# --- разбор вопроса ---------------------------------------------------------------

_SP = "[   ]"
_NUM_WORDS = {
    "один": 1, "одного": 1, "одну": 1, "два": 2, "две": 2, "двух": 2, "три": 3, "трёх": 3, "трех": 3,
    "четыре": 4, "четырёх": 4, "четырех": 4, "пять": 5, "пяти": 5, "шесть": 6, "шести": 6, "семь": 7, "семи": 7,
    "восемь": 8, "восьми": 8, "девять": 9, "девяти": 9, "десять": 10, "десяти": 10, "одиннадцать": 11,
    "одиннадцати": 11, "двенадцать": 12, "двенадцати": 12, "пятнадцать": 15, "восемнадцать": 18,
    "двадцать": 20, "тридцать": 30,
}
_NUM_WORD_RE = "|".join(sorted(_NUM_WORDS, key=len, reverse=True))
_TERM = re.compile(
    rf"(?:\b(?P<prep>за|через|на|в{_SP}+течени[еи])\s+)?"
    rf"(?:(?<![\d.,])(?P<n>\d{{1,3}})(?:-?(?:ти|х|ми|и))?|\b(?P<w>{_NUM_WORD_RE}))?\s*"
    r"(?<![а-яёa-z])(?P<unit>месяц\w*|мес\b\.?|год\w*|лет\b|недел\w*)",
    re.IGNORECASE,
)
_HALF_YEAR = re.compile(r"\b(?:(?:за|через|на)\s+)?(?P<w>полгода|полтора\s+года)\b", re.IGNORECASE)
_DATE_NUM = re.compile(r"\b(?:(?:к|до|по)\s+)?(?P<d>\d{1,2})[./](?P<m>\d{1,2})[./](?P<y>\d{4}|\d{2})\b")
_DATE_ISO = re.compile(r"\b(?:(?:к|до|по)\s+)?(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})\b")
_MONTH_STEMS = ["январ", "феврал", "март", "апрел", "ма", "июн", "июл", "август", "сентябр", "октябр", "ноябр", "декабр"]
_DATE_MONTH = re.compile(
    r"\b(?:к|до)\s+(?P<end>(?:концу|конца)\s+)?"
    r"(?P<m>январ[юяь]|феврал[юяь]|март[ау]?|апрел[юяь]|ма[юяй]|июн[юяь]|июл[юяь]|август[ау]?|сентябр[юяь]|"
    r"октябр[юяь]|ноябр[юяь]|декабр[юяь])\b(?:\s+(?P<y>\d{4}))?",
    re.IGNORECASE,
)
_DATE_YEAR_END = re.compile(
    r"\b(?:к|до)\s+(?:(?:концу|конца)\s+(?P<which>этого|следующего)?\s*года|новому\s+году|нового\s+года)\b",
    re.IGNORECASE,
)
_AMOUNT = re.compile(
    rf"(?P<sign>[-−–]\s*)?(?<![\d.,])(?P<int>\d{{1,3}}(?:{_SP}\d{{3}})+|\d+)(?:[.,](?P<frac>\d{{1,2}}))?"
    rf"(?:(?P<k>[кk])(?![а-яёa-z])|\s*(?P<mult>тыс\w*\.?|т\.\s?р\.?|млн\.?|миллион\w*))?"
    r"\s*(?P<cur>₽|руб\w*\.?|р\.|\$|usd|долл\w*|€|eur|евро|₸|тенге|kzt|¥|jpy|иен\w*)?",
    re.IGNORECASE,
)
_CURRENCY_MARKS = [
    (re.compile(r"₽|руб|р\.", re.I), "RUB"),
    (re.compile(r"\$|usd|долл", re.I), "USD"),
    (re.compile(r"€|eur|евро", re.I), "EUR"),
    (re.compile(r"₸|тенге|kzt", re.I), "KZT"),
    (re.compile(r"¥|jpy|иен", re.I), "JPY"),
]
_WEEK_AFTER = re.compile(r"\s*(?:(?:в|на|за)\s+недел\w*|/\s*нед\w*|еженедельно)", re.IGNORECASE)
_MONTH_AFTER = re.compile(r"\s*(?:(?:в|на)\s+(?:месяц|мес\b)|/\s*мес\w*|ежемесячно)", re.IGNORECASE)
_CONTRIB_BEFORE = re.compile(
    # «накопить 300 000» — это сумма цели, а не взнос, поэтому \bкопить.
    r"(?:\bпо(?=\s)|ежемесячн\w*|еженедельн\w*|\bв\s+(?:месяц|неделю)|\bотклад\w*|\bотлож\w*|\bвзнос\w*|\bвносить|"
    r"\bвношу|\bкопить|\bкоплю|\bкласть|\bкладу)\s*(?:по\s*)?(?:\S+\s+){0,2}$",
    re.IGNORECASE,
)
_GOAL_WORDS = re.compile(
    r"\bцел(?:ь|и|ей|ям|ью|ями|ях)\b|накоп\w*|копить|коплю|\bотклад\w*|\bотлож\w*|\bвзнос\w*|сбереч\w*",
    re.IGNORECASE,
)
# Слова, которые есть в названиях многих целей и не помогают их различать.
_GENERIC_STEMS = ("цел", "накоп", "сбереж", "копил", "мечт")


@dataclass(frozen=True)
class Term:
    target_date: date
    source: Literal["months", "weeks", "date"]
    text: str  # как сказал пользователь


@dataclass(frozen=True)
class Contribution:
    amount: Decimal  # в мажорных единицах, как в вопросе; знак сохранён
    currency: str | None  # None — валюта не указана, считается валютой цели
    period: Period
    text: str


@dataclass(frozen=True)
class GoalRequest:
    term: Term | None
    contribution: Contribution | None

    @property
    def has_parameters(self) -> bool:
        return self.term is not None or self.contribution is not None


def _number(n: str | None, w: str | None) -> int | None:
    if n:
        return int(n)
    if w:
        return _NUM_WORDS[w.lower()]
    return None


def _mask(text: str, span: tuple[int, int]) -> str:
    return text[: span[0]] + " " * (span[1] - span[0]) + text[span[1] :]


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _month_end(year: int, month: int) -> date:
    return _add_months(date(year, month, 1), 1) - timedelta(days=1)


def _parse_term(text: str, today: date) -> tuple[Term | None, str]:
    """Срок из текста и текст с вырезанным сроком (чтобы его числа не
    приняли за сумму взноса)."""
    for regex in (_DATE_NUM, _DATE_ISO):
        m = regex.search(text)
        if m:
            year = int(m["y"])
            year = year + 2000 if year < 100 else year
            d = _safe_date(year, int(m["m"]), int(m["d"]))
            text = _mask(text, m.span())
            if d is not None:
                return Term(d, "date", m.group(0).strip()), text
    m = _DATE_YEAR_END.search(text)
    if m:
        year = today.year + (1 if (m["which"] or "").lower() == "следующего" else 0)
        return Term(date(year, 12, 31), "date", m.group(0).strip()), _mask(text, m.span())
    m = _DATE_MONTH.search(text)
    if m:
        word = m["m"].lower()
        month = next(i for i, stem in enumerate(_MONTH_STEMS, 1) if word.startswith(stem) and not (stem == "ма" and word.startswith("мар")))
        end = bool(m["end"])
        if m["y"]:
            year = int(m["y"])
        else:
            year = today.year if (month > today.month or (month == today.month and end)) else today.year + 1
        target = _month_end(year, month) if end else date(year, month, 1)
        return Term(target, "date", m.group(0).strip()), _mask(text, m.span())

    m = _HALF_YEAR.search(text)
    if m:
        months = 6 if m["w"].lower() == "полгода" else 18
        return Term(_add_months(today, months), "months", m.group(0).strip()), _mask(text, m.span())
    parts: list[tuple[int, str, re.Match[str]]] = []
    for m in _TERM.finditer(text):
        count = _number(m["n"], m["w"])
        unit = m["unit"].lower()
        if count is None:
            # «за год», «через год» — без числа только год и только с предлогом:
            # «в месяц» — это периодичность взноса, а не срок.
            if not (m["prep"] and unit.startswith("год")):
                continue
            count = 1
        if count <= 0:
            continue
        parts.append((count, unit, m))
    if not parts:
        return None, text
    # «2 года и 3 месяца» — одна длительность; несколько разных сроков через
    # «или» не складываются: берётся первый.
    chosen = [parts[0]]
    for prev, cur in zip(parts, parts[1:]):
        if not re.fullmatch(r"\s*(?:и|,)?\s*", text[prev[2].end() : cur[2].start()]):
            break
        chosen.append(cur)
    weeks = sum(c for c, u, _ in chosen if u.startswith("недел"))
    months = sum(c * (12 if u.startswith(("год", "лет")) else 1) for c, u, _ in chosen if not u.startswith("недел"))
    phrase = text[chosen[0][2].start() : chosen[-1][2].end()].strip()
    for *_, m in chosen:
        text = _mask(text, m.span())
    if weeks and not months:
        return Term(today + timedelta(weeks=weeks), "weeks", phrase), text
    target = _add_months(today, months) + timedelta(weeks=weeks)
    return Term(target, "months", phrase), text


def _parse_contribution(text: str) -> Contribution | None:
    for m in _AMOUNT.finditer(text):
        after = text[m.end() : m.end() + 30]
        before = text[max(0, m.start() - 40) : m.start()]
        weekly = _WEEK_AFTER.match(after)
        monthly = _MONTH_AFTER.match(after)
        if not (weekly or monthly or _CONTRIB_BEFORE.search(before)):
            continue
        digits = re.sub(_SP, "", m["int"])
        value = Decimal(f"{digits}.{m['frac']}" if m["frac"] else digits)
        mult = (m["mult"] or "").lower()
        if m["k"] or mult.startswith(("тыс", "т.")):
            value *= 1000
        elif mult.startswith(("млн", "миллион")):
            value *= 1_000_000
        if m["sign"]:
            value = -value
        currency = None
        if m["cur"]:
            currency = next(code for regex, code in _CURRENCY_MARKS if regex.match(m["cur"]))
        before_week = re.search(r"(?:еженедельн\w*|\bв\s+неделю)\s*(?:по\s*)?(?:\S+\s+){0,2}$", before, re.IGNORECASE)
        period: Period = "week" if (weekly or before_week) else "month"
        marker = weekly or monthly
        phrase = m.group(0) + (marker.group(0) if marker else "")
        return Contribution(value, currency, period, phrase.strip())
    return None


def parse_request(text: str, today: date) -> GoalRequest:
    term, rest = _parse_term(text, today)
    return GoalRequest(term=term, contribution=_parse_contribution(rest))


# --- выбор цели ---------------------------------------------------------------------


def _stems(goal_label: str) -> list[str]:
    stems = []
    for word in re.findall(r"[a-zа-яё0-9]+", goal_label.casefold()):
        if len(word) < 3 or word.startswith(_GENERIC_STEMS):
            continue
        stems.append(word if len(word) <= 4 else word[: len(word) - 2])
    return stems


def _mentioned(goals: list[DigestGoal], text: str) -> list[DigestGoal]:
    text_cf = text.casefold()
    found = []
    for g in goals:
        full = g.label.casefold().strip()
        if (full and full in text_cf) or any(re.search(rf"\b{re.escape(s)}", text_cf) for s in _stems(g.label)):
            found.append(g)
    return found


def is_goal_question(dialogue: list[dict[str, str]], goals: list[DigestGoal], today: date) -> bool:
    """Нужен ли расчёт: вопрос о цели/накоплениях, упоминание цели по
    названию, или ответ на уточняющий вопрос о сроке/взносе (в последней
    реплике есть срок или взнос, а предыдущие реплики были о цели)."""
    last = dialogue[-1]["content"]
    if _GOAL_WORDS.search(last) or _mentioned(goals, last):
        return True
    if not parse_request(last, today).has_parameters:
        return False
    return any(_GOAL_WORDS.search(m["content"]) for m in dialogue[-3:-1])


# --- расчёт -------------------------------------------------------------------------


@dataclass(frozen=True)
class GoalCalculation:
    kind: CalculationKind
    goal: DigestGoal | None = None
    candidates: tuple[str, ...] = ()
    period: Period = "month"
    term: Term | None = None
    term_from_goal: bool = False
    periods: int | None = None  # взносов до срока
    required: Money | None = None  # нужный взнос за период
    required_last: Money | None = None
    contribution: Money | None = None  # взнос из вопроса
    contribution_text: str | None = None
    periods_needed: int | None = None  # взносов при заданном взносе
    contribution_last: Money | None = None
    finish_date: date | None = None  # ориентировочная дата последнего взноса
    feasible: bool | None = None
    accumulated_by_term: Money | None = None
    shortfall: Money | None = None

    def as_dict(self) -> dict:
        """Структурированный результат (минорные единицы) — для события meta."""
        money = lambda m: {"minor": m.minor, "currency": m.currency.code} if m is not None else None  # noqa: E731
        g = self.goal
        return {
            "kind": self.kind,
            "goal": None if g is None else {
                "label": g.label, "status": g.status, "target": g.target.minor, "saved": g.saved.minor,
                "remaining": g.remaining.minor, "currency": g.currency,
                "target_date": g.target_date.isoformat() if g.target_date else None,
            },
            "period": self.period,
            "target_date": self.term.target_date.isoformat() if self.term else None,
            "term_source": ("goal" if self.term_from_goal else self.term.source) if self.term else None,
            "periods": self.periods,
            "required": money(self.required),
            "required_last": money(self.required_last),
            "contribution": money(self.contribution),
            "periods_needed": self.periods_needed,
            "contribution_last": money(self.contribution_last),
            "finish_date": self.finish_date.isoformat() if self.finish_date else None,
            "feasible": self.feasible,
            "accumulated_by_term": money(self.accumulated_by_term),
            "shortfall": money(self.shortfall),
        }


def _periods_until(today: date, target: date, period: Period) -> int:
    if period == "month":
        return months_left(today, target)  # то же правило, что у плана цели в контексте
    return max(1, (target - today).days // 7)


def _finish_date(today: date, periods: int, period: Period) -> date:
    return _add_months(today, periods) if period == "month" else today + timedelta(weeks=periods)


def calculate(goal: DigestGoal, request: GoalRequest, today: date) -> GoalCalculation:
    if goal.status == "completed" or goal.remaining.minor <= 0:
        return GoalCalculation("completed", goal)
    remaining = Money.of(goal.remaining.minor, goal.currency)
    c = request.contribution
    period: Period = c.period if c else ("week" if request.term and request.term.source == "weeks" else "month")

    contribution: Money | None = None
    if c is not None:
        if c.currency is not None and c.currency != goal.currency:
            return GoalCalculation("currency_mismatch", goal, period=period, contribution_text=c.text)
        contribution = Money.from_major(c.amount, goal.currency)

    term, from_goal = request.term, False
    if term is None and goal.target_date is not None:
        term, from_goal = Term(goal.target_date, "date", goal.target_date.isoformat()), True
    if term is not None and term.target_date < today:
        return GoalCalculation("date_passed", goal, period=period, term=term, term_from_goal=from_goal)

    required = required_last = None
    periods = None
    if term is not None:
        periods = _periods_until(today, term.target_date, period)
        required = contribution_for_periods(remaining, periods)
        required_last = last_contribution(remaining, required, periods)

    if contribution is not None and contribution.minor <= 0:
        # При таком взносе цель не достигается никогда: срок накопления не
        # считается. Если срок назван — показывается только нужный взнос.
        return GoalCalculation(
            "contribution_not_positive", goal, period=period, term=term, term_from_goal=from_goal,
            periods=periods, required=required, required_last=required_last, contribution=contribution,
        )

    if contribution is None:
        if term is None:
            return GoalCalculation("needs_input", goal, period=period)
        return GoalCalculation(
            "required_contribution", goal, period=period, term=term, term_from_goal=from_goal,
            periods=periods, required=required, required_last=required_last,
        )

    needed = periods_for_contribution(remaining, contribution)
    if needed > MAX_PERIODS[period]:
        return GoalCalculation("too_long", goal, period=period, contribution=contribution, periods_needed=needed)
    common = dict(
        period=period, contribution=contribution, contribution_text=c.text if c else None, periods_needed=needed,
        contribution_last=last_contribution(remaining, contribution, needed),
        finish_date=_finish_date(today, needed, period),
    )
    if term is None:
        return GoalCalculation("time_to_goal", goal, **common)
    accumulated = contribution * periods
    shortfall = remaining - accumulated
    return GoalCalculation(
        "feasibility", goal, term=term, term_from_goal=from_goal, periods=periods, required=required,
        required_last=required_last, feasible=contribution >= required,
        accumulated_by_term=accumulated if accumulated < remaining else remaining,
        shortfall=shortfall if shortfall.is_positive else Money.zero(goal.currency), **common,
    )


def plan_for_dialogue(dialogue: list[dict[str, str]], goals: list[DigestGoal], today: date) -> GoalCalculation | None:
    """Расчёт для последней реплики или None, если вопрос не о целях."""
    if not is_goal_question(dialogue, goals, today):
        return None
    if not goals:
        return GoalCalculation("no_goals")
    request = parse_request(dialogue[-1]["content"], today)
    user_texts = [m["content"] for m in reversed(dialogue) if m["role"] == "user"][:3]
    chosen: list[DigestGoal] = []
    for text in user_texts:  # сначала последняя реплика, затем более ранние
        chosen = _mentioned(goals, text)
        if chosen:
            break
    if len(chosen) != 1:
        if len(goals) == 1 and not chosen:
            chosen = goals
        else:
            names = tuple(g.label for g in (chosen or goals))
            return GoalCalculation("choose_goal", candidates=names)
    return calculate(chosen[0], request, today)


# --- текст для модели ----------------------------------------------------------------


def _date_text(d: date) -> str:
    return f"{d.day} {MONTHS_GENITIVE[d.month - 1]} {d.year}"


def render(calc: GoalCalculation, today: date) -> str:
    """Раздел блока ДАННЫЕ. Все числа — уже посчитанные значения."""
    lines = ["## Расчёт по цели (посчитано приложением; используй эти числа как есть, не пересчитывай)"]
    if calc.kind == "no_goals":
        lines.append("- Целей в приложении нет. Предложи создать цель в разделе «Цели» — тогда приложение посчитает план.")
        return "\n".join(lines)
    if calc.kind == "choose_goal":
        options = ", ".join(label(n) for n in calc.candidates)
        lines.append(f"- Целей несколько: {options}. Из вопроса не ясно, о какой речь.")
        lines.append(f"- Задай пользователю ровно этот вопрос: «Для какой цели посчитать: {options}?»")
        return "\n".join(lines)

    g = calc.goal
    assert g is not None
    per, unit = PERIOD_TEXT[calc.period]
    goal_date = f"срок цели {_date_text(g.target_date)}" if g.target_date else "срок цели не задан"
    lines.append(
        f"- Цель {label(g.label)} ({GOAL_STATUS_TEXT[g.status]}): нужно {g.target.display}, накоплено {g.saved.display}, "
        f"осталось накопить {g.remaining.display}; {goal_date}."
    )
    term_text = ""
    if calc.term is not None:
        source = "срок цели" if calc.term_from_goal else f"срок из вопроса «{calc.term.text}»"
        term_text = f"{source}: до {_date_text(calc.term.target_date)}"

    if calc.kind == "completed":
        lines.append("- Цель уже достигнута: накоплено не меньше нужной суммы. Дополнительные взносы не нужны.")
        return "\n".join(lines)
    if calc.kind == "needs_input":
        lines.append(
            "- Срок и размер взноса не заданы ни в цели, ни в вопросе. Приложение не выбирает их за пользователя "
            "и не придумывает: план считается, когда пользователь назовёт срок или сумму взноса."
        )
        lines.append(
            "- Если пользователь спрашивает, сколько откладывать или сколько времени нужно, не называй своих сроков "
            f"и сумм, а задай ему ровно этот вопрос: «{ASK_TERM_OR_CONTRIBUTION}»"
        )
        return "\n".join(lines)
    if calc.kind == "date_passed":
        lines.append(f"- {term_text[0].upper()}{term_text[1:]} — эта дата уже прошла (сегодня {_date_text(today)}). План к прошедшей дате не считается.")
        lines.append("- Задай пользователю ровно этот вопрос: «К какой новой дате или за какой срок вы хотите накопить?»")
        return "\n".join(lines)
    if calc.kind == "currency_mismatch":
        lines.append(
            f"- Взнос «{calc.contribution_text}» указан не в валюте цели ({g.currency}). Курсов валют в приложении нет, "
            "поэтому такой взнос не пересчитывается."
        )
        lines.append(f"- Задай пользователю ровно этот вопрос: «Сколько вы готовы откладывать в {g.currency}?»")
        return "\n".join(lines)
    if calc.kind == "contribution_not_positive":
        lines.append(
            f"- Названный взнос {calc.contribution.format()} не больше нуля: при нём цель не будет достигнута, срок "
            "накопления не определён."
        )
        if calc.required is None:
            lines.append(f"- Задай пользователю ровно этот вопрос: «{ASK_TERM_OR_CONTRIBUTION}»")
            return "\n".join(lines)
    if calc.kind == "too_long":
        lines.append(
            f"- При взносе {calc.contribution.format()} {per} понадобится {calc.periods_needed} взносов — больше 100 лет. "
            "Скажи, что при таком взносе план нереалистичен, и предложи назвать срок или больший взнос."
        )
        return "\n".join(lines)

    if calc.required is not None:
        lines.append(
            f"- {term_text[0].upper()}{term_text[1:]}, это {calc.periods} {unit} от сегодня ({_date_text(today)}). "
            f"Чтобы успеть, нужно откладывать {calc.required.format()} {per}: {calc.periods} взносов"
            + (
                f", последний — {calc.required_last.format()}."
                if calc.required_last is not None and calc.required_last != calc.required
                else "."
            )
        )
    if calc.contribution is not None and calc.periods_needed is not None:
        finish = _date_text(calc.finish_date) if calc.finish_date else "—"
        lines.append(
            f"- При взносе {calc.contribution.format()} {per} понадобится {calc.periods_needed} взносов "
            f"(ориентировочно до {finish})"
            + (
                f", последний взнос — {calc.contribution_last.format()}."
                if calc.contribution_last is not None and calc.contribution_last != calc.contribution
                else "."
            )
        )
    if calc.kind == "feasibility":
        if calc.feasible:
            lines.append(f"- Вывод: при таком взносе цель достигается к сроку (нужно не меньше {calc.required.format()} {per}).")
        else:
            lines.append(
                f"- Вывод: к сроку при таком взносе накопится {calc.accumulated_by_term.format()}, не хватит "
                f"{calc.shortfall.format()}. Чтобы успеть, нужно {calc.required.format()} {per}."
            )
    lines.append(f"- {ASSUMPTIONS}")
    if calc.period == "month":
        lines.append("- Взносы раз в месяц, первый — в ближайший месяц; срок в месяцах считается по календарным месяцам.")
    else:
        lines.append("- Взносы раз в неделю, первый — на ближайшей неделе.")
    return "\n".join(lines)
