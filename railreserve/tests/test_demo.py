from fastapi.testclient import TestClient

from app.main import app

TRAIN = "12951"
DAY = "2026-11-01"


def test_demo_reset_and_stats_endpoints():
    client = TestClient(app)
    response = client.post(
        "/api/demo/reset",
        json={"train_id": TRAIN, "journey_date": DAY, "seat_count": 5},
    )
    assert response.status_code == 200

    response = client.get(
        "/api/seats", params={"train_id": TRAIN, "journey_date": DAY}
    )
    assert response.status_code == 200
    assert len(response.json()["seats"]) == 5

    response = client.get(
        "/api/stats", params={"train_id": TRAIN, "journey_date": DAY}
    )
    assert response.status_code == 200
    assert response.json()["available"] == 5
    assert response.json()["naive_winners"] == 0
