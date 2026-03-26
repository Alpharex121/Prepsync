from pydantic import BaseModel, Field, field_validator


class Question(BaseModel):
    text: str = Field(min_length=5)
    options: list[str] = Field(min_length=4, max_length=4)
    correct_index: int = Field(ge=0, le=3)
    explanation: str = Field(min_length=3)
    difficulty: str
    topic: str

    @field_validator("difficulty")
    @classmethod
    def validate_difficulty(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"easy", "medium", "hard"}:
            raise ValueError("difficulty must be one of: easy, medium, hard")
        return normalized


class QuizPackage(BaseModel):
    questions: list[Question] = Field(min_length=1)
