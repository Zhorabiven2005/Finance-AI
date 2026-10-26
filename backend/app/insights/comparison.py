"""Сравнение финансовых периодов (Stage 3D).

Только чтение. Правила те же, что у инсайтов Stage 3C и аналитики:
  * доходы и расходы — только операции (Transaction), по каждой валюте
    отдельно; переводы между своими счетами (Transfer) в них не входят и
    показаны отдельной строкой;
  * основной показатель расходов — «расходы на жизнь»: все расходы БЕЗ
    погашений долгов (операции, привязанные к платежу по долгу, и категория
    «Погашение долга»). Так погашение кредитки не учитывает уже записанные
    покупки второй раз. Погашения показаны отдельной строкой и входят в
    денежный поток («доходы минус все расходы»). Записаны ли сами покупки по
    кредитке, данные не знают: если нет — расходы на жизнь занижены, и это
    сказано в предупреждении. Исторические операции не переклассифицируются;
    изменения по категориям, крупные расходы и доля «Прочих» тоже считаются
    по расходам на жизнь;
  * пары «расход и доход одной суммы в один день на разных своих счетах»
    только помечаются как возможные непроведённые переводы и из сумм НЕ
    исключаются;
  * процент изменения не выводится, если база нулевая или прошлый период не
    покрыт данными.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.assistant.goal_planner import MONTHS_GENITIVE
from app.context.indicators import round_percent
from app.context.labels import sanitize_label
from app.db.models import Category, Transaction, Transfer
from app.engine import comparison as cmp
from app.engine import insights as rules
from app.engine.analytics import share_percent
from app.engine.flows import debt_repayment_category_ids, flow_kind, is_transfer
from app.engine.money import Money, money_sum
from app.schemas.insights import (
    CategoryChangeOut,
    ChangeOut,
    ComparisonWindowOut,
    CurrencyComparisonOut,
    InsightPeriodKey,
    LargeExpensesComparisonOut,
    PeriodComparisonOut,
    PossibleInternalPairsOut,
    ShareComparisonOut,
    TransfersExcludedOut,
)
from app.schemas.money import MoneyOut

MONTHS_RU = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]
TOP_CHANGES = 3
MAX_CATEGORY_ROWS = 12
HISTORY_WINDOW_DAYS = 183  # как у крупных расходов Stage 3C
OTHER_SHARE_WARNING = 25
OTHER_EXPENSE_CATEGORY = "Прочие расходы"


def _out(m: Money) -> MoneyOut:
    return MoneyOut(minor=m.minor, currency=m.currency.code)


def _change_out(c: cmp.Change) -> ChangeOut:
    return ChangeOut(
        current=_out(c.current),
        previous=_out(c.previous),
        delta=_out(c.delta),
        percent=round_percent(c.percent),
        percent_null_reason=c.percent_null_reason,
    )


def _d(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def _fmt(m: Money) -> str:
    return m.format()


def _signed_pct(value: float | None) -> str:
    if value is None:
        return ""
    return f" ({'+' if value > 0 else ''}{value:.1f}%)".replace(".", ",")


def window_label(w: cmp.Window, *, partial: bool) -> str:
    if partial:
        return f"{w.first.day}–{w.last.day} {MONTHS_GENITIVE[w.last.month - 1]} {w.last.year}"
    if w.first.month == w.last.month and w.first.year == w.last.year:
        return f"{MONTHS_RU[w.first.month - 1]} {w.first.year}"
    if w.first.year == w.last.year:
        return f"{MONTHS_RU[w.first.month - 1]}–{MONTHS_RU[w.last.month - 1]} {w.last.year}"
    return f"{MONTHS_RU[w.first.month - 1]} {w.first.year} — {MONTHS_RU[w.last.month - 1]} {w.last.year}"


def _window_out(w: cmp.Window, partial: bool) -> ComparisonWindowOut:
    return ComparisonWindowOut(date_from=w.first, date_to=w.last, label=window_label(w, partial=partial), days=w.days)


def _in(t, w: cmp.Window) -> bool:
    return w.start <= t.occurred_at <= w.end


def _direction(what: str, c: cmp.Change, prev_label: str) -> str:
    """«Расходы выросли на X (+p%) по сравнению с …» — без оценок «хорошо/плохо»."""
    pct = _signed_pct(round_percent(c.percent))
    if c.delta.is_positive:
        return f"{what} выросли на {_fmt(c.delta)}{pct}: {_fmt(c.current)} против {_fmt(c.previous)} за {prev_label}."
    if c.delta.is_negative:
        return f"{what} снизились на {_fmt(-c.delta)}{pct}: {_fmt(c.current)} против {_fmt(c.previous)} за {prev_label}."
    return f"{what} не изменились: {_fmt(c.current)}."


def build_comparison(db: Session, *, period_key: InsightPeriodKey, today: date) -> PeriodComparisonOut:
    windows = cmp.comparison_windows(period_key, today)
    cur_w, prev_w = windows.current, windows.previous
    cur_label = window_label(cur_w, partial=windows.same_days)
    prev_label = window_label(prev_w, partial=windows.same_days and not windows.previous_shorter)

    if windows.same_days:
        note = f"Сравниваются одинаковые дни: {cur_label} и {prev_label}."
        if windows.previous_shorter:
            note = (
                f"Сравниваются {cur_label} и весь {prev_label}: в прошлом месяце только {prev_w.days} дн., "
                "поэтому дней в периодах не поровну."
            )
    elif period_key == "previous_month":
        note = f"Сравниваются полные календарные месяцы: {cur_label} и {prev_label}."
    else:
        note = f"Сравниваются три полных месяца: {cur_label} и {prev_label}."

    history_start = min(prev_w.start, cur_w.end - timedelta(days=HISTORY_WINDOW_DAYS))
    txs = list(
        db.scalars(
            select(Transaction)
            .where(Transaction.occurred_at >= history_start, Transaction.occurred_at <= cur_w.end)
            .order_by(Transaction.occurred_at, Transaction.id)
        )
    )
    transfers = list(
        db.scalars(select(Transfer).where(Transfer.occurred_at >= prev_w.start, Transfer.occurred_at <= cur_w.end))
    )
    categories = {c.id: c for c in db.scalars(select(Category))}
    first = db.scalar(select(func.min(Transaction.occurred_at)))
    first_day = first.astimezone(timezone.utc).date() if first is not None else None

    # Отмеченные пользователем переводы (Stage 3F) — не доходы и не расходы ни
    # в одном из периодов; показываются отдельной строкой.
    marked = [t for t in txs if is_transfer(t)]
    txs = [t for t in txs if not is_transfer(t)]
    cur_txs = [t for t in txs if _in(t, cur_w)]
    prev_txs = [t for t in txs if _in(t, prev_w)]
    out = PeriodComparisonOut(
        key=period_key,
        current=_window_out(cur_w, windows.same_days),
        previous=_window_out(prev_w, windows.same_days and not windows.previous_shorter),
        same_days=windows.same_days,
        note=note,
        by_currency=[],
        unavailable_reason=None,
    )
    if not cur_txs and not prev_txs and not any(_in(t, cur_w) or _in(t, prev_w) for t in marked):
        out.unavailable_reason = "Ни в одном из двух периодов нет операций — сравнивать нечего."
        return out

    # Прошлый период покрыт данными, только если история начинается не позже
    # его первого дня. Иначе проценты от неполной базы не выводятся.
    history_ok = first_day is not None and first_day <= prev_w.first
    history_warning = None
    if not history_ok:
        if first_day is None or first_day > prev_w.last:
            history_warning = f"За {prev_label} операций в приложении нет: сравнение показывает только текущие суммы, проценты не считаются."
        else:
            history_warning = (
                f"Операции в приложении есть только с {_d(first_day)}: {prev_label} покрыт данными частично, "
                "поэтому разница между периодами не отражает реальное изменение, проценты не считаются."
            )
        if first_day is not None and first_day > cur_w.first:
            history_warning += f" Текущий период ({cur_label}) тоже покрыт данными только с {_d(first_day)}."

    debt_category_ids = set(debt_repayment_category_ids(categories.values()))
    other_ids = {cid for cid, c in categories.items() if c.is_default and c.type == "expense" and c.name == OTHER_EXPENSE_CATEGORY}

    for cur in sorted({t.currency for t in cur_txs + prev_txs + [m for m in marked if _in(m, cur_w) or _in(m, prev_w)]}):
        out.by_currency.append(
            _currency_comparison(
                cur,
                [t for t in cur_txs if t.currency == cur],
                [t for t in prev_txs if t.currency == cur],
                [t for t in txs if t.currency == cur and t.type == "expense"],
                [tr for tr in transfers if tr.currency == cur],
                [t for t in marked if t.currency == cur],
                windows,
                cur_label,
                prev_label,
                categories,
                debt_category_ids,
                other_ids,
                history_ok,
                history_warning,
            )
        )
    return out


def _sum(txs, cur: str, kind: str | None = None, pred=None) -> Money:
    return money_sum(
        (Money.of(t.amount_minor, cur) for t in txs if (kind is None or t.type == kind) and (pred is None or pred(t))),
        cur,
    )


def _currency_comparison(
    cur: str,
    cur_txs: list[Transaction],
    prev_txs: list[Transaction],
    baseline_expenses: list[Transaction],
    transfers: list[Transfer],
    marked: list[Transaction],
    windows: cmp.ComparisonWindows,
    cur_label: str,
    prev_label: str,
    categories: dict[int, Category],
    debt_category_ids: set[int],
    other_ids: set[int],
    history_ok: bool,
    history_warning: str | None,
) -> CurrencyComparisonOut:
    def change(c: Money, p: Money) -> cmp.Change:
        return cmp.change(c, p, history_ok=history_ok)

    is_debt = lambda t: flow_kind(t, debt_category_ids) == "debt_repayment"  # noqa: E731 — единое правило
    income = change(_sum(cur_txs, cur, "income"), _sum(prev_txs, cur, "income"))
    expense = change(_sum(cur_txs, cur, "expense"), _sum(prev_txs, cur, "expense"))
    net = change(income.current - expense.current, income.previous - expense.previous)
    debt = change(_sum(cur_txs, cur, "expense", is_debt), _sum(prev_txs, cur, "expense", is_debt))
    without_debt = change(expense.current - debt.current, expense.previous - debt.previous)

    # --- категории расходов ---
    by_cat: dict[int, list[Money]] = defaultdict(lambda: [Money.zero(cur), Money.zero(cur)])
    for idx, group in enumerate((cur_txs, prev_txs)):
        for t in group:
            if t.type == "expense" and not is_debt(t):
                by_cat[t.category_id][idx] = by_cat[t.category_id][idx] + Money.of(t.amount_minor, cur)
    rows = []
    for cid, (c, p) in by_cat.items():
        ch = change(c, p)
        rows.append(
            CategoryChangeOut(
                category_id=cid,
                label=sanitize_label(categories[cid].name if cid in categories else None)[0] or "—",
                **_change_out(ch).model_dump(),
            )
        )
    rows.sort(key=lambda r: (-abs(r.delta.minor), r.category_id))
    up = sorted((r for r in rows if r.delta.minor > 0), key=lambda r: (-r.delta.minor, r.category_id))[:TOP_CHANGES]
    down = sorted((r for r in rows if r.delta.minor < 0), key=lambda r: (r.delta.minor, r.category_id))[:TOP_CHANGES]

    # --- крупные расходы: один порог на оба периода, по расходам на жизнь ---
    baseline_expenses = [t for t in baseline_expenses if not is_debt(t)]
    threshold = rules.large_expense_threshold([t.amount_minor for t in baseline_expenses])
    large = None
    large_reason = None
    if threshold is None:
        large_reason = (
            f"Мало расходов для оценки обычного уровня трат: нужно хотя бы {rules.LARGE_EXPENSE_MIN_BASELINE} за полгода, "
            f"сейчас {len(baseline_expenses)}."
        )
    else:
        is_large = lambda t: t.amount_minor >= threshold.threshold_minor  # noqa: E731
        large_cur = [t for t in cur_txs if t.type == "expense" and not is_debt(t) and is_large(t)]
        large_prev = [t for t in prev_txs if t.type == "expense" and not is_debt(t) and is_large(t)]
        large = LargeExpensesComparisonOut(
            threshold=_out(Money.of(threshold.threshold_minor, cur)),
            current_count=len(large_cur),
            previous_count=len(large_prev),
            total=_change_out(change(_sum(large_cur, cur), _sum(large_prev, cur))),
        )

    # --- доля «Прочих расходов» ---
    def other_share(txs: list[Transaction]) -> float | None:
        total = _sum(txs, cur, "expense", lambda t: not is_debt(t))
        if not total.minor:
            return None
        return round_percent(share_percent(_sum(txs, cur, "expense", lambda t: t.category_id in other_ids), total))

    share_cur, share_prev = other_share(cur_txs), other_share(prev_txs)
    share = ShareComparisonOut(
        current=share_cur,
        previous=share_prev,
        delta_points=round(share_cur - share_prev, 1) if share_cur is not None and share_prev is not None else None,
    )

    # --- переводы и возможные непроведённые переводы ---
    tr_cur = [tr for tr in transfers if _in(tr, windows.current)]
    tr_prev = [tr for tr in transfers if _in(tr, windows.previous)]
    marked_cur = [t for t in marked if _in(t, windows.current)]
    marked_prev = [t for t in marked if _in(t, windows.previous)]
    transfers_out = TransfersExcludedOut(
        current_count=len(tr_cur),
        current_total=_out(_sum(tr_cur, cur)),
        previous_count=len(tr_prev),
        previous_total=_out(_sum(tr_prev, cur)),
        marked_current_count=len(marked_cur),
        marked_current_total=_out(_sum(marked_cur, cur)),
        marked_previous_count=len(marked_prev),
        marked_previous_total=_out(_sum(marked_prev, cur)),
    )
    pairs = []
    for group in (cur_txs, prev_txs):
        pairs += cmp.mirror_pairs(
            [cmp.Movement(t.id, t.account_id, t.type, t.amount_minor, t.occurred_at.astimezone(timezone.utc).date()) for t in group]  # type: ignore[arg-type]
        )
    pairs_total = money_sum((Money.of(o.amount_minor, cur) for o, _ in pairs), cur)

    # --- предупреждения и уверенность ---
    warnings: list[str] = []
    if history_warning:
        warnings.append(history_warning)
    if not cur_txs:
        warnings.append("В текущем периоде операций в этой валюте нет.")
    high_other = [s for s in (share_cur, share_prev) if s is not None and s >= OTHER_SHARE_WARNING]
    if high_other:
        parts = []
        if share_cur is not None:
            parts.append(f"{share_cur:.1f}% сейчас".replace(".", ","))
        if share_prev is not None:
            parts.append(f"{share_prev:.1f}% в прошлом периоде".replace(".", ","))
        warnings.append(
            f"Доля «{OTHER_EXPENSE_CATEGORY}» — {' и '.join(parts)}: изменения по категориям менее достоверны, "
            "часть трат может быть не тем, чем кажется (в том числе переводами на свои кредитные продукты)."
        )
    if pairs:
        warnings.append(
            f"Найдено {len(pairs)} пар «расход и доход одной суммы в один день на разных счетах» на {_fmt(pairs_total)}. "
            "Возможно, это переводы между своими счетами, записанные как операции: они учтены в доходах и расходах. "
            "Если это переводы — оформите их как переводы, и сравнение станет точнее."
        )
    has_debt = bool(debt.current.minor or debt.previous.minor)
    if has_debt:
        warnings.append(
            f"Погашения долгов ({_fmt(debt.current)} сейчас, {_fmt(debt.previous)} в прошлом периоде) не входят в "
            "расходы на жизнь, чтобы покупки по кредитной карте, уже записанные расходами, не учитывались второй раз. "
            "Приложение не может проверить, записаны ли эти покупки: если нет, расходы на жизнь занижены на часть "
            "погашений. В денежном потоке («доходы минус все расходы») погашения учтены."
        )
    if not history_ok:
        confidence = "low"
    elif high_other or pairs or has_debt:
        confidence = "medium"
    else:
        confidence = "high"

    # --- итог словами (только посчитанные значения) ---
    if not history_ok:
        # Без данных за прошлый период «рост» — артефакт пустой истории, а не
        # факт: называем только текущие суммы.
        summary = [
            f"За {cur_label}: доходы {_fmt(income.current)}, расходы на жизнь {_fmt(without_debt.current)}.",
            f"Надёжно сравнить с периодом «{prev_label}» нельзя — за него в приложении нет полных данных.",
        ]
        up_down: list[CategoryChangeOut] = []
    else:
        summary = [_direction("Расходы на жизнь", without_debt, prev_label), _direction("Доходы", income, prev_label)]
        up_down = [*up[:1], *down[:1]]
    if net.current.is_negative:
        what = "Все расходы вместе с погашениями долгов" if debt.current.minor else "Расходы"
        summary.append(f"{what} превышают доходы на {_fmt(-net.current)}.")
    if up and up[0] in up_down:
        top = up[0]
        summary.append(
            f"Сильнее всего выросли расходы на «{top.label}»: +{_fmt(Money.of(top.delta.minor, cur))}"
            f"{_signed_pct(top.percent)}."
        )
    if down and down[0] in up_down:
        bottom = down[0]
        summary.append(
            f"Сильнее всего снизились на «{bottom.label}»: −{_fmt(Money.of(-bottom.delta.minor, cur))}"
            f"{_signed_pct(bottom.percent)}."
        )

    return CurrencyComparisonOut(
        currency=cur,
        confidence=confidence,  # type: ignore[arg-type]
        income=_change_out(income),
        expense=_change_out(expense),
        net=_change_out(net),
        debt_repayments=_change_out(debt),
        expense_without_debt_repayments=_change_out(without_debt),
        categories_up=up,
        categories_down=down,
        categories=rows[:MAX_CATEGORY_ROWS],
        categories_truncated=len(rows) > MAX_CATEGORY_ROWS,
        large_expenses=large,
        large_expenses_null_reason=large_reason,
        other_share=share,
        transfers_excluded=transfers_out,
        possible_internal_pairs=PossibleInternalPairsOut(count=len(pairs), total=_out(pairs_total)),
        summary=" ".join(summary),
        warnings=warnings,
    )
