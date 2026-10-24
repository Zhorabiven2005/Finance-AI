"""CSV: экспорт таблиц и импорт операций (preview -> commit)."""

from __future__ import annotations

import csv
import io

import pytest

from app.backup import csv_import
from tests.data_helpers import (
    comparable,
    csv_commit,
    csv_preview,
    export_backup,
    populate,
)

HEADER = "Дата;Сумма;Тип;Счёт;Категория;Комментарий"


def parse_csv(content: bytes) -> list[dict]:
    assert content.startswith(b"\xef\xbb\xbf"), "нужен UTF-8 BOM для Excel"
    return list(csv.DictReader(io.StringIO(content.decode("utf-8-sig")), delimiter=";"))


@pytest.fixture()
def account(seeded_client):
    return seeded_client.post(
        "/api/v1/accounts",
        json={"name": "Сбер", "type": "bank", "currency": "RUB", "initial_balance_minor": 0},
    ).json()


def tx_count(client):
    return len(client.get("/api/v1/transactions", params={"limit": 100}).json())


# ---------------------------------------------------------------------------
# Экспорт
# ---------------------------------------------------------------------------


class TestCsvExport:
    def test_transactions_csv(self, seeded_client):
        s = populate(seeded_client)
        r = seeded_client.get("/api/v1/export/transactions.csv")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        assert 'filename="finance-ai-transactions-' in r.headers["content-disposition"]
        rows = parse_csv(r.content)
        assert list(rows[0]) == [
            "id", "occurred_at", "type", "amount_minor", "amount", "currency", "account_id",
            "account", "category_id", "category", "comment", "debt_id", "debt_name", "created_at",
        ]
        assert len(rows) == 5
        coffee = next(x for x in rows if x["category"] == "Кафе")
        assert coffee["amount_minor"] == "45050"
        assert coffee["amount"] == "450.50"
        assert coffee["currency"] == "RUB"
        assert coffee["account"] == "Сбер"
        assert coffee["comment"] == "Кофе, «круассан»; чек №1"
        assert coffee["occurred_at"] == "2026-09-02T12:30:00Z"
        usd = next(x for x in rows if x["currency"] == "USD")
        assert usd["amount"] == "12.99"
        ledger = next(x for x in rows if x["debt_id"])
        assert ledger["debt_id"] == str(s["debt"]["id"])
        assert ledger["debt_name"] == "Банк"
        assert ledger["category"] == "Погашение долга"

    def test_crlf_and_formula_escaping(self, seeded_client, account):
        food = next(c for c in seeded_client.get("/api/v1/categories").json() if c["name"] == "Продукты")
        seeded_client.post(
            "/api/v1/transactions",
            json={
                "account_id": account["id"], "category_id": food["id"], "type": "expense",
                "amount_minor": 100, "occurred_at": "2026-09-01T10:00:00Z", "comment": "=HYPERLINK(1)",
            },
        )
        content = seeded_client.get("/api/v1/export/transactions.csv").content
        assert b"\r\n" in content
        assert parse_csv(content)[0]["comment"] == "'=HYPERLINK(1)"

    @pytest.mark.parametrize("kind, count", [("transfers", 1), ("accounts", 3), ("debts", 1), ("goals", 1)])
    def test_other_exports(self, seeded_client, kind, count):
        populate(seeded_client)
        r = seeded_client.get(f"/api/v1/export/{kind}.csv")
        assert r.status_code == 200
        assert len(parse_csv(r.content)) == count

    def test_accounts_and_debts_values(self, seeded_client):
        populate(seeded_client)
        accounts = {a["name"]: a for a in parse_csv(seeded_client.get("/api/v1/export/accounts.csv").content)}
        api = {a["name"]: a for a in seeded_client.get("/api/v1/accounts").json()}
        assert accounts["Сбер"]["balance_minor"] == str(api["Сбер"]["balance"]["minor"])
        debt = parse_csv(seeded_client.get("/api/v1/export/debts.csv").content)[0]
        assert (debt["principal_minor"], debt["paid_minor"], debt["remaining_minor"]) == ("3000000", "1250000", "1750000")
        goal = parse_csv(seeded_client.get("/api/v1/export/goals.csv").content)[0]
        assert goal["saved_minor"] == "7000000"

    def test_unknown_export_404(self, seeded_client):
        assert seeded_client.get("/api/v1/export/secrets.csv").status_code == 404


