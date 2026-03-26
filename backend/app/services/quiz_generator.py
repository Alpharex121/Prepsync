import random
import warnings
from collections.abc import Sequence

from pydantic import ValidationError

from app.core.config import settings
from app.schemas.quiz import Question, QuizPackage
from app.schemas.room import RoomConfig

warnings.filterwarnings("ignore", category=FutureWarning, module="langchain_google_genai.chat_models")


class QuizGenerator:
    async def generate(self, config: RoomConfig) -> QuizPackage:
        run_nonce = random.SystemRandom().randint(100000, 999999999)
        prompt = self._build_prompt(config, run_nonce=run_nonce)
        expected_total = self._expected_question_total(config)
        llm_output = await self._generate_with_langchain(prompt)

        if llm_output is None:
            return self._fallback_package(config)

        validation_errors: str | None = None
        for _ in range(2):
            try:
                package = QuizPackage.model_validate(llm_output)
                if len(package.questions) != expected_total:
                    raise ValueError(
                        f"Expected exactly {expected_total} questions, got {len(package.questions)}"
                    )
                return package
            except (ValidationError, ValueError) as exc:
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

    def _resolve_model_name(self, provider: str) -> str:
        model_name = (settings.llm_model or "").strip()
        if model_name.startswith("models/"):
            model_name = model_name.split("/", 1)[1]

        if provider in {"gemini", "google", "google_genai"}:
            aliases = {
                "gemini-3.1-pro": "gemini-2.5-pro",
                "gemini-3.1-flash": "gemini-2.5-flash",
            }
            if model_name in aliases:
                return aliases[model_name]
            if model_name.startswith("gemini-3."):
                return "gemini-2.5-flash" if "flash" in model_name else "gemini-2.5-pro"

        return model_name

    def _build_provider_model(self, provider: str):
        model_name = self._resolve_model_name(provider)

        if provider == "openai":
            if not settings.llm_api_key:
                return None
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(
                model=model_name,
                api_key=settings.llm_api_key,
                temperature=0.3,
            )

        if provider in {"gemini", "google", "google_genai"}:
            if not settings.gemini_api_key:
                return None
            from langchain_google_genai import ChatGoogleGenerativeAI

            return ChatGoogleGenerativeAI(
                model=model_name,
                google_api_key=settings.gemini_api_key,
                temperature=0.3,
            )

        if provider == "groq":
            if not settings.groq_api_key:
                return None
            from langchain_groq import ChatGroq

            return ChatGroq(
                model=model_name,
                api_key=settings.groq_api_key,
                temperature=0.3,
            )

        return None

    def _expected_question_total(self, config: RoomConfig) -> int:
        topic_count = max(1, len(config.topics))
        exam_count = max(1, len(config.exams))
        return config.count * topic_count * exam_count

    def _build_prompt(self, config: RoomConfig, run_nonce: int) -> str:
        exam_hints = self._exam_hints(config.exams)
        topic_list = ", ".join(config.topics) if config.topics else "General Aptitude"
        exam_list = ", ".join(config.exams) if config.exams else "General"
        expected_total = self._expected_question_total(config)

        return (
            "Create a quiz package with these constraints:\n"
            f"- Exams: {exam_list}\n"
            f"- Topics: {topic_list}\n"
            f"- Questions per topic per exam: {config.count}\n"
            f"- Total questions required: {expected_total}\n"
            "- For EACH exam and EACH topic combination, generate exactly the specified count\n"
            "- Each question must have exactly 4 options and one correct index from 0 to 3\n"
            "- Questions must be mathematically solvable and exam-style, not definition-only\n"
            "- Do not repeat questions\n"
            "- Do not use placeholder wording\n"
            f"- Target difficulty level: {config.difficulty.value}\n"
            f"- Adapt style by exam hints:\n{exam_hints}\n"
            "- Keep explanations concise and educational.\n"
            "- At least 30% questions should be PYQ-style (previous year pattern), and include year/source hint in explanation where possible.\n"
            f"- Randomization nonce for this generation: {run_nonce}"
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
        total_questions = self._expected_question_total(config)

        difficulty = config.difficulty.value

        run_salt = random.SystemRandom().randint(100000, 999999999)

        questions: list[Question] = []
        for index in range(total_questions):
            topic = topics[index % len(topics)]
            exam = exams[index % len(exams)]

            question = self._fallback_question(topic, exam, index, difficulty, run_salt)
            questions.append(question)

        return QuizPackage(questions=questions)

    def _fallback_question(self, topic: str, exam: str, index: int, difficulty: str, run_salt: int) -> Question:
        lowered = topic.strip().lower()
        if "average" in lowered:
            return self._average_question(topic, exam, index, difficulty, run_salt)
        if "profit" in lowered or "loss" in lowered:
            return self._profit_loss_question(topic, exam, index, difficulty, run_salt)
        if "work" in lowered or "time" in lowered:
            return self._work_time_question(topic, exam, index, difficulty, run_salt)
        return self._general_arithmetic_question(topic, exam, index, difficulty, run_salt)

    def _average_question(self, topic: str, exam: str, index: int, difficulty: str, run_salt: int) -> Question:
        rng = random.Random(1000 + index + run_salt)
        number_ranges = {"easy": (12, 45), "medium": (20, 80), "hard": (35, 160)}
        low, high = number_ranges.get(difficulty, (20, 80))
        numbers = [rng.randint(low, high) for _ in range(4)]
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

    def _profit_loss_question(self, topic: str, exam: str, index: int, difficulty: str, run_salt: int) -> Question:
        rng = random.Random(2000 + index + run_salt)
        cp_ranges = {"easy": (120, 450), "medium": (200, 900), "hard": (700, 2500)}
        cp_low, cp_high = cp_ranges.get(difficulty, (200, 900))
        cp = rng.randint(cp_low, cp_high)
        choices = {
            "easy": [5, 10, 12, 15],
            "medium": [10, 12, 15, 20, 25],
            "hard": [12, 15, 18, 20, 25, 30, 35],
        }
        profit_percent = rng.choice(choices.get(difficulty, [10, 12, 15, 20, 25]))
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

    def _work_time_question(self, topic: str, exam: str, index: int, difficulty: str, run_salt: int) -> Question:
        rng = random.Random(3000 + index + run_salt)
        day_ranges = {"easy": (8, 14), "medium": (8, 20), "hard": (10, 30)}
        d_low, d_high = day_ranges.get(difficulty, (8, 20))
        a_days = rng.randint(d_low, d_high)
        b_days = rng.randint(d_low + 1, d_high + 4)
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

    def _general_arithmetic_question(self, topic: str, exam: str, index: int, difficulty: str, run_salt: int) -> Question:
        rng = random.Random(4000 + index + run_salt)
        xy_ranges = {"easy": ((8, 24), (3, 12)), "medium": ((15, 45), (5, 25)), "hard": ((35, 120), (12, 55))}
        (x_low, x_high), (y_low, y_high) = xy_ranges.get(difficulty, ((15, 45), (5, 25)))
        x = rng.randint(x_low, x_high)
        y = rng.randint(y_low, y_high)
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





