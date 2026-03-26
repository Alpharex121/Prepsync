from fastapi.testclient import TestClient

from app.main import app


def _recv_until(ws, expected_types, max_messages=25):
    for _ in range(max_messages):
        payload = ws.receive_json()
        if payload.get("type") in expected_types:
            return payload
    raise AssertionError(f"Did not receive any of: {expected_types}")


def test_e2e_quiz_mode_flow(fake_redis):
    client = TestClient(app)

    created = client.post(
        "/rooms/create",
        json={
            "config": {
                "mode": "QUIZ",
                "count": 2,
                "time_per_q": 20,
                "time_per_section": 300,
                "topics": ["Averages"],
                "exams": ["SSC"],
            }
        },
    ).json()
    room_id = created["room_id"]

    with client.websocket_connect(f"/ws/rooms/{room_id}?user_id=alice") as ws:
        ws.receive_json()
        ws.send_json({"type": "JOIN_ROOM", "user_id": "alice"})
        _recv_until(ws, {"JOIN_ROOM_ACK"})

        generated = client.post(f"/rooms/{room_id}/generate-questions")
        assert generated.status_code == 200

        question_event = _recv_until(ws, {"NEXT_QUESTION"})
        assert "question_data" in question_event

        ws.send_json(
            {
                "type": "SUBMIT_ANSWER",
                "question_index": question_event["question_index"],
                "selected_option": 0,
            }
        )
        submit_result = _recv_until(ws, {"SUBMIT_ACCEPTED", "SUBMIT_REJECTED"})
        assert submit_result["type"] == "SUBMIT_ACCEPTED"


def test_e2e_test_mode_flow(fake_redis):
    client = TestClient(app)

    created = client.post(
        "/rooms/create",
        json={
            "config": {
                "mode": "TEST",
                "count": 2,
                "time_per_q": 20,
                "time_per_section": 600,
                "topics": ["Averages", "Work and Time"],
                "exams": ["GATE", "SSC"],
            }
        },
    ).json()
    room_id = created["room_id"]

    with client.websocket_connect(f"/ws/rooms/{room_id}?user_id=alice") as ws:
        ws.receive_json()
        ws.send_json({"type": "JOIN_ROOM", "user_id": "alice"})
        _recv_until(ws, {"JOIN_ROOM_ACK"})

        generated = client.post(f"/rooms/{room_id}/generate-questions")
        assert generated.status_code == 200

        section_event = _recv_until(ws, {"TEST_SECTION_START"})
        assert section_event["section_question_count"] >= 1

        first_question_index = section_event["questions"][0]["question_index"]
        ws.send_json({"type": "NAVIGATE_QUESTION", "question_index": first_question_index})
        nav = _recv_until(ws, {"QUESTION_NAVIGATED", "NAVIGATION_REJECTED"})
        assert nav["type"] == "QUESTION_NAVIGATED"

        ws.send_json(
            {
                "type": "SUBMIT_ANSWER",
                "question_index": first_question_index,
                "selected_option": 0,
            }
        )
        submit_result = _recv_until(ws, {"SUBMIT_ACCEPTED", "SUBMIT_REJECTED"})
        assert submit_result["type"] == "SUBMIT_ACCEPTED"

        ws.send_json({"type": "SUBMIT_SECTION", "section_index": section_event["section_index"]})
        section_submit = _recv_until(ws, {"SECTION_SUBMIT_ACCEPTED", "SECTION_SUBMIT_REJECTED"})
        assert section_submit["type"] == "SECTION_SUBMIT_ACCEPTED"

