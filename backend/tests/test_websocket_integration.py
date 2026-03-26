from fastapi.testclient import TestClient

from app.main import app


def _recv_until(ws, expected_types, max_messages=12):
    for _ in range(max_messages):
        payload = ws.receive_json()
        if payload.get("type") in expected_types:
            return payload
    raise AssertionError(f"Did not receive any of: {expected_types}")


def test_websocket_event_validation_and_join(fake_redis):
    client = TestClient(app)

    created = client.post(
        "/rooms/create",
        json={
            "config": {
                "mode": "QUIZ",
                "count": 3,
                "time_per_q": 30,
                "time_per_section": 300,
                "topics": ["Averages"],
                "exams": ["GATE"],
            }
        },
    ).json()
    room_id = created["room_id"]

    with client.websocket_connect(f"/ws/rooms/{room_id}?user_id=alice") as ws:
        connected = ws.receive_json()
        assert connected["type"] in {"CONNECTED", "RECONNECTED"}

        ws.send_json({"type": "SUBMIT_ANSWER", "question_index": 0, "selected_option": 1})
        err = ws.receive_json()
        assert err["type"] == "ERROR"

        ws.send_json({"type": "JOIN_ROOM", "user_id": "alice"})
        join_ack = _recv_until(ws, {"JOIN_ROOM_ACK"})
        assert join_ack["room_id"] == room_id

        ws.send_json({"type": "SUBMIT_ANSWER", "question_index": -99, "selected_option": 1})
        invalid_payload = ws.receive_json()
        assert invalid_payload["type"] == "ERROR"

