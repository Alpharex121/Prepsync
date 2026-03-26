from pydantic import BaseModel


class HistoryListItem(BaseModel):
    room_id: str
    mode: str
    topics: list[str]
    exams: list[str]
    created_at: str


class AttemptRecordRequest(BaseModel):
    room_id: str
    user_id: str
    question_index: int
    selected_option: int
    time_taken_ms: int = 0


class AttemptItem(BaseModel):
    question_index: int
    topic: str
    text: str
    selected_option: int | None
    correct_index: int
    is_correct: bool
    time_taken_ms: int


class SectionInsight(BaseModel):
    topic: str
    attempted: int
    correct: int
    accuracy: float


class AttemptReport(BaseModel):
    room_id: str
    user_id: str
    mode: str
    created_at: str
    attempts: list[AttemptItem]
    section_insights: list[SectionInsight]


class RoomAnalytics(BaseModel):
    room_id: str
    participant_count: int
    total_attempts: int
    avg_accuracy: float
    section_insights: list[SectionInsight]
