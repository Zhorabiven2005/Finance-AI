"""Объяснение инсайта локальной моделью (Stage 3C).

Модель получает только один уже посчитанный инсайт — в том же формате
запроса, что и чат (prompts.build_messages): неизменяемые правила и блок
ДАННЫЕ. Пользовательского текста в запросе нет вовсе: вопрос к модели —
фиксированная фраза приложения. Названия категорий и счетов выводятся как
строковые литералы JSON (данные, а не инструкции); комментариев к операциям
в инсайтах нет.

Числа в ответе модели сверяются с этим же блоком (grounding).
"""

from __future__ import annotations

from app.assistant.digest import label
from app.engine.money import Money
from app.schemas.insights import ChangeOut, CurrencyComparisonOut, InsightOut, PeriodComparisonOut

EXPLAIN_REQUEST = (
    "Объясни простыми словами этот вывод приложения в 3–5 предложениях: что он означает и почему на него стоит "
    "обратить внимание. Если уместно, предложи одно-два осторожных действия, которые прямо следуют из этих данных. "
    "Называй только числа из данных и только с тем смыслом, который указан в их названии: не пересчитывай, не "
    "округляй и не называй их средними, если так не написано. Не придумывай причин трат и обстоятельств; учитывай "
    "ограничения и уверенность."
)

TYPE_TEXT = {
    "cash_flow": "доходы и расходы за период",
    "spending_structure": "структура расходов по категориям",
    "large_expenses": "крупные расходы относительно обычного уровня трат",
    "recurring_expenses": "возможные регулярные платежи",
    "budgets": "бюджеты текущего месяца",
    "goals": "финансовые цели",
    "data_quality": "надёжность данных",
}
CONFIDENCE_TEXT = {"high": "высокая", "medium": "средняя", "low": "низкая"}


def _money(m) -> str:
    return Money.of(m.minor, m.currency).format()


def _pct(value: float) -> str:
    return f"{value:.1f}".replace(".", ",") + "%"


def facts_text(insight: InsightOut) -> str:
    p = insight.period
    lines = [
        f"## Вывод приложения: {insight.title}",
        f"- Тип: {TYPE_TEXT[insight.type]}.",
        f"- Период: {p.label} ({p.date_from.isoformat()} — {p.date_to.isoformat()}).",
        f"- Валюта: {insight.currency or 'у каждой строки своя, суммы разных валют не складываются'}.",
        f"- Уверенность вывода: {CONFIDENCE_TEXT[insight.confidence]}.",
        "## Показатели",
    ]
    for m in insight.metrics:
        if m.money is not None:
            value = _money(m.money)
        elif m.percent is not None:
            value = _pct(m.percent)
        elif m.count is not None:
            value = str(m.count)
        else:
            value = "нет данных"
        lines.append(f"- {m.label}: {value}.")
    if insight.items:
        lines.append("## Строки")
        for item in insight.items:
            parts = [label(item.label)]
            if item.money is not None:
                parts.append(_money(item.money))
            if item.percent is not None:
                parts.append(_pct(item.percent))
            if item.date is not None:
                parts.append(f"дата {item.date.isoformat()}")
            if item.note:
                parts.append(item.note)
            lines.append("- " + "; ".join(parts) + ".")
    lines.append("## Итог приложения")
    lines.append(f"- {insight.summary}")
    if insight.limitations:
        lines.append("## Ограничения")
        lines += [f"- {x}" for x in insight.limitations]
    return "\n".join(lines)


COMPARISON_ID_PREFIX = "comparison:"
PERCENT_NULL_TEXT = {
    "zero_base": "процента нет: в прошлом периоде было 0",
    "insufficient_history": "процента нет: прошлый период не покрыт данными",
}


def _change(c: ChangeOut) -> str:
    sign = "+" if c.delta.minor > 0 else ""
    pct = (
        f"{'+' if (c.percent or 0) > 0 else ''}{_pct(c.percent)}"
        if c.percent is not None
        else PERCENT_NULL_TEXT[c.percent_null_reason or "zero_base"]
    )
    return f"сейчас {_money(c.current)}, было {_money(c.previous)}, изменение {sign}{_money(c.delta)} ({pct})"


def comparison_facts_text(comparison: PeriodComparisonOut, item: CurrencyComparisonOut) -> str:
    """Сравнение периодов для модели: только посчитанные значения."""
    lines = [
        "## Вывод приложения: сравнение периодов",
        f"- Текущий период: {comparison.current.label}; прошлый: {comparison.previous.label}.",
        f"- {comparison.note}",
        f"- Валюта: {item.currency}. Уверенность вывода: {CONFIDENCE_TEXT[item.confidence]}.",
        "## Показатели",
        f"- Доходы: {_change(item.income)}.",
        f"- Расходы на жизнь (без погашений долгов): {_change(item.expense_without_debt_repayments)}.",
        f"- Погашения долгов (не входят в расходы на жизнь): {_change(item.debt_repayments)}.",
        f"- Все расходы вместе с погашениями: {_change(item.expense)}.",
        f"- Доходы минус все расходы: {_change(item.net)}.",
    ]
    t = item.transfers_excluded
    lines.append(
        f"- Переводы между своими счетами не входят в доходы и расходы: сейчас {t.current_count} на "
        f"{_money(t.current_total)}, было {t.previous_count} на {_money(t.previous_total)}."
    )
    if item.categories:
        lines.append("## Изменение расходов по категориям")
        lines += [f"- {label(r.label)}: {_change(r)}." for r in item.categories]
    if item.large_expenses is not None:
        le = item.large_expenses
        lines.append(
            f"- Крупные расходы (от {_money(le.threshold)}): сейчас {le.current_count}, было {le.previous_count}; "
            f"сумма — {_change(le.total)}."
        )
    elif item.large_expenses_null_reason:
        lines.append(f"- Крупные расходы: {item.large_expenses_null_reason}")
    sh = item.other_share
    if sh.current is not None or sh.previous is not None:
        cur = _pct(sh.current) if sh.current is not None else "нет расходов"
        prev = _pct(sh.previous) if sh.previous is not None else "нет расходов"
        lines.append(f"- Доля «Прочих расходов»: сейчас {cur}, было {prev}.")
    lines.append("## Итог приложения")
    lines.append(f"- {item.summary}")
    if item.warnings:
        lines.append("## Ограничения")
        lines += [f"- {w}" for w in item.warnings]
    return "\n".join(lines)
