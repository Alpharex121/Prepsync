from fastapi.testclient import TestClient

from app.main import app


def test_register_login_and_profile() -> None:
    client = TestClient(app)

    register_response = client.post(
        "/auth/register",
        json={"username": "alice", "password": "securepass123"},
    )
    assert register_response.status_code == 201
    token = register_response.json()["access_token"]

    login_response = client.post(
        "/auth/login",
        json={"username": "alice", "password": "securepass123"},
    )
    assert login_response.status_code == 200

    me_response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_response.status_code == 200
    assert me_response.json()["username"] == "alice"