# ---------------------------------------------------------------------------
# Импорт
# ---------------------------------------------------------------------------


VALID = "\n".join(
    [
        HEADER,
        "2026-10-01;45 000,00;доход;Сбер;Зарплата;Октябрь",
        "02.10.2026;1 200,50 ₽;расход;Сбер;Продукты;Магазин",
        "2026-10-03 18:30:00;-350;;сбер;продукты;",
        "2026-10-04T09:15:00Z;(99,90);;Сбер;Продукты;Кофе",
    ]
)


class TestCsvPreview:
    def test_valid_preview_suggests_mapping_and_writes_nothing(self, seeded_client, account):
        before = comparable(export_backup(seeded_client))
        r = csv_preview(seeded_client, VALID, {"mapping": None})
        assert r.status_code == 200, r.text
        p = r.json()
        assert p["mapping"]["occurred_at"] == "Дата"
        assert p["mapping"]["amount"] == "Сумма"
        assert p["mapping"]["account"] == "Счёт"
        assert p["delimiter"] == ";"
        assert (p["total_rows"], p["new_rows"], p["error_rows"]) == (4, 4, 0)
        assert p["can_import"] is True
        assert [s["amount_minor"] for s in p["sample"]] == [4_500_000, 120_050, 35_000, 9_990]
        assert [s["type"] for s in p["sample"]] == ["income", "expense", "expense", "expense"]
        assert comparable(export_backup(seeded_client)) == before

    def test_dates_are_utc_and_local_without_zone(self, seeded_client, account):
        # UTC+3 у браузера: getTimezoneOffset() == -180.
        p = csv_preview(seeded_client, VALID, {"tz_offset_minutes": -180}).json()
        assert p["sample"][0]["occurred_at"] == "2026-10-01T09:00:00Z"  # дата без времени — 12:00 местного
        assert p["sample"][2]["occurred_at"] == "2026-10-03T15:30:00Z"
        assert p["sample"][3]["occurred_at"] == "2026-10-04T09:15:00Z"  # явный Z не сдвигается

    def test_missing_required_column(self, seeded_client, account):
        p = csv_preview(seeded_client, "Сумма;Счёт;Категория\n100;Сбер;Продукты").json()
        assert p["can_import"] is False
        assert any("Дата" in e for e in p["mapping_errors"])
        r = csv_commit(seeded_client, "Сумма;Счёт;Категория\n100;Сбер;Продукты")
        assert r.status_code == 400

    def test_mapping_can_be_overridden(self, seeded_client, account):
        text = "Когда;Сколько;Куда;Откуда\n2026-10-01;-10;Продукты;Сбер"
        p = csv_preview(seeded_client, text).json()
        assert p["can_import"] is False
        mapping = {"occurred_at": "Когда", "amount": "Сколько", "category": "Куда", "account": "Откуда"}
        p = csv_preview(seeded_client, text, {"mapping": mapping}).json()
        assert p["can_import"] is True and p["new_rows"] == 1

    def test_mapping_to_missing_column_rejected(self, seeded_client, account):
        p = csv_preview(seeded_client, VALID, {"mapping": {"occurred_at": "Нет такой", "amount": "Сумма", "category": "Категория", "account": "Счёт"}}).json()
        assert any("Нет такой" in e for e in p["mapping_errors"])

    def test_default_account_for_all_rows(self, seeded_client, account):
        text = "Дата;Сумма;Категория\n2026-10-01;-10;Продукты"
        p = csv_preview(seeded_client, text).json()
        assert p["can_import"] is False
        p = csv_preview(seeded_client, text, {"default_account_id": account["id"]}).json()
        assert p["can_import"] is True

    @pytest.mark.parametrize(
        "amount, message",
        [("abc", "некорректная сумма"), ("0", "нулевой"), ("1,234.56", "некорректная сумма"), ("10,555", "знаков после запятой"), ("", "не указана сумма")],
    )
    def test_invalid_amount(self, seeded_client, account, amount, message):
        p = csv_preview(seeded_client, f"{HEADER}\n2026-10-01;{amount};расход;Сбер;Продукты;").json()
        assert p["error_rows"] == 1
        assert p["errors"][0]["row"] == 2
        assert message in p["errors"][0]["message"]

    @pytest.mark.parametrize("value", ["01/02/2026", "2026-02-30", "32.01.2026", "вчера", "2026/10/01"])
    def test_invalid_or_ambiguous_date(self, seeded_client, account, value):
        p = csv_preview(seeded_client, f"{HEADER}\n{value};-10;расход;Сбер;Продукты;").json()
        assert p["error_rows"] == 1
        assert "дат" in p["errors"][0]["message"]

    def test_unknown_type_and_negative_income(self, seeded_client, account):
        text = f"{HEADER}\n2026-10-01;10;перевод;Сбер;Продукты;\n2026-10-01;-10;доход;Сбер;Зарплата;"
        errors = csv_preview(seeded_client, text).json()["errors"]
        assert "неизвестный тип" in errors[0]["message"]
        assert "отрицательная сумма" in errors[1]["message"]

    def test_currency_column_must_match_account(self, seeded_client, account):
        text = "Дата;Сумма;Счёт;Категория;Валюта\n2026-10-01;-10;Сбер;Продукты;USD\n2026-10-01;-10;Сбер;Продукты;XYZ"
        errors = csv_preview(seeded_client, text).json()["errors"]
        assert "не совпадает с валютой счёта" in errors[0]["message"]
        assert "неизвестная валюта" in errors[1]["message"]

    def test_error_report_has_row_numbers(self, seeded_client, account):
        text = "\n".join([HEADER, "2026-10-01;-10;;Сбер;Продукты;", "2026-10-01;-10;;Тинкофф;Продукты;", "2026-10-01;xx;;Сбер;Продукты;"])
        p = csv_preview(seeded_client, text).json()
        assert {(e["row"], e["message"]) for e in p["errors"]} >= {
            (3, "счёт «Тинкофф» не найден"),
            (4, "некорректная сумма «xx»"),
        }
        assert (p["new_rows"], p["error_rows"]) == (1, 2)


