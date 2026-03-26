import json
from collections import defaultdict
from datetime import UTC, datetime

import psycopg

from app.core.config import settings
from app.schemas.history import AttemptItem, AttemptReport, HistoryListItem, RoomAnalytics, SectionInsight
from app.schemas.quiz import QuizPackage
from app.schemas.room import RoomConfig


class HistoryService:
    def __init__(self) -> None:
        self._sessions: dict[str, dict] = {}
        self._attempts: list[dict] = []

    def persist_quiz_history(self, room_id: str, config: RoomConfig, package: QuizPackage) -> None:
        created_at = datetime.now(UTC).isoformat()
        self._sessions[room_id] = {
            "room_id": room_id,
            "mode": config.mode.value,
            "config": config.model_dump(mode="json"),
            "questions": package.model_dump(mode="json")["questions"],
            "created_at": created_at,
        }

        try:
            with psycopg.connect(settings.postgres_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS quiz_history (
                            id SERIAL PRIMARY KEY,
                            room_id TEXT NOT NULL,
                            mode TEXT NOT NULL,
                            config_params JSONB NOT NULL,
                            question_package JSONB NOT NULL,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                        """
                    )
                    cursor.execute(
                        """
                        INSERT INTO quiz_history (room_id, mode, config_params, question_package)
                        VALUES (%s, %s, %s::jsonb, %s::jsonb)
                        """,
                        (
                            room_id,
                            config.mode.value,
                            json.dumps(config.model_dump(mode="json")),
                            json.dumps(package.model_dump(mode="json")),
                        ),
                    )
                connection.commit()
        except Exception:
            return

    def record_attempt_submission(
        self,
        *,
        room_id: str,
        user_id: str,
        question_index: int,
        selected_option: int,
        time_taken_ms: int,
    ) -> bool:
        session = self._sessions.get(room_id)
        if not session:
            return False

        questions = session["questions"]
        if question_index < 0 or question_index >= len(questions):
            return False

        for item in self._attempts:
            if (
                item["room_id"] == room_id
                and item["user_id"] == user_id
                and item["question_index"] == question_index
            ):
                return True

        question = questions[question_index]
        correct_index = int(question.get("correct_index", -1))
        topic = str(question.get("topic", "General"))

        self._attempts.append(
            {
                "room_id": room_id,
                "user_id": user_id,
                "question_index": question_index,
                "selected_option": selected_option,
                "is_correct": selected_option == correct_index,
                "time_taken_ms": max(0, int(time_taken_ms)),
                "topic": topic,
                "created_at": datetime.now(UTC).isoformat(),
            }
        )
        return True

    def list_history(
        self,
        *,
        mode: str | None,
        date_from: str | None,
        date_to: str | None,
        topic: str | None,
        exam: str | None,
    ) -> list[HistoryListItem]:
        items: list[HistoryListItem] = []
        for session in self._sessions.values():
            if mode and session["mode"].upper() != mode.upper():
                continue

            created = session["created_at"]
            if date_from and created < date_from:
                continue
            if date_to and created > date_to:
                continue

            topics = session["config"].get("topics", [])
            exams = session["config"].get("exams", [])
            if topic and topic not in topics:
                continue
            if exam and exam not in exams:
                continue

            items.append(
                HistoryListItem(
                    room_id=session["room_id"],
                    mode=session["mode"],
                    topics=topics,
                    exams=exams,
                    created_at=created,
                )
            )

        items.sort(key=lambda item: item.created_at, reverse=True)
        return items

    def get_attempt_report(self, *, room_id: str, user_id: str) -> AttemptReport | None:
        session = self._sessions.get(room_id)
        if not session:
            return None

        attempts_map = {
            item["question_index"]: item
            for item in self._attempts
            if item["room_id"] == room_id and item["user_id"] == user_id
        }

        attempt_items: list[AttemptItem] = []
        section_bucket: dict[str, dict[str, int]] = defaultdict(lambda: {"attempted": 0, "correct": 0})

        for index, question in enumerate(session["questions"]):
            attempt = attempts_map.get(index)
            selected_option = attempt["selected_option"] if attempt else None
            is_correct = bool(attempt and attempt["is_correct"])
            time_taken_ms = int(attempt["time_taken_ms"]) if attempt else 0
            topic = str(question.get("topic", "General"))

            if attempt:
                section_bucket[topic]["attempted"] += 1
                if is_correct:
                    section_bucket[topic]["correct"] += 1

            attempt_items.append(
                AttemptItem(
                    question_index=index,
                    topic=topic,
                    text=str(question.get("text", "")),
                    selected_option=selected_option,
                    correct_index=int(question.get("correct_index", -1)),
                    is_correct=is_correct,
                    time_taken_ms=time_taken_ms,
                )
            )

        section_insights: list[SectionInsight] = []
        for topic, stats in section_bucket.items():
            attempted = stats["attempted"]
            correct = stats["correct"]
            accuracy = (correct / attempted) if attempted else 0.0
            section_insights.append(
                SectionInsight(topic=topic, attempted=attempted, correct=correct, accuracy=accuracy)
            )

        return AttemptReport(
            room_id=room_id,
            user_id=user_id,
            mode=session["mode"],
            created_at=session["created_at"],
            attempts=attempt_items,
            section_insights=section_insights,
        )

    def get_room_analytics(self, room_id: str) -> RoomAnalytics | None:
        session = self._sessions.get(room_id)
        if not session:
            return None

        room_attempts = [item for item in self._attempts if item["room_id"] == room_id]
        participants = {item["user_id"] for item in room_attempts}

        total_attempts = len(room_attempts)
        correct_attempts = sum(1 for item in room_attempts if item["is_correct"])
        avg_accuracy = (correct_attempts / total_attempts) if total_attempts else 0.0

        section_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"attempted": 0, "correct": 0})
        for item in room_attempts:
            topic = item["topic"]
            section_stats[topic]["attempted"] += 1
            if item["is_correct"]:
                section_stats[topic]["correct"] += 1

        section_insights = []
        for topic, stats in section_stats.items():
            attempted = stats["attempted"]
            correct = stats["correct"]
            accuracy = (correct / attempted) if attempted else 0.0
            section_insights.append(
                SectionInsight(topic=topic, attempted=attempted, correct=correct, accuracy=accuracy)
            )

        return RoomAnalytics(
            room_id=room_id,
            participant_count=len(participants),
            total_attempts=total_attempts,
            avg_accuracy=avg_accuracy,
            section_insights=section_insights,
        )


history_service = HistoryService()
