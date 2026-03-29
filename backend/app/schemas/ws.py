from pydantic import BaseModel, Field


class JoinRoomEvent(BaseModel):
    type: str
    user_id: str = Field(min_length=1, max_length=64)


class RoomStateChangeEvent(BaseModel):
    type: str
    status: str


class SubmitAnswerEvent(BaseModel):
    type: str
    question_index: int = Field(ge=0, le=5000)
    selected_option: int = Field(ge=0, le=3)


class NavigateQuestionEvent(BaseModel):
    type: str
    question_index: int = Field(ge=0, le=5000)


class SubmitSectionEvent(BaseModel):
    type: str
    section_index: int = Field(ge=0, le=500)


class EndSessionVoteEvent(BaseModel):
    type: str

