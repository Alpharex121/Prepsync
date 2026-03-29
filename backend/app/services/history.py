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
        self._user_results: list[dict] = []

    def _ensure_db_schema(self, connection: psycopg.Connection) -> None:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS quiz_history (
                    room_id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    config_params JSONB NOT NULL,
                    question_package JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS quiz_attempt_history (
                    id BIGSERIAL PRIMARY KEY,
                    room_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    question_index INTEGER NOT NULL,
                    selected_option INTEGER NOT NULL,
                    is_correct BOOLEAN NOT NULL,
                    time_taken_ms INTEGER NOT NULL DEFAULT 0,
                    topic TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (room_id, user_id, question_index)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS quiz_user_results (
                    room_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    score DOUBLE PRECISION NOT NULL DEFAULT 0,
                    completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (room_id, user_id)
                )
                """
            )

    def _to_iso(self, value: object) -> str:
        if isinstance(value, datetime):
            return value.astimezone(UTC).isoformat()
        return str(value)

    def _get_session(self, room_id: str) -> dict | None:
        cached = self._sessions.get(room_id)
        if cached:
            return cached

        try:
            with psycopg.connect(settings.postgres_url) as connection:
                self._ensure_db_schema(connection)
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT room_id, mode, config_params, question_package, created_at
                        FROM quiz_history
                        WHERE room_id = %s
                        """,
                        (room_id,),
                    )
                    row = cursor.fetchone()
        except Exception:
            return None

        if row is None:
            return None

        room_id_val, mode, config_params, question_package, created_at = row
        config_dict = dict(config_params or {})
        question_dict = dict(question_package or {})
        questions = list(question_dict.get("questions", []))
        session = {
            "room_id": str(room_id_val),
            "mode": str(mode),
            "config": config_dict,
            "questions": questions,
            "created_at": self._to_iso(created_at),
        }
        self._sessions[str(room_id_val)] = session
        return session

    def _get_attempt_rows(self, room_id: str, user_id: str | None = None) -> list[dict]:
        try:
            with psycopg.connect(settings.postgres_url) as connection:
                self._ensure_db_schema(connection)
                with connection.cursor() as cursor:
                    if user_id is None:
                        cursor.execute(
                            """
                            SELECT room_id, user_id, question_index, selected_option, is_correct, time_taken_ms, topic, created_at
                            FROM quiz_attempt_history
                            WHERE room_id = %s
                            """,
                            (room_id,),
                        )
                    else:
                        cursor.execute(
                            """
                            SELECT room_id, user_id, question_index, selected_option, is_correct, time_taken_ms, topic, created_at
                            FROM quiz_attempt_history
                            WHERE room_id = %s AND user_id = %s
                            """,
                            (room_id, user_id),
                        )
                    rows = cursor.fetchall()

            result: list[dict] = []
            for row in rows:
                result.append(
                    {
                        "room_id": str(row[0]),
                        "user_id": str(row[1]),
                        "question_index": int(row[2]),
                        "selected_option": int(row[3]),
                        "is_correct": bool(row[4]),
                        "time_taken_ms": int(row[5]),
                        "topic": str(row[6]),
                        "created_at": self._to_iso(row[7]),
                    }
                )
            return result
        except Exception:
            if user_id is None:
                return [item for item in self._attempts if item["room_id"] == room_id]
            return [
                item
                for item in self._attempts
                if item["room_id"] == room_id and item["user_id"] == user_id
            ]

    def persist_quiz_history(self, room_id: str, config: RoomConfig, package: QuizPackage) -> None:
        created_at = datetime.now(UTC).isoformat()
        session = {
            "room_id": room_id,
            "mode": config.mode.value,
            "config": config.model_dump(mode="json"),
            "questions": package.model_dump(mode="json").get("questions", []),
            "created_at": created_at,
        }
        self._sessions[room_id] = session

        try:
            with psycopg.connect(settings.postgres_url) as connection:
                self._ensure_db_schema(connection)
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO quiz_history (room_id, mode, config_params, question_package)
                        VALUES (%s, %s, %s::jsonb, %s::jsonb)
                        ON CONFLICT (room_id) DO UPDATE
                        SET mode = EXCLUDED.mode,
                            config_params = EXCLUDED.config_params,
                            question_package = EXCLUDED.question_package,
                            created_at = NOW()
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
        session = self._get_session(room_id)
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
        row = {
            "room_id": room_id,
            "user_id": user_id,
            "question_index": question_index,
            "selected_option": selected_option,
            "is_correct": selected_option == correct_index,
            "time_taken_ms": max(0, int(time_taken_ms)),
            "topic": topic,
            "created_at": datetime.now(UTC).isoformat(),
        }
        self._attempts.append(row)

        try:
            with psycopg.connect(settings.postgres_url) as connection:
                self._ensure_db_schema(connection)
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO quiz_attempt_history (
                            room_id, user_id, question_index, selected_option, is_correct, time_taken_ms, topic
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (room_id, user_id, question_index) DO NOTHING
                        """,
                        (
                            room_id,
                            user_id,
                            question_index,
                            selected_option,
                            row["is_correct"],
                            row["time_taken_ms"],
                            topic,
                        ),
                    )
                connection.commit()
        except Exception:
            pass

        return True
    def persist_user_results(self, room_id: str, results: list[dict]) -> None:
        if not results:
            return

        for row in results:
            self._user_results.append(
                {
                    "room_id": room_id,
                    "user_id": str(row.get("user_id", "")),
                    "score": float(row.get("score", 0.0)),
                    "completed_at": datetime.now(UTC).isoformat(),
                }
            )

        try:
            with psycopg.connect(settings.postgres_url) as connection:
                self._ensure_db_schema(connection)
                with connection.cursor() as cursor:
                    for row in results:
                        cursor.execute(
                            """
                            INSERT INTO quiz_user_results (room_id, user_id, score, completed_at)
                            VALUES (%s, %s, %s, NOW())
                            ON CONFLICT (room_id, user_id) DO UPDATE
                            SET score = EXCLUDED.score,
                                completed_at = NOW()
                            """,
                            (
                                room_id,
                                str(row.get("user_id", "")),
                                float(row.get("score", 0.0)),
                            ),
                        )
                connection.commit()
        except Exception:
            pass

    def list_history(
        self,
        *,
        user_id: str,
        mode: str | None,
        date_from: str | None,
        date_to: str | None,
        topic: str | None,
        exam: str | None,
    ) -> list[HistoryListItem]:
        sessions: list[dict] = []
        normalized_user_id = user_id.strip().lower()

        try:
            with psycopg.connect(settings.postgres_url) as connection:
                self._ensure_db_schema(connection)
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT qh.room_id, qh.mode, qh.config_params, qh.created_at
                        FROM quiz_history qh
                        LEFT JOIN (
                            SELECT DISTINCT room_id
                            FROM quiz_attempt_history
                            WHERE lower(trim(user_id)) = %s
                        ) ua ON ua.room_id = qh.room_id
                        LEFT JOIN (
                            SELECT DISTINCT room_id
                            FROM quiz_user_results
                            WHERE lower(trim(user_id)) = %s
                        ) ur ON ur.room_id = qh.room_id
                        WHERE ua.room_id IS NOT NULL
                           OR ur.room_id IS NOT NULL
                           OR lower(trim(COALESCE(qh.config_params->>'owner_id', ''))) = %s
                        ORDER BY qh.created_at DESC
                        """,
                        (normalized_user_id, normalized_user_id, normalized_user_id),
                    )
                    for room_id, mode_val, config_params, created_at in cursor.fetchall():
                        sessions.append(
                            {
                                "room_id": str(room_id),
                                "mode": str(mode_val),
                                "config": dict(config_params or {}),
                                "created_at": self._to_iso(created_at),
                            }
                        )
        except Exception:
            user_room_ids = {
                item["room_id"]
                for item in self._attempts
                if str(item.get("user_id", "")).strip().lower() == normalized_user_id
            }
            user_room_ids.update({
                item["room_id"]
                for item in self._user_results
                if str(item.get("user_id", "")).strip().lower() == normalized_user_id
            })
            sessions = [
                session
                for session in self._sessions.values()
                if session.get("room_id") in user_room_ids
                or str(session.get("config", {}).get("owner_id", "")).strip().lower() == normalized_user_id
            ]

        # Always merge in-memory fallback so history still appears if DB writes were partially missed.
        user_room_ids = {
            item["room_id"]
            for item in self._attempts
            if str(item.get("user_id", "")).strip().lower() == normalized_user_id
        }
        user_room_ids.update({
            item["room_id"]
            for item in self._user_results
            if str(item.get("user_id", "")).strip().lower() == normalized_user_id
        })

        merged_sessions: dict[str, dict] = {str(session.get("room_id", "")): session for session in sessions if session.get("room_id")}
        for session in self._sessions.values():
            room_id = str(session.get("room_id", ""))
            owner_id = str(session.get("config", {}).get("owner_id", "")).strip().lower()
            if room_id and (room_id in user_room_ids or owner_id == normalized_user_id):
                merged_sessions.setdefault(room_id, session)

        items: list[HistoryListItem] = []
        for session in merged_sessions.values():
            if mode and str(session["mode"]).upper() != mode.upper():
                continue

            created = str(session["created_at"])
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
                    room_id=str(session["room_id"]),
                    mode=str(session["mode"]),
                    topics=topics,
                    exams=exams,
                    created_at=created,
                )
            )

        items.sort(key=lambda item: item.created_at, reverse=True)
        return items

    def get_attempt_report(self, *, room_id: str, user_id: str) -> AttemptReport | None:
        session = self._get_session(room_id)
        if not session:
            return None

        attempt_rows = self._get_attempt_rows(room_id, user_id)
        attempts_map = {item["question_index"]: item for item in attempt_rows}

        attempt_items: list[AttemptItem] = []
        topic_totals: dict[str, int] = defaultdict(int)
        topic_correct: dict[str, int] = defaultdict(int)

        for index, question in enumerate(session["questions"]):
            topic = str(question.get("topic", "General"))
            topic_totals[topic] += 1

            attempt = attempts_map.get(index)
            selected_option = attempt["selected_option"] if attempt else None
            is_correct = bool(attempt and attempt["is_correct"])
            time_taken_ms = int(attempt["time_taken_ms"]) if attempt else 0
            if is_correct:
                topic_correct[topic] += 1

            attempt_items.append(
                AttemptItem(
                    question_index=index,
                    topic=topic,
                    text=str(question.get("text", "")),
                    explanation=str(question.get("explanation", "")),
                    selected_option=selected_option,
                    correct_index=int(question.get("correct_index", -1)),
                    is_correct=is_correct,
                    time_taken_ms=time_taken_ms,
                )
            )

        section_insights: list[SectionInsight] = []
        for topic, total_questions in topic_totals.items():
            correct = topic_correct.get(topic, 0)
            accuracy = (correct / total_questions) if total_questions else 0.0
            section_insights.append(
                SectionInsight(topic=topic, attempted=total_questions, correct=correct, accuracy=accuracy)
            )

        section_insights.sort(key=lambda insight: insight.topic)

        return AttemptReport(
            room_id=room_id,
            user_id=user_id,
            mode=session["mode"],
            created_at=session["created_at"],
            attempts=attempt_items,
            section_insights=section_insights,
        )

    def get_room_analytics(self, room_id: str) -> RoomAnalytics | None:
        session = self._get_session(room_id)
        if not session:
            return None

        room_attempts = self._get_attempt_rows(room_id, None)
        participants = {item["user_id"] for item in room_attempts}
        participant_count = len(participants)

        total_questions = len(session.get("questions", []))
        correct_attempts = sum(1 for item in room_attempts if item["is_correct"])
        denominator = total_questions * participant_count if participant_count else 0
        avg_accuracy = (correct_attempts / denominator) if denominator else 0.0

        topic_totals: dict[str, int] = defaultdict(int)
        for question in session.get("questions", []):
            topic = str(question.get("topic", "General"))
            topic_totals[topic] += 1

        topic_correct: dict[str, int] = defaultdict(int)
        for item in room_attempts:
            if item["is_correct"]:
                topic_correct[item["topic"]] += 1

        section_insights: list[SectionInsight] = []
        for topic, total_in_topic in topic_totals.items():
            total_possible = total_in_topic * participant_count
            correct = topic_correct.get(topic, 0)
            accuracy = (correct / total_possible) if total_possible else 0.0
            section_insights.append(
                SectionInsight(topic=topic, attempted=total_possible, correct=correct, accuracy=accuracy)
            )

        section_insights.sort(key=lambda insight: insight.topic)

        return RoomAnalytics(
            room_id=room_id,
            participant_count=participant_count,
            total_attempts=len(room_attempts),
            avg_accuracy=avg_accuracy,
            section_insights=section_insights,
        )


history_service = HistoryService()











