import asyncio

import pytest

from app.schemas.room import RoomConfig, RoomStatus
from app.services.room import RoomService
from tests.fake_redis import FakeRedis


def test_room_state_machine_transitions():
    redis = FakeRedis()
    room_service = RoomService(redis)

    room_id = asyncio.run(room_service.create_room(RoomConfig()))
    assert asyncio.run(room_service.get_status(room_id)) == RoomStatus.LOBBY

    status = asyncio.run(room_service.transition_status(room_id, RoomStatus.GENERATING))
    assert status == RoomStatus.GENERATING

    status = asyncio.run(room_service.transition_status(room_id, RoomStatus.ACTIVE))
    assert status == RoomStatus.ACTIVE

    status = asyncio.run(room_service.transition_status(room_id, RoomStatus.FINISHED))
    assert status == RoomStatus.FINISHED


def test_room_state_machine_rejects_invalid_transition():
    redis = FakeRedis()
    room_service = RoomService(redis)

    room_id = asyncio.run(room_service.create_room(RoomConfig()))

    with pytest.raises(ValueError):
        asyncio.run(room_service.transition_status(room_id, RoomStatus.ACTIVE))