class TestAccountCategoryResolution:
    TEXT = f"{HEADER}\n2026-10-01;-500;;Тинькофф;Игрушки;\n2026-10-02;-700;;Тинькофф;Игрушки;"

    def test_unknown_account_and_category_not_created_silently(self, seeded_client, account):
        p = csv_preview(seeded_client, self.TEXT).json()
        assert p["can_import"] is False
        assert [a["name"] for a in p["unknown_accounts"]] == ["Тинькофф"]
        assert p["unknown_accounts"][0]["rows"] == 2
        assert [(c["name"], c["type"]) for c in p["unknown_categories"]] == [("Игрушки", "expense")]
        assert csv_commit(seeded_client, self.TEXT).status_code == 400
        names = [a["name"] for a in seeded_client.get("/api/v1/accounts").json()]
        assert names == ["Сбер"]

    def test_map_to_existing(self, seeded_client, account):
        p = csv_preview(seeded_client, self.TEXT).json()
        food = next(c for c in seeded_client.get("/api/v1/categories").json() if c["name"] == "Продукты")
        options = {
            "account_resolutions": {p["unknown_accounts"][0]["key"]: {"action": "map", "target_id": account["id"]}},
            "category_resolutions": {p["unknown_categories"][0]["key"]: {"action": "map", "target_id": food["id"]}},
        }
        p2 = csv_preview(seeded_client, self.TEXT, options).json()
        assert p2["can_import"] is True and p2["new_accounts"] == []
        r = csv_commit(seeded_client, self.TEXT, options)
        assert r.json()["created"] == 2
        acc = seeded_client.get(f"/api/v1/accounts/{account['id']}").json()
        assert acc["balance"]["minor"] == -120_000

    def test_create_new_explicitly(self, seeded_client, account):
        p = csv_preview(seeded_client, self.TEXT).json()
        options = {
            "account_resolutions": {p["unknown_accounts"][0]["key"]: {"action": "create"}},
            "category_resolutions": {p["unknown_categories"][0]["key"]: {"action": "create"}},
        }
        p2 = csv_preview(seeded_client, self.TEXT, options).json()
        assert p2["new_accounts"] == [{"name": "Тинькофф", "currency": "RUB"}]
        assert p2["new_categories"] == [{"name": "Игрушки", "type": "expense"}]
        r = csv_commit(seeded_client, self.TEXT, options).json()
        assert (r["created"], r["created_accounts"], r["created_categories"]) == (2, 1, 1)
        tinkoff = next(a for a in seeded_client.get("/api/v1/accounts").json() if a["name"] == "Тинькофф")
        assert tinkoff["balance"]["minor"] == -120_000

    def test_category_of_other_type(self, seeded_client, account):
        p = csv_preview(seeded_client, f"{HEADER}\n2026-10-01;-500;;Сбер;Зарплата;").json()
        assert "категория доходов" in p["errors"][0]["message"]


