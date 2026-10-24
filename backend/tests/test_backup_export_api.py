"""JSON-backup: экспорт."""

from __future__ import annotations

import re

from app.backup.format import BACKUP_FORMAT_VERSION, SECTIONS
from app.backup.validator import validate_backup
from tests.data_helpers import export_backup, populate, raw


def test_download_headers(seeded_client):
    r = seeded_client.get("/api/v1/export/backup")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    disposition = r.headers["content-disposition"]
    assert re.fullmatch(r'attachment; filename="finance-ai-backup-\d{4}-\d{2}-\d{2}\.json"', disposition)


def test_header_fields(seeded_client):
    doc = export_backup(seeded_client)
    assert doc["format"] == "finance-ai-backup"
    assert doc["version"] == BACKUP_FORMAT_VERSION
    assert doc["exported_at"].endswith("Z")
    assert doc["base_currency"] == doc["settings"]["base_currency"]
    assert set(doc["data"]) == set(SECTIONS)


def test_all_entities_exported_with_ids_and_relationships(seeded_client):
    s = populate(seeded_client)
    d = export_backup(seeded_client)["data"]
    assert len(d["accounts"]) == 3
    assert len(d["categories"]) == 34
    # 3 обычные операции + операция от платежа по долгу + 1 от регулярной.
    assert len(d["transactions"]) == 5
    assert len(d["transfers"]) == 1
    assert len(d["debts"]) == 1 and len(d["debt_payments"]) == 2
    assert len(d["budgets"]) == 1
    assert len(d["recurring_transactions"]) == 1 and len(d["recurring_transaction_runs"]) == 1
    assert len(d["goals"]) == 1 and len(d["goal_entries"]) == 2

    cafe = next(c for c in d["categories"] if c["id"] == s["cafe"]["id"])
    assert cafe["parent_id"] == s["food"]["id"] and cafe["icon"] == "coffee"
    assert all(e["goal_id"] == s["goal"]["id"] for e in d["goal_entries"])
    ledger = [t for t in d["transactions"] if t["debt_payment_id"] is not None]
    assert len(ledger) == 1 and ledger[0]["debt_payment_id"] == s["payments"][0]["id"]
    run = d["recurring_transaction_runs"][0]
    assert run["recurring_transaction_id"] == s["rule"]["id"]
    assert any(t["id"] == run["transaction_id"] for t in d["transactions"])


def test_money_is_integer_minor_with_currency(seeded_client):
    s = populate(seeded_client)
    d = export_backup(seeded_client)["data"]
    usd_tx = next(t for t in d["transactions"] if t["account_id"] == s["usd"]["id"])
    assert usd_tx["amount_minor"] == 1_299 and isinstance(usd_tx["amount_minor"], int)
    assert usd_tx["currency"] == "USD"
    for section in ("transactions", "transfers", "budgets", "goal_entries", "debt_payments"):
        for row in d[section]:
            assert isinstance(row["amount_minor"], int) and not isinstance(row["amount_minor"], bool)
    assert d["accounts"][0]["initial_balance_minor"] == 10_000_000


def test_dates_are_utc_iso_and_dates_are_plain(seeded_client):
    populate(seeded_client)
    d = export_backup(seeded_client)["data"]
    tx = next(t for t in d["transactions"] if t["comment"] == "Сентябрь")
    assert tx["occurred_at"] == "2026-09-01T09:00:00Z"
    assert tx["created_at"].endswith("Z")
    assert d["debts"][0]["due_date"] == "2026-12-31"
    assert d["goals"][0]["target_date"] == "2027-03-01"
    assert d["recurring_transactions"][0]["start_date"] == "2026-09-10"


def test_export_is_valid_against_own_schema(seeded_client):
    populate(seeded_client)
    doc = validate_backup(raw(export_backup(seeded_client)))
    assert doc.version == BACKUP_FORMAT_VERSION


def test_no_internal_tables_exported(seeded_client):
    doc = export_backup(seeded_client)
    text = str(doc)
    assert "alembic" not in text
    assert "app_settings" not in doc["data"]
