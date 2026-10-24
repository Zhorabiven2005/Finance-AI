"""Удаление цели отличается от архивации: цель и её GoalEntry исчезают совсем,
в любом статусе. Подтверждение — забота фронтенда (модалка), не API."""

from __future__ import annotations

from sqlalchemy import func, select

from app.db.models import GoalEntry


def create_goal(client, **overrides):
    payload = {"name": "MacBook", "target_amount_minor": 18_000_000, "currency": "RUB", **overrides}
    r = client.post("/api/v1/goals", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def add_entry(client, goal_id, amount_minor):
    r = client.post(
        f"/api/v1/goals/{goal_id}/entries",
        json={"type": "contribution", "amount_minor": amount_minor, "occurred_at": "2026-09-01T10:00:00Z"},
    )
    assert r.status_code == 201, r.text


def entry_count(db_session, goal_id=None):
    db_session.expire_all()
    stmt = select(func.count(GoalEntry.id))
    if goal_id is not None:
        stmt = stmt.where(GoalEntry.goal_id == goal_id)
    return db_session.scalar(stmt)


def test_delete_goal_removes_its_entries_without_orphans(client, db_session):
    goal = create_goal(client)
    other = create_goal(client, name="Другая")
    add_entry(client, goal["id"], 1_000_000)
    add_entry(client, goal["id"], 500_000)
    add_entry(client, other["id"], 700_000)
    assert client.delete(f"/api/v1/goals/{goal['id']}").status_code == 204
    assert entry_count(db_session, goal["id"]) == 0
    assert entry_count(db_session) == 1
    assert client.get(f"/api/v1/goals/{other['id']}").json()["saved"]["minor"] == 700_000


def test_delete_completed_goal(client, db_session):
    goal = create_goal(client, target_amount_minor=1_000)
    add_entry(client, goal["id"], 1_000)
    assert client.get(f"/api/v1/goals/{goal['id']}").json()["status"] == "completed"
    assert client.delete(f"/api/v1/goals/{goal['id']}").status_code == 204
    assert entry_count(db_session) == 0


def test_delete_archived_goal(client, db_session):
    goal = create_goal(client)
    add_entry(client, goal["id"], 1_000)
    client.patch(f"/api/v1/goals/{goal['id']}", json={"is_archived": True})
    assert client.delete(f"/api/v1/goals/{goal['id']}").status_code == 204
    assert entry_count(db_session) == 0
    assert client.get("/api/v1/goals").json() == []


def test_delete_active_goal_without_entries(client):
    goal = create_goal(client)
    assert client.delete(f"/api/v1/goals/{goal['id']}").status_code == 204
    assert client.get("/api/v1/goals").json() == []


def test_archive_keeps_goal_and_entries(client, db_session):
    goal = create_goal(client)
    add_entry(client, goal["id"], 1_000)
    client.patch(f"/api/v1/goals/{goal['id']}", json={"is_archived": True})
    assert entry_count(db_session, goal["id"]) == 1
    assert client.get(f"/api/v1/goals/{goal['id']}").json()["status"] == "archived"


def test_deleted_goal_is_gone_everywhere(client):
    goal = create_goal(client)
    client.delete(f"/api/v1/goals/{goal['id']}")
    assert client.get(f"/api/v1/goals/{goal['id']}").status_code == 404
    assert client.get(f"/api/v1/goals/{goal['id']}/entries").status_code == 404
    assert client.delete(f"/api/v1/goals/{goal['id']}").status_code == 404
