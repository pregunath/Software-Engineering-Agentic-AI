from fastapi.testclient import TestClient

from app.main import app


def test_plan_requires_approval_before_execution() -> None:
    with TestClient(app) as client:
        task = client.post(
            "/tasks", json={"title": "Plan task", "description": "Approve a plan."}
        ).json()
        plan = client.post(
            f"/tasks/{task['id']}/plan",
            json={
                "summary": "Update parser behavior",
                "content": "Inspect parser and update the focused test.",
                "proposed_diff": "--- a/parser.py\n+++ b/parser.py",
            },
        )
        before = client.get(f"/tasks/{task['id']}")
        approved = client.post(f"/tasks/{task['id']}/plan/approve")
        events = client.get(f"/tasks/{task['id']}/events").json()

    assert plan.status_code == 201
    assert plan.json()["status"] == "awaiting_approval"
    assert before.status_code == 404
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert any(event["type"] == "plan.approved" for event in events)
