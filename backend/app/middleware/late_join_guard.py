import re
from urllib.parse import parse_qs

from app.core.redis import get_redis
from app.schemas.room import RoomStatus
from app.services.realtime import get_realtime_engine

_ROOM_WS_PATH = re.compile(r"^/ws/rooms/(?P<room_id>[A-Za-z0-9_-]+)$")


class LateJoinGuardMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "websocket":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        matched = _ROOM_WS_PATH.match(path)
        if not matched:
            await self.app(scope, receive, send)
            return

        room_id = matched.group("room_id")

        redis = get_redis()
        room_status = await redis.get(f"room:{room_id}:status")

        # Reconnect allowance: if user had an existing session in this room,
        # allow reconnect even when room moved beyond LOBBY.
        query_raw = scope.get("query_string", b"").decode("utf-8")
        query = parse_qs(query_raw)
        user_id = (query.get("user_id") or [""])[0]
        engine = get_realtime_engine()
        is_known_user = bool(user_id and engine.has_session(room_id, user_id))

        if room_status != RoomStatus.LOBBY.value and not is_known_user:
            await send({"type": "websocket.close", "code": 4403})
            return

        await self.app(scope, receive, send)