class TestCsvCommit:
    def test_commit_creates_operations(self, seeded_client, account):
        r = csv_commit(seeded_client, VALID)
        assert r.status_code == 200, r.text
        assert r.json()["created"] == 4
        bal = seeded_client.get(f"/api/v1/accounts/{account['id']}").json()["balance"]["minor"]
        assert bal == 4_500_000 - 120_050 - 35_000 - 9_990

    def test_requires_confirmation(self, seeded_client, account):
        r = csv_commit(seeded_client, VALID, confirm=False)
        assert r.status_code == 400
        assert tx_count(seeded_client) == 0

    def test_repeated_import_creates_no_duplicates(self, seeded_client, account):
        csv_commit(seeded_client, VALID)
        p = csv_preview(seeded_client, VALID).json()
        assert (p["new_rows"], p["duplicate_rows"]) == (0, 4)
        assert p["can_import"] is False
        r = csv_commit(seeded_client, VALID)
        assert r.status_code == 400
        assert tx_count(seeded_client) == 4

    def test_duplicate_detection_ignores_case_and_spaces_in_comment(self, seeded_client, account):
        csv_commit(seeded_client, f"{HEADER}\n2026-10-01;-10;;Сбер;Продукты;Магазин  у дома")
        p = csv_preview(seeded_client, f"{HEADER}\n2026-10-01;-10;;Сбер;Продукты;  магазин у ДОМА").json()
        assert p["duplicate_rows"] == 1

    def test_identical_rows_compared_as_multiset(self, seeded_client, account):
        row = "2026-10-01;-150;;Сбер;Продукты;Кофе"
        csv_commit(seeded_client, f"{HEADER}\n{row}")
        p = csv_preview(seeded_client, f"{HEADER}\n{row}\n{row}").json()
        # Одна такая покупка уже есть — импортируется ровно вторая.
        assert (p["new_rows"], p["duplicate_rows"]) == (1, 1)
        csv_commit(seeded_client, f"{HEADER}\n{row}\n{row}")
        assert tx_count(seeded_client) == 2

    def test_different_amount_is_not_duplicate(self, seeded_client, account):
        csv_commit(seeded_client, f"{HEADER}\n2026-10-01;-10;;Сбер;Продукты;")
        p = csv_preview(seeded_client, f"{HEADER}\n2026-10-01;-11;;Сбер;Продукты;").json()
        assert p["new_rows"] == 1

    def test_one_bad_row_blocks_whole_import(self, seeded_client, account):
        text = VALID + "\n2026-10-05;мусор;;Сбер;Продукты;"
        r = csv_commit(seeded_client, text)
        assert r.status_code == 400
        assert "строка 6" in r.json()["detail"]
        assert tx_count(seeded_client) == 0

    def test_failure_during_write_rolls_back(self, seeded_client, account, monkeypatch):
        from sqlalchemy.orm import Session

        from app.db.models import Transaction

        text = f"{HEADER}\n2026-10-01;-500;;Тинькофф;Продукты;\n" + VALID.split("\n", 1)[1]
        p = csv_preview(seeded_client, text).json()
        options = {"account_resolutions": {p["unknown_accounts"][0]["key"]: {"action": "create"}}}

        real_add = Session.add
        calls = {"n": 0}

        def flaky_add(self, obj, *args, **kwargs):
            if isinstance(obj, Transaction):
                calls["n"] += 1
                if calls["n"] == 3:
                    raise RuntimeError("disk full")
            return real_add(self, obj, *args, **kwargs)

        monkeypatch.setattr(Session, "add", flaky_add)
        r = csv_commit(seeded_client, text, options)
        monkeypatch.undo()
        assert calls["n"] == 3
        assert r.status_code == 500
        assert tx_count(seeded_client) == 0
        # Новый счёт, созданный в той же транзакции, тоже откатился.
        assert [a["name"] for a in seeded_client.get("/api/v1/accounts").json()] == ["Сбер"]


