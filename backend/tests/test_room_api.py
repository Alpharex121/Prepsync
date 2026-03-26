from fastapi.testclient import TestClient

from app.main import app
from app.schemas.room import RoomConfig, RoomStatus
from app.services.room import get_room_service


class FakeRoomService:
    def __init__(self) -> None:
        self.status_by_room: dict[str, RoomStatus] = {}

    async def create_room(self, config: RoomConfig) -> str:  # noqa: ARG002
        room_id = "room123"
        self.status_by_room[room_id] = RoomStatus.LOBBY
        return room_id

    async def get_status(self, room_id: str) -> RoomStatus | None:
        return self.status_by_room.get(room_id)

    async def transition_status(self, room_id: str, target_status: RoomStatus) -> RoomStatus:
        current = self.status_by_room.get(room_id)
        if current is None:
            raise ValueError("Room not found")

        allowed = {
            RoomStatus.LOBBY: {RoomStatus.GENERATING},
            RoomStatus.GENERATING: {RoomStatus.ACTIVE},
            RoomStatus.ACTIVE: {RoomStatus.FINISHED},
            RoomStatus.FINISHED: set(),
        }

        if target_status not in allowed[current]:
            raise ValueError(f"Invalid transition: {current.value} -> {target_status.value}")

        self.status_by_room[room_id] = target_status
        return target_status


def test_create_join_check_and_transition() -> None:
    fake_service = FakeRoomService()

    async def override_room_service() -> FakeRoomService:
        return fake_service

    app.dependency_overrides[get_room_service] = override_room_service
    client = TestClient(app)

    create_response = client.post("/rooms/create", json={"config": {"mode": "QUIZ"}})
    assert create_response.status_code == 201
    room_id = create_response.json()["room_id"]

    join_response = client.get(f"/rooms/{room_id}/join-check")
    assert join_response.status_code == 200
    assert join_response.json()["can_join"] is True

    transition_response = client.post(
        f"/rooms/{room_id}/transition",
        json={"status": "GENERATING"},
    )
    assert transition_response.status_code == 200
    assert transition_response.json()["status"] == "GENERATING"

    join_response_after_transition = client.get(f"/rooms/{room_id}/join-check")
    assert join_response_after_transition.status_code == 200
    assert join_response_after_transition.json()["can_join"] is False

    app.dependency_overrides.clear()

