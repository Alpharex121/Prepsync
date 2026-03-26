from enum import Enum

from pydantic import BaseModel, Field, model_validator


class RoomStatus(str, Enum):
    LOBBY = "LOBBY"
    GENERATING = "GENERATING"
    ACTIVE = "ACTIVE"
    FINISHED = "FINISHED"


class RoomMode(str, Enum):
    QUIZ = "QUIZ"
    TEST = "TEST"


class RoomConfig(BaseModel):
    mode: RoomMode = RoomMode.QUIZ
    count: int = Field(default=10, ge=1, le=200)
    time_per_q: int = Field(default=60, ge=5, le=3600)
    time_per_section: int = Field(default=300, ge=30, le=7200)
    exams: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_timing(self):
        if self.mode == RoomMode.QUIZ:
            self.time_per_section = 300
        if self.mode == RoomMode.TEST:
            self.time_per_q = 60
        return self


class RoomCreateRequest(BaseModel):
    config: RoomConfig = Field(default_factory=RoomConfig)


class RoomCreateResponse(BaseModel):
    room_id: str
    status: RoomStatus


class RoomJoinCheckResponse(BaseModel):
    room_id: str
    can_join: bool
    status: RoomStatus


class RoomTransitionRequest(BaseModel):
    status: RoomStatus


class RoomStateResponse(BaseModel):
    room_id: str
    status: RoomStatus
    ends_at: int = 0
    test_ends_at: int = 0
    current_question: int = 0


class RoomGenerationResponse(BaseModel):
    room_id: str
    status: RoomStatus
    question_count: int
    ends_at: int = 0
    test_ends_at: int = 0
    current_question: int = 0
