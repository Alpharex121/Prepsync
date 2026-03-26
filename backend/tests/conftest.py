import pytest

from app.services import history
from app.services.realtime import get_realtime_engine
from tests.fake_redis import FakeRedis


@pytest.fixture()
def fake_redis(monkeypatch):
    redis = FakeRedis()

    monkeypatch.setattr("app.core.redis.get_redis", lambda: redis)
    monkeypatch.setattr("app.services.room.get_redis", lambda: redis)
    monkeypatch.setattr("app.middleware.late_join_guard.get_redis", lambda: redis)

    engine = get_realtime_engine()
    engine._room_sessions.clear()
    engine._room_submissions.clear()
    engine._room_participants.clear()
    engine._test_room_sections.clear()
    engine._test_user_state.clear()
    engine._room_finalized.clear()

    history.history_service._sessions.clear()
    history.history_service._attempts.clear()

    return redis

