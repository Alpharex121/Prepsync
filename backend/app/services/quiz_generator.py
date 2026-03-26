import random
from collections.abc import Sequence

from pydantic import ValidationError

from app.core.config import settings
from app.schemas.quiz import Question, QuizPackage
from app.schemas.room import RoomConfig


class QuizGenerator:
    async def generate(self, config: RoomConfig) -> QuizPackage:
        prompt = self._build_prompt(config)
        llm_output = await self._generate_with_langchain(prompt)

        if llm_output is None:
            return self._fallback_package(config)

        validation_errors: str | None = None
        for _ in range(2):
            try:
                return QuizPackage.model_validate(llm_output)
            except ValidationError as exc:
                validation_errors = str(exc)
                llm_output = await self._generate_with_langchain(
                    f"{prompt}\n\nValidation errors from previous attempt:\n{validation_errors}"
                )
                if llm_output is None:
                    break

        return self._fallback_package(config)

    async def _generate_with_langchain(self, prompt: str) -> dict | None:
        provider = (settings.llm_provider or "openai").strip().lower()

        try:
            from langchain_core.prompts import ChatPromptTemplate

            model = self._build_provider_model(provider)
            if model is None:
                return None

            structured_model = model.with_structured_output(QuizPackage)

            chain = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        (
                            "You are an exam-question author for Indian competitive exams. "
                            "Generate realistic MCQs with concrete numbers and plausible distractors. "
                            "Never output placeholders like 'Option A', 'Practice question', or template text. "
                            "Output must strictly match the requested structured schema."
                        ),
                    ),
                    ("human", "{prompt}"),
                ]
            ) | structured_model

            result = await chain.ainvoke({"prompt": prompt})
            if isinstance(result, QuizPackage):
                return result.model_dump(mode="json")
            if isinstance(result, dict):
                return result
            return None
        except Exception:
            return None

    def _build_provider_model(self, provider: str):
        if provider == "openai":
            if not settings.llm_api_key:
                return None
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(
                model=settings.llm_model,
                api_key=settings.llm_api_key,
                temperature=0.3,
            )

        if provider in {"gemini", "google", "google_genai"}:
            if not settings.gemini_api_key:
                return None
            from langchain_google_genai import ChatGoogleGenerativeAI

            return ChatGoogleGenerativeAI(
                model=settings.llm_model,
                google_api_key=settings.gemini_api_key,
                temperature=0.3,
            )

        if provider == "groq":
            if not settings.groq_api_key:
                return None
            from langchain_groq import ChatGroq

            return ChatGroq(
                model=settings.llm_model,
                api_key=settings.groq_api_key,
                temperature=0.3,
            )

        return None

    def _build_prompt(self, config: RoomConfig) -> str:
        exam_hints = self._exam_hints(config.exams)
        topic_list = ", ".join(config.topics) if config.topics else "General Aptitude"
        exam_list = ", ".join(config.exams) if config.exams else "General"

        return (
            "Create a quiz package with these constraints:\n"
            f"- Exams: {exam_list}\n"
            f"- Topics: {topic_list}\n"
            f"- Questions per topic: {config.count}\n"
            "- Each question must have exactly 4 options and one correct index from 0 to 3\n"
            "- Questions must be mathematically solvable and exam-style, not definition-only\n"
            "- Do not repeat questions\n"
            "- Do not use placeholder wording\n"
            f"- Adapt difficulty by exam style:\n{exam_hints}\n"
            "- Keep explanations concise and educational."
        )

    def _exam_hints(self, exams: Sequence[str]) -> str:
        normalized = {exam.strip().lower() for exam in exams}
        hints: list[str] = []

        if "gate" in normalized:
            hints.append("GATE: emphasize multi-step reasoning and analytical rigor.")
        if "ssc" in normalized:
            hints.append("SSC: emphasize fast-solving aptitude and practical shortcuts.")

        if not hints:
            hints.append("General: maintain medium difficulty balanced practice questions.")

        return "\n".join(f"  * {hint}" for hint in hints)

    def _fallback_package(self, config: RoomConfig) -> QuizPackage:
        topics = config.topics if config.topics else ["General Aptitude"]
        exams = config.exams if config.exams else ["General"]
        total_questions = config.count * len(topics) * len(exams)

        difficulty = "medium"
        normalized = {exam.lower() for exam in exams}
        if "gate" in normalized:
            difficulty = "hard"
        elif "ssc" in normalized:
            difficulty = "easy"

        questions: list[Question] = []
        for index in range(total_questions):
            topic = topics[index % len(topics)]
            exam = exams[index % len(exams)]

            question = self._fallback_question(topic, exam, index, difficulty)
            questions.append(question)

        return QuizPackage(questions=questions)

    def _fallback_question(self, topic: str, exam: str, index: int, difficulty: str) -> Question:
        lowered = topic.strip().lower()
        if "average" in lowered:
            return self._average_question(topic, exam, index, difficulty)
        if "profit" in lowered or "loss" in lowered:
            return self._profit_loss_question(topic, exam, index, difficulty)
        if "work" in lowered or "time" in lowered:
            return self._work_time_question(topic, exam, index, difficulty)
        return self._general_arithmetic_question(topic, exam, index, difficulty)

    def _average_question(self, topic: str, exam: str, index: int, difficulty: str) -> Question:
        rng = random.Random(1000 + index)
        numbers = [rng.randint(20, 60) for _ in range(4)]
        total = sum(numbers)
        average = total / 4
        correct = f"{average:.1f}" if average % 1 else str(int(average))

        offsets = [-3, -1, 2, 4]
        options = [
            correct,
            str(int(average + offsets[1])),
            str(int(average + offsets[2])),
            str(int(average + offsets[3])),
        ]
        rng.shuffle(options)
        correct_index = options.index(correct)

        text = (
            f"[{exam}] The marks of four students are {numbers[0]}, {numbers[1]}, "
            f"{numbers[2]} and {numbers[3]}. What is their average mark?"
        )
        explanation = f"Average = (sum of values)/4 = {total}/4 = {correct}."

        return Question(
            text=text,
            options=options,
            correct_index=correct_index,
            explanation=explanation,
            difficulty=difficulty,
            topic=topic,
        )

    def _profit_loss_question(self, topic: str, exam: str, index: int, difficulty: str) -> Question:
        rng = random.Random(2000 + index)
        cp = rng.randint(200, 800)
        profit_percent = rng.choice([10, 12, 15, 20, 25])
        sp = cp * (100 + profit_percent) / 100
        correct = str(int(sp))

        options = [
            correct,
            str(int(cp * (100 + profit_percent - 5) / 100)),
            str(int(cp * (100 + profit_percent + 5) / 100)),
            str(int(cp * (100 + profit_percent + 10) / 100)),
        ]
        rng.shuffle(options)
        correct_index = options.index(correct)

        text = (
            f"[{exam}] A shopkeeper buys an article for Rs. {cp} and gains "
            f"{profit_percent}%. Find the selling price."
        )
        explanation = (
            f"Selling price = CP x (100 + profit%)/100 = {cp} x {100 + profit_percent}/100 = {correct}."
        )

        return Question(
            text=text,
            options=options,
            correct_index=correct_index,
            explanation=explanation,
            difficulty=difficulty,
            topic=topic,
        )

    def _work_time_question(self, topic: str, exam: str, index: int, difficulty: str) -> Question:
        rng = random.Random(3000 + index)
        a_days = rng.randint(8, 16)
        b_days = rng.randint(10, 20)
        together = (a_days * b_days) / (a_days + b_days)
        correct = f"{together:.2f}".rstrip("0").rstrip(".")

        options = [
            correct,
            f"{together + 1:.2f}".rstrip("0").rstrip("."),
            f"{max(1.0, together - 1):.2f}".rstrip("0").rstrip("."),
            f"{together + 2:.2f}".rstrip("0").rstrip("."),
        ]
        rng.shuffle(options)
        correct_index = options.index(correct)

        text = (
            f"[{exam}] A can finish a work in {a_days} days and B can finish the same work "
            f"in {b_days} days. In how many days can they finish it together?"
        )
        explanation = (
            f"Combined rate = 1/{a_days} + 1/{b_days}; time = 1/(combined rate) = {correct} days."
        )

        return Question(
            text=text,
            options=options,
            correct_index=correct_index,
            explanation=explanation,
            difficulty=difficulty,
            topic=topic,
        )

    def _general_arithmetic_question(self, topic: str, exam: str, index: int, difficulty: str) -> Question:
        rng = random.Random(4000 + index)
        x = rng.randint(15, 45)
        y = rng.randint(5, 25)
        correct_value = x + y * 2
        correct = str(correct_value)

        options = [
            correct,
            str(correct_value + 3),
            str(correct_value - 3),
            str(correct_value + 6),
        ]
        rng.shuffle(options)
        correct_index = options.index(correct)

        text = f"[{exam}] If x = {x} and y = {y}, find the value of x + 2y."
        explanation = f"x + 2y = {x} + 2 x {y} = {correct}."

        return Question(
            text=text,
            options=options,
            correct_index=correct_index,
            explanation=explanation,
            difficulty=difficulty,
            topic=topic,
        )


quiz_generator = QuizGenerator()