class TestCsvRoundTripAndFormats:
    def test_export_then_import_round_trip(self, seeded_client):
        s = populate(seeded_client)
        exported = seeded_client.get("/api/v1/export/transactions.csv").content
        text = exported.decode("utf-8-sig")
        ordinary = [t for t in seeded_client.get("/api/v1/transactions", params={"limit": 100}).json() if t["debt_id"] is None]
        for t in ordinary:
            seeded_client.delete(f"/api/v1/transactions/{t['id']}")

        p = csv_preview(seeded_client, text).json()
        assert p["mapping"]["amount_minor"] == "amount_minor" and p["mapping"]["amount"] is None
        # Строка погашения долга не импортируется из CSV (только через backup).
        assert p["skipped_rows"] == 1
        assert (p["new_rows"], p["error_rows"]) == (len(ordinary), 0)
        assert csv_commit(seeded_client, text).json()["created"] == len(ordinary)

        restored = seeded_client.get("/api/v1/transactions", params={"limit": 100}).json()
        key = lambda t: (t["account_id"], t["category_id"], t["type"], t["amount"]["minor"], t["occurred_at"], t["comment"])  # noqa: E731
        assert sorted(map(key, [t for t in restored if t["debt_id"] is None])) == sorted(map(key, ordinary))
        # Повторно — ничего нового.
        assert csv_preview(seeded_client, text).json()["new_rows"] == 0

    def test_formula_escape_is_reverted_on_import(self, seeded_client, account):
        text = f"{HEADER}\n2026-10-01;-10;;Сбер;Продукты;'=SUM(1)"
        csv_commit(seeded_client, text)
        assert seeded_client.get("/api/v1/transactions").json()[0]["comment"] == "=SUM(1)"

    def test_comma_delimiter_and_quotes(self, seeded_client, account):
        text = 'date,amount,account,category,comment\n2026-10-01,"-1 200,50",Сбер,Продукты,"Хлеб, молоко"'
        p = csv_preview(seeded_client, text).json()
        assert p["delimiter"] == ","
        assert p["sample"][0]["amount_minor"] == 120_050
        assert p["sample"][0]["comment"] == "Хлеб, молоко"

    def test_windows_1251_file(self, seeded_client, account):
        p = csv_preview(seeded_client, VALID.replace(" ₽", ""), encoding="cp1251").json()
        assert p["encoding"] == "windows-1251"
        assert p["new_rows"] == 4

    @pytest.mark.parametrize(
        "content, message",
        [
            ("", "пуст"),
            ("just one column\nvalue", "разделитель"),
            ("a;a\n1;2", "несколько раз"),
        ],
    )
    def test_broken_files(self, seeded_client, account, content, message):
        r = csv_preview(seeded_client, content)
        assert r.status_code == 400
        assert message in r.json()["detail"]

    def test_binary_file_rejected(self, seeded_client):
        r = csv_preview(seeded_client, b"\x00\x01\x02;\x03")
        assert r.status_code == 400

    def test_size_and_row_limits(self, seeded_client, account, monkeypatch):
        monkeypatch.setattr(csv_import, "MAX_CSV_ROWS", 3)
        r = csv_preview(seeded_client, VALID)
        assert r.status_code == 400 and "Слишком много строк" in r.json()["detail"]
        monkeypatch.setattr(csv_import, "MAX_CSV_BYTES", 50)
        r = csv_preview(seeded_client, VALID)
        assert r.status_code == 400 and "слишком большой" in r.json()["detail"]

    def test_garbage_request_rejected(self, seeded_client):
        r = seeded_client.post("/api/v1/import/transactions/preview", json={"file_base64": "!!!не base64"})
        assert r.status_code == 400
        r = seeded_client.post("/api/v1/import/transactions/preview", json={"file": 1})
        assert r.status_code == 422
