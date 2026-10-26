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
from app.schemas.insights import InsightOut

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
