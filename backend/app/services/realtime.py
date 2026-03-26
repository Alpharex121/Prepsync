import asyncio
import contextlib
import time
from dataclasses import dataclass, field

from fastapi import WebSocket

from app.schemas.room import RoomMode, RoomStatus
from app.services.room import get_room_service

SUBMISSION_GRACE_MS = 2000
STALE_SESSION_TTL_SECONDS = 45
CORRECT_ANSWER_POINTS = 10.0


@dataclass
class UserSession:
    user_id: str
    websocket: WebSocket
    connected: bool
    last_seen: float


@dataclass
class TestUserState:
    test_ends_at: int
    current_section: int = 0
    locked_sections: set[int] = field(default_factory=set)
    finished: bool = False
    answers: dict[int, int] = field(default_factory=dict)


class RealtimeEngine:
    def __init__(self) -> None:
        self._room_sessions: dict[str, dict[str, UserSession]] = {}
        self._room_submissions: dict[str, set[str]] = {}
        self._room_participants: dict[str, set[str]] = {}
        self._test_room_sections: dict[str, list[dict]] = {}
        self._test_user_state: dict[str, dict[str, TestUserState]] = {}
        self._room_finalized: set[str] = set()
        self._cleanup_task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        if self._cleanup_task is None:
            return
        self._cleanup_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._cleanup_task
        self._cleanup_task = None

    def has_session(self, room_id: str, user_id: str) -> bool:
        sessions = self._room_sessions.get(room_id, {})
        return user_id in sessions

    def get_participants(self, room_id: str) -> list[str]:
        return sorted(self._room_participants.get(room_id, set()))

    def get_user_rooms(self, user_id: str) -> list[str]:
        user_rooms: set[str] = set()
        for room_id, participants in self._room_participants.items():
            if user_id in participants:
                user_rooms.add(room_id)
        for room_id, sessions in self._room_sessions.items():
            if user_id in sessions:
                user_rooms.add(room_id)
        return sorted(user_rooms)

    async def connect(self, room_id: str, user_id: str, websocket: WebSocket) -> None:
        sessions = self._room_sessions.setdefault(room_id, {})

        previous = sessions.get(user_id)
        if previous and previous.connected and previous.websocket is not websocket:
            with contextlib.suppress(Exception):
                await previous.websocket.close(code=4001)

        sessions[user_id] = UserSession(
            user_id=user_id,
            websocket=websocket,
            connected=True,
            last_seen=time.time(),
        )
        self._room_participants.setdefault(room_id, set()).add(user_id)

    async def disconnect(self, room_id: str, user_id: str) -> None:
        sessions = self._room_sessions.get(room_id)
        if not sessions or user_id not in sessions:
            return

        session = sessions[user_id]
        session.connected = False
        session.last_seen = time.time()

        participants = self._room_participants.get(room_id)
        if participants is not None:
            participants.discard(user_id)

    async def touch(self, room_id: str, user_id: str) -> None:
        sessions = self._room_sessions.get(room_id)
        if not sessions:
            return
        session = sessions.get(user_id)
        if not session:
            return

        session.last_seen = time.time()
        session.connected = True

    async def send_to_user(self, room_id: str, user_id: str, event: dict) -> None:
        sessions = self._room_sessions.get(room_id, {})
        session = sessions.get(user_id)
        if not session or not session.connected:
            return

        try:
            await session.websocket.send_json(event)
        except Exception:
            session.connected = False
            session.last_seen = time.time()

    async def broadcast(self, room_id: str, event: dict) -> None:
        sessions = self._room_sessions.get(room_id, {})
        to_drop: list[str] = []

        for user_id, session in sessions.items():
            if not session.connected:
                continue
            try:
                await session.websocket.send_json(event)
            except Exception:
                to_drop.append(user_id)

        for user_id in to_drop:
            sessions[user_id].connected = False
            sessions[user_id].last_seen = time.time()

    async def handle_join_room(self, room_id: str, user_id: str) -> dict:
        room_service = await get_room_service()
        status = await room_service.get_status(room_id)
        runtime = await room_service.get_runtime(room_id)

        if status is None:
            return {"type": "ERROR", "detail": "Room not found"}

        config = await room_service.get_config(room_id)
        payload = {
            "type": "JOIN_ROOM_ACK",
            "room_id": room_id,
            "status": status.value,
            "ends_at": runtime["ends_at"],
            "total_questions": await room_service.get_question_count(room_id),
            "test_ends_at": runtime["test_ends_at"],
            "current_question": runtime["current_question"],
            "user_id": user_id,
            "participants": self.get_participants(room_id),
            "owner_id": config.owner_id,

        }
        if status == RoomStatus.ACTIVE and config.mode == RoomMode.QUIZ:
            question = await room_service.get_question(room_id, runtime["current_question"])
            payload["question_data"] = self._sanitize_question(question)

        if status == RoomStatus.ACTIVE and config.mode == RoomMode.TEST:
            await self._ensure_test_sections(room_id, config.topics)
            user_state = self._ensure_test_user_state(room_id, user_id, len(self._test_room_sections.get(room_id, [])), config.time_per_section)
            section_payload = await self._build_test_section_payload(room_id, user_state)
            payload.update(section_payload)

        return payload

    async def handle_room_state_change(self, room_id: str, actor_user_id: str, status_value: str) -> dict:
        room_service = await get_room_service()
        owner_id = await room_service.get_owner_id(room_id)
        if owner_id and owner_id != actor_user_id:
            raise ValueError("Only room admin can start or transition")

        new_status = await room_service.transition_status(room_id, RoomStatus(status_value))

        timing = {"ends_at": 0, "test_ends_at": 0, "current_question": 0}
        if new_status == RoomStatus.ACTIVE:
            timing = await room_service.activate_session(room_id)
            self._room_submissions[room_id] = set()
            self._room_finalized.discard(room_id)

        event = {
            "type": "ROOM_STATE_CHANGE",
            "status": new_status.value,
            "ends_at": timing["ends_at"],
            "test_ends_at": timing["test_ends_at"],
            "current_question": timing["current_question"],
        }
        await self.broadcast(room_id, event)

        config = await room_service.get_config(room_id)
        if new_status == RoomStatus.ACTIVE and config.mode == RoomMode.QUIZ:
            await self.publish_current_question(room_id)

        if new_status == RoomStatus.ACTIVE and config.mode == RoomMode.TEST:
            await self._ensure_test_sections(room_id, config.topics)

        return event

    async def publish_current_question(self, room_id: str) -> dict:
        room_service = await get_room_service()
        runtime = await room_service.get_runtime(room_id)
        question_index = runtime["current_question"]
        question = await room_service.get_question(room_id, question_index)

        event = {
            "type": "NEXT_QUESTION",
            "room_id": room_id,
            "question_index": question_index,
            "question_data": self._sanitize_question(question),
            "ends_at": runtime["ends_at"],
            "total_questions": await room_service.get_question_count(room_id),
        }
        await self.broadcast(room_id, event)
        return event

    async def handle_submit_answer(
        self,
        room_id: str,
        user_id: str,
        question_index: int,
        selected_option: int,
    ) -> dict:
        room_service = await get_room_service()
        status = await room_service.get_status(room_id)
        if status != RoomStatus.ACTIVE:
            return {"type": "SUBMIT_REJECTED", "detail": "Room is not active"}

        config = await room_service.get_config(room_id)
        runtime = await room_service.get_runtime(room_id)

        now_ms = int(time.time() * 1000)
        current_question = runtime["current_question"]

        if config.mode == RoomMode.QUIZ:
            if question_index != current_question:
                return {"type": "SUBMIT_REJECTED", "detail": "Question is no longer active"}

            submissions = self._room_submissions.setdefault(room_id, set())
            if user_id in submissions:
                return {"type": "SUBMIT_REJECTED", "detail": "Answer already submitted"}

            ends_at = runtime["ends_at"]
            if now_ms > (ends_at + SUBMISSION_GRACE_MS):
                return {
                    "type": "SUBMIT_REJECTED",
                    "detail": "Submission window expired",
                    "accepted_until": ends_at + SUBMISSION_GRACE_MS,
                }

            question = await room_service.get_question(room_id, current_question)
            if question is None:
                return {"type": "SUBMIT_REJECTED", "detail": "Question not found"}

            is_correct = int(question.get("correct_index", -1)) == selected_option
            updated_score = None
            if is_correct:
                updated_score = await room_service.increment_score(
                    room_id,
                    user_id,
                    CORRECT_ANSWER_POINTS,
                )

            submissions.add(user_id)

            await self.broadcast(
                room_id,
                {
                    "type": "SUBMIT_ANSWER_ACK",
                    "room_id": room_id,
                    "user_id": user_id,
                    "question_index": question_index,
                    "selected_option": selected_option,
                    "submitted_at": now_ms,
                },
            )
            active_count = self._active_session_count(room_id)
            if active_count > 0 and len(submissions) >= active_count:
                await self._advance_quiz_question(room_id)

            return {
                "type": "SUBMIT_ACCEPTED",
                "submitted_at": now_ms,
                "question_index": question_index,
                "is_correct": is_correct,
                "score": updated_score,
            }

        # TEST mode flow
        await self._ensure_test_sections(room_id, config.topics)
        user_state = self._ensure_test_user_state(room_id, user_id, len(self._test_room_sections.get(room_id, [])), config.time_per_section)

        if user_state.finished:
            return {"type": "SUBMIT_REJECTED", "detail": "Test already finished"}

        if now_ms > user_state.test_ends_at:
            return {"type": "SUBMIT_REJECTED", "detail": "User test timer expired"}

        sections = self._test_room_sections.get(room_id, [])
        if user_state.current_section >= len(sections):
            return {"type": "SUBMIT_REJECTED", "detail": "Invalid current section"}

        allowed_indices = set(sections[user_state.current_section]["question_indices"])
        if question_index not in allowed_indices:
            return {"type": "SUBMIT_REJECTED", "detail": "Question not in active section"}

        if question_index in user_state.answers:
            return {"type": "SUBMIT_REJECTED", "detail": "Answer already submitted"}

        question = await room_service.get_question(room_id, question_index)
        if question is None:
            return {"type": "SUBMIT_REJECTED", "detail": "Question not found"}

        is_correct = int(question.get("correct_index", -1)) == selected_option
        updated_score = None
        if is_correct:
            updated_score = await room_service.increment_score(room_id, user_id, CORRECT_ANSWER_POINTS)

        user_state.answers[question_index] = selected_option

        await self.broadcast(
            room_id,
            {
                "type": "SUBMIT_ANSWER_ACK",
                "room_id": room_id,
                "user_id": user_id,
                "question_index": question_index,
                "selected_option": selected_option,
                "submitted_at": now_ms,
            },
        )
        return {
            "type": "SUBMIT_ACCEPTED",
            "submitted_at": now_ms,
            "question_index": question_index,
                "is_correct": is_correct,
            "score": updated_score,
            "test_ends_at": user_state.test_ends_at,
            "current_section": user_state.current_section,
        }

    async def handle_navigate_question(self, room_id: str, user_id: str, question_index: int) -> dict:
        room_service = await get_room_service()
        config = await room_service.get_config(room_id)
        if config.mode != RoomMode.TEST:
            return {"type": "NAVIGATION_REJECTED", "detail": "Navigation is only for TEST mode"}

        await self._ensure_test_sections(room_id, config.topics)
        user_state = self._ensure_test_user_state(room_id, user_id, len(self._test_room_sections.get(room_id, [])), config.time_per_section)
        sections = self._test_room_sections.get(room_id, [])

        if user_state.current_section >= len(sections):
            return {"type": "NAVIGATION_REJECTED", "detail": "Invalid current section"}

        allowed_indices = set(sections[user_state.current_section]["question_indices"])
        if question_index not in allowed_indices:
            return {"type": "NAVIGATION_REJECTED", "detail": "Question not in active section"}

        question = await room_service.get_question(room_id, question_index)
        return {
            "type": "QUESTION_NAVIGATED",
            "room_id": room_id,
            "question_index": question_index,
            "question_data": self._sanitize_question(question),
            "section_index": user_state.current_section,
            "test_ends_at": user_state.test_ends_at,
        }

    async def handle_submit_section(self, room_id: str, user_id: str, section_index: int) -> dict:
        room_service = await get_room_service()
        config = await room_service.get_config(room_id)
        if config.mode != RoomMode.TEST:
            return {"type": "SECTION_SUBMIT_REJECTED", "detail": "Only valid in TEST mode"}

        await self._ensure_test_sections(room_id, config.topics)
        user_state = self._ensure_test_user_state(room_id, user_id, len(self._test_room_sections.get(room_id, [])), config.time_per_section)

        if user_state.finished:
            return {"type": "SECTION_SUBMIT_REJECTED", "detail": "Test already finished"}

        if section_index != user_state.current_section:
            return {"type": "SECTION_SUBMIT_REJECTED", "detail": "Can only submit current section"}

        user_state.locked_sections.add(section_index)
        sections = self._test_room_sections.get(room_id, [])

        if user_state.current_section >= len(sections) - 1:
            user_state.finished = True
            await self.broadcast(
                room_id,
                {"type": "USER_FINISHED_TEST", "room_id": room_id, "user_id": user_id},
            )
            return {
                "type": "SECTION_SUBMIT_ACCEPTED",
                "room_id": room_id,
                "user_id": user_id,
                "finished": True,
            }

        user_state.current_section += 1
        payload = await self._build_test_section_payload(room_id, user_state)
        await self.send_to_user(room_id, user_id, payload)
        return {
            "type": "SECTION_SUBMIT_ACCEPTED",
            "room_id": room_id,
            "user_id": user_id,
            "finished": False,
            "current_section": user_state.current_section,
        }

    async def publish_test_sections(self, room_id: str) -> None:
        room_service = await get_room_service()
        config = await room_service.get_config(room_id)
        await self._ensure_test_sections(room_id, config.topics)

        participants = self._room_participants.get(room_id, set())
        for user_id in participants:
            state = self._ensure_test_user_state(room_id, user_id, len(self._test_room_sections.get(room_id, [])), config.time_per_section)
            payload = await self._build_test_section_payload(room_id, state)
            await self.send_to_user(room_id, user_id, payload)
    async def finalize_results(self, room_id: str) -> dict:
        if room_id in self._room_finalized:
            return {"type": "FINAL_RESULTS", "room_id": room_id, "leaderboard": []}

        room_service = await get_room_service()
        status = await room_service.get_status(room_id)
        if status == RoomStatus.ACTIVE:
            await room_service.transition_status(room_id, RoomStatus.FINISHED)

        leaderboard = await room_service.get_leaderboard(room_id)
        event = {"type": "FINAL_RESULTS", "room_id": room_id, "leaderboard": leaderboard}
        await self.broadcast(room_id, event)

        self._room_finalized.add(room_id)
        self._room_submissions.pop(room_id, None)
        self._test_user_state.pop(room_id, None)
        self._test_room_sections.pop(room_id, None)

        return event

    async def _advance_quiz_question(self, room_id: str) -> dict:
        room_service = await get_room_service()
        config = await room_service.get_config(room_id)
        runtime = await room_service.get_runtime(room_id)

        next_question = runtime["current_question"] + 1
        total_questions = await room_service.get_question_count(room_id)
        max_questions = total_questions

        if next_question >= max_questions:
            return await self.finalize_results(room_id)

        ends_at = int(time.time() * 1000) + (config.time_per_q * 1000)
        await room_service.set_runtime(room_id, current_question=next_question, ends_at=ends_at)
        self._room_submissions[room_id] = set()

        question = await room_service.get_question(room_id, next_question)
        event = {
            "type": "NEXT_QUESTION",
            "room_id": room_id,
            "question_index": next_question,
            "question_data": self._sanitize_question(question),
            "ends_at": ends_at,
            "total_questions": total_questions,
        }
        await self.broadcast(room_id, event)
        return event

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(1)
            now = time.time()
            now_ms = int(now * 1000)

            await self._handle_quiz_timeouts(now_ms)
            await self._handle_test_finalization(now_ms)

            empty_rooms: list[str] = []
            for room_id, sessions in self._room_sessions.items():
                stale_users = [
                    user_id
                    for user_id, session in sessions.items()
                    if (not session.connected)
                    and ((now - session.last_seen) > STALE_SESSION_TTL_SECONDS)
                ]
                for user_id in stale_users:
                    sessions.pop(user_id, None)
                    participants = self._room_participants.get(room_id)
                    if participants is not None:
                        participants.discard(user_id)

                if not sessions:
                    empty_rooms.append(room_id)

            for room_id in empty_rooms:
                self._room_sessions.pop(room_id, None)
                self._room_submissions.pop(room_id, None)
                self._room_participants.pop(room_id, None)

    async def _handle_quiz_timeouts(self, now_ms: int) -> None:
        room_service = await get_room_service()
        for room_id in list(self._room_sessions.keys()):
            status = await room_service.get_status(room_id)
            if status != RoomStatus.ACTIVE:
                continue

            config = await room_service.get_config(room_id)
            if config.mode != RoomMode.QUIZ:
                continue

            runtime = await room_service.get_runtime(room_id)
            if self._active_session_count(room_id) <= 0:
                continue

            ends_at = runtime["ends_at"]
            if ends_at <= 0:
                continue

            if now_ms > (ends_at + SUBMISSION_GRACE_MS):
                await self._advance_quiz_question(room_id)

    async def _handle_test_finalization(self, now_ms: int) -> None:
        room_service = await get_room_service()

        for room_id in list(self._room_participants.keys()):
            if room_id in self._room_finalized:
                continue

            status = await room_service.get_status(room_id)
            if status != RoomStatus.ACTIVE:
                continue

            config = await room_service.get_config(room_id)
            if config.mode != RoomMode.TEST:
                continue

            participants = self._room_participants.get(room_id, set())
            if not participants:
                continue

            states = self._test_user_state.get(room_id, {})
            if not states:
                continue

            all_finished = True
            all_timed_out = True
            for user_id in participants:
                state = states.get(user_id)
                if state is None:
                    all_finished = False
                    all_timed_out = False
                    break

                if not state.finished:
                    all_finished = False
                if now_ms <= state.test_ends_at:
                    all_timed_out = False

            if all_finished or all_timed_out:
                await self.finalize_results(room_id)

    async def _ensure_test_sections(self, room_id: str, ordered_topics: list[str]) -> None:
        if room_id in self._test_room_sections:
            return

        room_service = await get_room_service()
        questions = await room_service.get_all_questions(room_id)

        topic_to_indices: dict[str, list[int]] = {}
        for index, question in enumerate(questions):
            topic = str(question.get("topic", "General")).strip() or "General"
            topic_to_indices.setdefault(topic, []).append(index)

        sections: list[dict] = []
        for topic in ordered_topics:
            topic_key = topic.strip()
            if topic_key in topic_to_indices:
                sections.append({"topic": topic_key, "question_indices": topic_to_indices.pop(topic_key)})

        for topic, indices in topic_to_indices.items():
            sections.append({"topic": topic, "question_indices": indices})

        self._test_room_sections[room_id] = sections

    def _ensure_test_user_state(self, room_id: str, user_id: str, section_count: int, time_per_section_seconds: int) -> TestUserState:
        room_states = self._test_user_state.setdefault(room_id, {})
        if user_id in room_states:
            return room_states[user_id]

        now_ms = int(time.time() * 1000)
        room_states[user_id] = TestUserState(test_ends_at=now_ms + (max(1, section_count) * time_per_section_seconds * 1000))
        return room_states[user_id]

    async def _build_test_section_payload(self, room_id: str, state: TestUserState) -> dict:
        room_service = await get_room_service()
        sections = self._test_room_sections.get(room_id, [])
        if not sections:
            return {"type": "TEST_SECTION_START", "section_index": 0, "questions": []}

        section = sections[state.current_section]
        question_indices = section["question_indices"]
        questions: list[dict] = []
        for index in question_indices:
            question = await room_service.get_question(room_id, index)
            q_payload = self._sanitize_question(question)
            q_payload["question_index"] = index
            questions.append(q_payload)

        return {
            "type": "TEST_SECTION_START",
            "room_id": room_id,
            "section_index": state.current_section,
            "section_topic": section["topic"],
            "section_question_count": len(question_indices),
            "total_sections": len(sections),
            "test_ends_at": state.test_ends_at,
            "locked_sections": sorted(list(state.locked_sections)),
            "questions": questions,
        }

    def _sanitize_question(self, question: dict | None) -> dict:
        if not question:
            return {}
        return {
            "text": question.get("text"),
            "options": question.get("options", []),
            "difficulty": question.get("difficulty"),
            "topic": question.get("topic"),
        }

    def _active_session_count(self, room_id: str) -> int:
        sessions = self._room_sessions.get(room_id, {})
        return sum(1 for session in sessions.values() if session.connected)


_engine: RealtimeEngine | None = None


def get_realtime_engine() -> RealtimeEngine:
    global _engine
    if _engine is None:
        _engine = RealtimeEngine()
    return _engine



















