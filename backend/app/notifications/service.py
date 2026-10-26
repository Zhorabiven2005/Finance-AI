"""Notification engine: сбор фактов из БД, запись уведомлений, жизненный цикл.

Идемпотентность:
  * у каждого события стабильный dedup_key (UNIQUE в БД);
  * если строка с ключом уже есть — новая не создаётся, даже если
    пользователь её удалил (удаление мягкое, deleted_at);
  * при каждой проверке вычисляется множество ключей, актуальных СЕЙЧАС.
    Уведомления engine-типов, чей ключ больше не актуален, получают
    resolved_at; если событие снова стало актуальным — resolved_at снимается;
  * очистка физически удаляет только записи, неактуальные дольше
    RETENTION_DAYS: ключи содержат дату/период события, а горизонт проверок
    ограничен, поэтому такой ключ уже не может стать актуальным снова.
    Удалённая пользователем, но всё ещё актуальная запись не очищается —
    иначе событие вернулось бы.

Параллельный запуск (старт backend, таймер, ручная проверка) исключён
блокировкой процесса; вторая линия защиты — UNIQUE на dedup_key.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import clock
from app.api.v1.budgets import compute_spent
from app.db.models import Budget, Debt, Notification, RecurringTransaction, Transaction
from app.engine.budgets import month_bounds
from app.engine.flows import is_transfer
from app.engine.debts import debt_remaining
from app.engine.money import Money, get_currency, money_sum
from app.notifications import rules
from app.notifications.rules import BudgetFact, Candidate, DebtFact, RecurringFact

logger = logging.getLogger("app.notifications")

_LOCK = threading.Lock()


class NotificationCheckBusy(Exception):
    """Проверка уже выполняется в другом потоке."""


@dataclass
class CheckResult:
    created: int = 0
    resolved: int = 0
    reactivated: int = 0
    purged: int = 0

    def as_dict(self) -> dict[str, int]:
        return {"created": self.created, "resolved": self.resolved, "reactivated": self.reactivated, "purged": self.purged}


# ---------------------------------------------------------------------------
# Сбор фактов
# ---------------------------------------------------------------------------


def _debt_facts(db: Session) -> list[DebtFact]:
    facts = []
    for d in db.scalars(select(Debt).where(Debt.due_date.is_not(None))):
        cur = get_currency(d.currency)
        remaining = debt_remaining(Money.of(d.principal_minor, cur), [Money.of(p.amount_minor, cur) for p in d.payments])
        facts.append(DebtFact(d.id, d.counterparty_name, d.direction, remaining, d.due_date))
    return facts


def _budget_facts(db: Session, today: date) -> list[BudgetFact]:
    facts = []
    for b in db.scalars(select(Budget).where(Budget.year == today.year, Budget.month == today.month)):
        facts.append(
            BudgetFact(b.id, b.category.name, b.year, b.month, Money.of(b.amount_minor, b.currency), compute_spent(db, b))
        )
    return facts


def _expense_totals(db: Session, today: date) -> dict[tuple[str, int, int], Money]:
    last = rules.previous_month(today.year, today.month)
    prev = rules.previous_month(*last)
    start, _ = month_bounds(*prev)
    _, end = month_bounds(*last)
    sums: dict[tuple[str, int, int], list[Money]] = defaultdict(list)
    for t in db.scalars(
        select(Transaction).where(
            Transaction.type == "expense", Transaction.occurred_at >= start, Transaction.occurred_at <= end
        )
    ):
        if is_transfer(t):  # отмеченный перевод — не расход (Stage 3F)
            continue
        at = t.occurred_at.astimezone(timezone.utc)
        sums[(t.currency, at.year, at.month)].append(Money.of(t.amount_minor, t.currency))
    return {k: money_sum(v, k[0]) for k, v in sums.items()}


def _recurring_facts(db: Session) -> list[RecurringFact]:
    return [
        RecurringFact(
            r.id, r.category.name, r.type, Money.of(r.amount_minor, r.currency), r.next_run_date, r.end_date, r.is_active
        )
        for r in db.scalars(select(RecurringTransaction).where(RecurringTransaction.is_active.is_(True)))
    ]


def collect_candidates(db: Session, today: date) -> list[Candidate]:
    return [
        *rules.debt_candidates(_debt_facts(db), today),
        *rules.budget_candidates(_budget_facts(db, today), today),
        *rules.spending_candidates(_expense_totals(db, today), today),
        *rules.recurring_candidates(_recurring_facts(db), today),
    ]


# ---------------------------------------------------------------------------
# Запись
# ---------------------------------------------------------------------------


def _to_row(c: Candidate) -> Notification:
    return Notification(
        type=c.type,
        severity=c.severity,
        title=c.title,
        message=c.message,
        entity_type=c.entity_type,
        entity_id=c.entity_id,
        dedup_key=c.dedup_key,
        data=json.dumps(c.data, ensure_ascii=False) if c.data else None,
    )


def _apply(db: Session, today: date, now: datetime) -> CheckResult:
    result = CheckResult()
    candidates = {c.dedup_key: c for c in collect_candidates(db, today)}
    existing = {n.dedup_key: n for n in db.scalars(select(Notification).where(Notification.type.in_(rules.ENGINE_TYPES)))}

    for key, candidate in candidates.items():
        row = existing.get(key)
        if row is None:
            db.add(_to_row(candidate))
            result.created += 1
        elif row.resolved_at is not None:
            # Событие снова актуально (например, бюджет опять превышен в том
            # же месяце). Удалённое пользователем остаётся скрытым.
            row.resolved_at = None
            if row.deleted_at is None:
                row.read_at = None
            result.reactivated += 1

    for key, row in existing.items():
        if key not in candidates and row.resolved_at is None:
            row.resolved_at = now
            result.resolved += 1

    cutoff = now - timedelta(days=rules.RETENTION_DAYS)
    purge_engine = db.execute(
        delete(Notification).where(Notification.resolved_at.is_not(None), Notification.resolved_at < cutoff)
    )
    # Системные события одноразовые (ключ уникален по времени) — их можно
    # чистить, когда они прочитаны или удалены и старше срока хранения.
    purge_system = db.execute(
        delete(Notification).where(
            Notification.type == rules.T_SYSTEM,
            Notification.created_at < cutoff,
            (Notification.read_at.is_not(None)) | (Notification.deleted_at.is_not(None)),
        )
    )
    result.purged = (purge_engine.rowcount or 0) + (purge_system.rowcount or 0)
    db.commit()
    return result


def generate_notifications(
    db: Session,
    today: date | None = None,
    now: datetime | None = None,
    *,
    wait_seconds: float = 30.0,
) -> CheckResult:
    """Идемпотентная проверка. Повторный вызов без изменений данных создаёт 0."""
    today = today or clock.today()
    now = now or datetime.now(timezone.utc)
    acquired = _LOCK.acquire(timeout=wait_seconds) if wait_seconds > 0 else _LOCK.acquire(blocking=False)
    if not acquired:
        raise NotificationCheckBusy()
    try:
        try:
            return _apply(db, today, now)
        except IntegrityError:
            # Ключ успел записать кто-то ещё (другой процесс) — повторяем
            # один раз на свежем состоянии, дублей не будет из-за UNIQUE.
            db.rollback()
            return _apply(db, today, now)
    except Exception:
        db.rollback()
        raise
    finally:
        _LOCK.release()


def create_system_notification(
    db: Session, key: str, title: str, message: str, data: dict | None = None, severity: str = "info"
) -> Notification | None:
    """Одноразовое системное событие; повтор с тем же ключом игнорируется."""
    dedup_key = f"{rules.T_SYSTEM}:{key}"
    if db.scalar(select(Notification.id).where(Notification.dedup_key == dedup_key)):
        return None
    row = _to_row(Candidate(rules.T_SYSTEM, severity, title, message, dedup_key, data=data or {}))
    db.add(row)
    db.commit()
    return row
