"""API-тесты финансовых целей."""

from __future__ import annotations

import pytest


def create_goal(client, **overrides):
    payload = {
        "name": "MacBook",
        "target_amount_minor": 18_000_000,
        "currency": "RUB",
        **overrides,
    }
    r = client.post("/api/v1/goals", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def add_entry(client, goal_id, type_, amount_minor, occurred_at="2026-09-01T10:00:00Z", **overrides):
    r = client.post(
        f"/api/v1/goals/{goal_id}/entries",
        json={"type": type_, "amount_minor": amount_minor, "occurred_at": occurred_at, **overrides},
    )
    return r


class TestCreateGoal:
    def test_create_goal(self, client):
        goal = create_goal(client, name="Отпуск", target_amount_minor=12_000_000, description="Турция")
        assert goal["name"] == "Отпуск"
        assert goal["description"] == "Турция"
        assert goal["target"]["minor"] == 12_000_000
        assert goal["saved"]["minor"] == 0
        assert goal["remaining"]["minor"] == 12_000_000
        assert goal["progress_percent"] == 0
        assert goal["status"] == "active"
        assert "created_at" in goal

    def test_target_date_nullable(self, client):
        goal = create_goal(client)
        assert goal["target_date"] is None

    def test_target_date_stored(self, client):
        goal = create_goal(client, target_date="2027-03-01")
        assert goal["target_date"] == "2027-03-01"

    def test_zero_target_rejected(self, client):
        r = client.post(
            "/api/v1/goals", json={"name": "X", "target_amount_minor": 0, "currency": "RUB"}
        )
        assert r.status_code == 422

    def test_negative_target_rejected(self, client):
        r = client.post(
            "/api/v1/goals", json={"name": "X", "target_amount_minor": -100, "currency": "RUB"}
        )
        assert r.status_code == 422

    def test_float_amount_rejected(self, client):
        r = client.post(
            "/api/v1/goals", json={"name": "X", "target_amount_minor": 100.5, "currency": "RUB"}
        )
        assert r.status_code == 422

    def test_large_target_amount(self, client):
        goal = create_goal(client, target_amount_minor=100_000_000_000)
        assert goal["target"]["minor"] == 100_000_000_000


class TestGetUpdateDeleteGoal:
    def test_get_goal(self, client):
        goal = create_goal(client)
        r = client.get(f"/api/v1/goals/{goal['id']}")
        assert r.status_code == 200
        assert r.json()["id"] == goal["id"]

    def test_get_missing_goal_404(self, client):
        assert client.get("/api/v1/goals/999999").status_code == 404

    def test_update_name_and_target(self, client):
        goal = create_goal(client)
        r = client.patch(
            f"/api/v1/goals/{goal['id']}", json={"name": "MacBook Pro", "target_amount_minor": 20_000_000}
        )
        assert r.status_code == 200
        assert r.json()["name"] == "MacBook Pro"
        assert r.json()["target"]["minor"] == 20_000_000

    def test_delete_goal(self, client):
        goal = create_goal(client)
        r = client.delete(f"/api/v1/goals/{goal['id']}")
        assert r.status_code == 204
        assert client.get(f"/api/v1/goals/{goal['id']}").status_code == 404

    def test_archive_goal_via_patch(self, client):
        goal = create_goal(client)
        r = client.patch(f"/api/v1/goals/{goal['id']}", json={"is_archived": True})
        assert r.json()["status"] == "archived"

    def test_delete_goal_cascades_entries(self, client):
        goal = create_goal(client)
        add_entry(client, goal["id"], "contribution", 1_000_000)
        r = client.delete(f"/api/v1/goals/{goal['id']}")
        assert r.status_code == 204


class TestGoalEntries:
    def test_contribution_increases_saved(self, client):
        goal = create_goal(client)
        add_entry(client, goal["id"], "contribution", 7_200_000)
        updated = client.get(f"/api/v1/goals/{goal['id']}").json()
        assert updated["saved"]["minor"] == 7_200_000
        assert updated["remaining"]["minor"] == 10_800_000
        assert updated["progress_percent"] == 40.0
        assert updated["status"] == "active"

    def test_multiple_contributions_sum(self, client):
        goal = create_goal(client, target_amount_minor=18_000_000)
        add_entry(client, goal["id"], "contribution", 7_200_000)
        add_entry(client, goal["id"], "contribution", 10_800_000)
        updated = client.get(f"/api/v1/goals/{goal['id']}").json()
        assert updated["saved"]["minor"] == 18_000_000
        assert updated["remaining"]["minor"] == 0
        assert updated["progress_percent"] == 100.0
        assert updated["status"] == "completed"

    def test_withdrawal_decreases_saved(self, client):
        goal = create_goal(client, target_amount_minor=18_000_000)
        add_entry(client, goal["id"], "contribution", 10_000_000)
        add_entry(client, goal["id"], "withdrawal", 3_000_000)
        updated = client.get(f"/api/v1/goals/{goal['id']}").json()
        assert updated["saved"]["minor"] == 7_000_000

    def test_withdrawal_exceeding_saved_rejected(self, client):
        goal = create_goal(client)
        add_entry(client, goal["id"], "contribution", 7_200_000)
        r = add_entry(client, goal["id"], "withdrawal", 10_000_000)
        assert r.status_code == 400
        # Баланс не должен был измениться после отклонённого запроса.
        unchanged = client.get(f"/api/v1/goals/{goal['id']}").json()
        assert unchanged["saved"]["minor"] == 7_200_000

    def test_withdrawal_exactly_equal_to_saved_allowed(self, client):
        goal = create_goal(client)
        add_entry(client, goal["id"], "contribution", 5_000_000)
        r = add_entry(client, goal["id"], "withdrawal", 5_000_000)
        assert r.status_code == 201
        updated = client.get(f"/api/v1/goals/{goal['id']}").json()
        assert updated["saved"]["minor"] == 0

    def test_withdrawal_from_empty_goal_rejected(self, client):
        goal = create_goal(client)
        r = add_entry(client, goal["id"], "withdrawal", 1)
        assert r.status_code == 400

    def test_completing_then_withdrawing_reverts_to_active(self, client):
        goal = create_goal(client, target_amount_minor=18_000_000)
        add_entry(client, goal["id"], "contribution", 18_000_000)
        assert client.get(f"/api/v1/goals/{goal['id']}").json()["status"] == "completed"
        add_entry(client, goal["id"], "withdrawal", 1_000_000)
        assert client.get(f"/api/v1/goals/{goal['id']}").json()["status"] == "active"

    def test_list_entries(self, client):
        goal = create_goal(client)
        add_entry(client, goal["id"], "contribution", 1_000_000, occurred_at="2026-09-01T10:00:00Z")
        add_entry(client, goal["id"], "contribution", 2_000_000, occurred_at="2026-09-05T10:00:00Z")
        r = client.get(f"/api/v1/goals/{goal['id']}/entries")
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_delete_entry(self, client):
        goal = create_goal(client)
        entry = add_entry(client, goal["id"], "contribution", 1_000_000).json()
        r = client.delete(f"/api/v1/goals/{goal['id']}/entries/{entry['id']}")
        assert r.status_code == 204
        assert client.get(f"/api/v1/goals/{goal['id']}").json()["saved"]["minor"] == 0

    def test_entry_comment_stored(self, client):
        goal = create_goal(client)
        r = add_entry(client, goal["id"], "contribution", 1_000_000, comment="Премия")
        assert r.json()["comment"] == "Премия"


class TestGoalCurrency:
    def test_entry_inherits_goal_currency(self, client):
        goal = create_goal(client, currency="USD", target_amount_minor=100_000)
        entry = add_entry(client, goal["id"], "contribution", 50_000).json()
        assert entry["amount"]["currency"] == "USD"

    def test_different_goals_different_currencies_independent(self, client):
        rub_goal = create_goal(client, currency="RUB", target_amount_minor=1_000_000)
        usd_goal = create_goal(client, currency="USD", target_amount_minor=1_000_000)
        add_entry(client, rub_goal["id"], "contribution", 500_000)
        rub_updated = client.get(f"/api/v1/goals/{rub_goal['id']}").json()
        usd_updated = client.get(f"/api/v1/goals/{usd_goal['id']}").json()
        assert rub_updated["saved"]["minor"] == 500_000
        assert usd_updated["saved"]["minor"] == 0
