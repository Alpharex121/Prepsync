import json
import time
from uuid import uuid4

from redis.asyncio import Redis

from app.core.redis import get_redis
from app.schemas.quiz import QuizPackage
from app.schemas.room import RoomConfig, RoomMode, RoomStatus

_ALLOWED_TRANSITIONS: dict[RoomStatus, set[RoomStatus]] = {
    RoomStatus.LOBBY: {RoomStatus.GENERATING},
    RoomStatus.GENERATING: {RoomStatus.ACTIVE},
    RoomStatus.ACTIVE: {RoomStatus.FINISHED},
    RoomStatus.FINISHED: set(),
}


def _status_key(room_id: str) -> str:
    return f"room:{room_id}:status"


def _config_key(room_id: str) -> str:
    return f"room:{room_id}:config"


def _questions_key(room_id: str) -> str:
    return f"room:{room_id}:questions"


def _leaderboard_key(room_id: str) -> str:
    return f"room:{room_id}:leaderboard"


def _runtime_key(room_id: str) -> str:
    return f"room:{room_id}:runtime"


class RoomService:
    def __init__(self, redis: Redis):
        self.redis = redis

    async def create_room(self, config: RoomConfig) -> str:
        room_id = uuid4().hex[:10]

        await self.redis.set(_status_key(room_id), RoomStatus.LOBBY.value)
        await self.redis.hset(
            _config_key(room_id),
            mapping={
                "owner_id": config.owner_id,
                "mode": config.mode.value,
                "count": str(config.count),
                "time_per_q": str(config.time_per_q),
                "time_per_section": str(config.time_per_section),
                "difficulty": config.difficulty.value,
                "exams": json.dumps(config.exams),
                "topics": json.dumps(config.topics),
            },
        )

        await self.redis.delete(_questions_key(room_id))
        await self.redis.zadd(_leaderboard_key(room_id), {"_bootstrap": 0.0})
        await self.redis.zrem(_leaderboard_key(room_id), "_bootstrap")
        await self.redis.hset(
            _runtime_key(room_id),
            mapping={
                "current_question": "0",
                "ends_at": "0",
                "test_ends_at": "0",
            },
        )

        return room_id

    async def save_question_package(self, room_id: str, package: QuizPackage) -> None:
        key = _questions_key(room_id)
        await self.redis.delete(key)

        payloads = [json.dumps(question.model_dump(mode="json")) for question in package.questions]
        if payloads:
            await self.redis.rpush(key, *payloads)

    async def get_all_questions(self, room_id: str) -> list[dict]:
        raws = await self.redis.lrange(_questions_key(room_id), 0, -1)
        return [json.loads(raw) for raw in raws]

    async def get_question(self, room_id: str, question_index: int) -> dict | None:
        raw = await self.redis.lindex(_questions_key(room_id), question_index)
        if raw is None:
            return None
        return json.loads(raw)

    async def get_question_count(self, room_id: str) -> int:
        return int(await self.redis.llen(_questions_key(room_id)))

    async def increment_score(self, room_id: str, user_id: str, delta: float) -> float:
        return float(await self.redis.zincrby(_leaderboard_key(room_id), delta, user_id))

    async def get_leaderboard(self, room_id: str, limit: int = 20) -> list[dict]:
        rows = await self.redis.zrevrange(_leaderboard_key(room_id), 0, limit - 1, withscores=True)
        return [{"user_id": user_id, "score": float(score)} for user_id, score in rows]

    async def get_status(self, room_id: str) -> RoomStatus | None:
        value = await self.redis.get(_status_key(room_id))
        if value is None:
            return None
        return RoomStatus(value)

    async def get_config(self, room_id: str) -> RoomConfig:
        data = await self.redis.hgetall(_config_key(room_id))
        if not data:
            raise ValueError("Room not found")

        return RoomConfig(
            owner_id=data.get("owner_id", ""),
            mode=RoomMode(data["mode"]),
            count=int(data["count"]),
            time_per_q=int(data.get("time_per_q", "60")),
            time_per_section=int(data.get("time_per_section", "300")),
            difficulty=data.get("difficulty", "medium"),
            exams=json.loads(data.get("exams", "[]")),
            topics=json.loads(data.get("topics", "[]")),
        )

    async def get_owner_id(self, room_id: str) -> str:
        data = await self.redis.hgetall(_config_key(room_id))
        if not data:
            raise ValueError("Room not found")
        return str(data.get("owner_id", ""))

    async def get_runtime(self, room_id: str) -> dict[str, int]:
        data = await self.redis.hgetall(_runtime_key(room_id))
        if not data:
            return {"current_question": 0, "ends_at": 0, "test_ends_at": 0}

        return {
            "current_question": int(data.get("current_question", "0")),
            "ends_at": int(data.get("ends_at", "0")),
            "test_ends_at": int(data.get("test_ends_at", "0")),
        }

    async def set_runtime(
        self,
        room_id: str,
        *,
        current_question: int | None = None,
        ends_at: int | None = None,
        test_ends_at: int | None = None,
    ) -> None:
        mapping: dict[str, str] = {}
        if current_question is not None:
            mapping["current_question"] = str(current_question)
        if ends_at is not None:
            mapping["ends_at"] = str(ends_at)
        if test_ends_at is not None:
            mapping["test_ends_at"] = str(test_ends_at)

        if mapping:
            await self.redis.hset(_runtime_key(room_id), mapping=mapping)

    async def can_join(self, room_id: str) -> bool:
        status = await self.get_status(room_id)
        return status == RoomStatus.LOBBY

    async def transition_status(self, room_id: str, target_status: RoomStatus) -> RoomStatus:
        current_status = await self.get_status(room_id)
        if current_status is None:
            raise ValueError("Room not found")

        allowed_targets = _ALLOWED_TRANSITIONS[current_status]
        if target_status not in allowed_targets:
            raise ValueError(
                f"Invalid transition: {current_status.value} -> {target_status.value}"
            )

        await self.redis.set(_status_key(room_id), target_status.value)
        return target_status

    async def activate_session(self, room_id: str) -> dict[str, int]:
        config = await self.get_config(room_id)
        now_ms = int(time.time() * 1000)

        if config.mode == RoomMode.QUIZ:
            ends_at = now_ms + (config.time_per_q * 1000)
            await self.set_runtime(room_id, current_question=0, ends_at=ends_at, test_ends_at=0)
            return {"ends_at": ends_at, "test_ends_at": 0, "current_question": 0}

        section_count = max(1, len(config.topics))
        test_ends_at = now_ms + (config.time_per_section * section_count * 1000)
        await self.set_runtime(room_id, current_question=0, ends_at=0, test_ends_at=test_ends_at)
        return {"ends_at": 0, "test_ends_at": test_ends_at, "current_question": 0}


async def get_room_service() -> RoomService:
    redis = get_redis()
    return RoomService(redis)
