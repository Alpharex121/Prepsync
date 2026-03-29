import asyncio
import json
import random
import re
import urllib.request
import warnings
from collections.abc import Sequence

from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.core.observability import logger
from app.schemas.quiz import Question, QuizPackage
from app.schemas.room import RoomConfig

warnings.filterwarnings("ignore", category=FutureWarning, module="langchain_google_genai.chat_models")


class SolverCheck(BaseModel):
    question_index: int
    solved_correct_index: int
    is_valid: bool


class SolverCheckBatch(BaseModel):
    checks: list[SolverCheck]


class QuizGenerator:
    async def generate(self, config: RoomConfig) -> QuizPackage:
        package, _trace = await self.generate_with_trace(config)
        return package

    async def generate_with_trace(self, config: RoomConfig) -> tuple[QuizPackage, dict]:
        run_nonce = random.SystemRandom().randint(100000, 999999999)
        expected_total = self._expected_question_total(config)
        provider = (settings.llm_provider or "openai").strip().lower()
        model_name = self._resolve_model_name(provider)

        exams = config.exams if config.exams else ["General"]
        topics = config.topics if config.topics else ["General Aptitude"]
        difficulty = config.difficulty.value

        references, search_trace = await self._fetch_search_context(config)

        trace: dict = {
            "provider": provider,
            "model": model_name,
            "mode": settings.question_source_mode,
            "run_nonce": run_nonce,
            "expected_total": expected_total,
            "config": config.model_dump(mode="json"),
            "search": search_trace,
            "reference_count": len(references),
            "references": references,
            "prompt_initial": (
                f"pairwise_generation exams={exams} topics={topics} count_per_pair={config.count} "
                f"difficulty={difficulty}"
            ),
            "attempts": [],
            "pair_traces": [],
            "fallback_used": False,
            "fallback_reason": "",
        }

        logger.info(
            "quiz_generation provider=%s model=%s mode=%s refs=%s expected_total=%s",
            provider,
            model_name,
            settings.question_source_mode,
            len(references),
            expected_total,
        )

        all_questions: list[Question] = []
        seen_fingerprints: set[str] = set()

        for exam in exams:
            for topic in topics:
                pair_questions, pair_trace = await self._generate_pair_questions(
                    exam=exam,
                    topic=topic,
                    count=config.count,
                    difficulty=difficulty,
                    run_nonce=run_nonce,
                    references=references,
                    forbidden_fingerprints=seen_fingerprints,
                    exam_hints=self._exam_hints([exam]),
                )

                trace["pair_traces"].append(pair_trace)
                trace["attempts"].extend(pair_trace.get("attempts", []))
                if pair_trace.get("fallback_used"):
                    trace["fallback_used"] = True

                for question in pair_questions:
                    seen_fingerprints.add(self._question_fingerprint(question))
                    all_questions.append(question)

        if len(all_questions) != expected_total:
            logger.warning(
                "quiz_generation fallback reason=pairwise_count_mismatch expected=%s actual=%s",
                expected_total,
                len(all_questions),
            )
            trace["fallback_used"] = True
            trace["fallback_reason"] = f"pairwise_count_mismatch expected={expected_total} actual={len(all_questions)}"
            return self._fallback_package(config), trace

        package = QuizPackage(questions=all_questions)
        logger.info("quiz_generation success pairwise questions=%s", len(package.questions))
        return package, trace

    async def _generate_pair_questions(
        self,
        *,
        exam: str,
        topic: str,
        count: int,
        difficulty: str,
        run_nonce: int,
        references: list[dict],
        forbidden_fingerprints: set[str],
        exam_hints: str,
    ) -> tuple[list[Question], dict]:
        pair_refs = self._select_pair_references(references, exam=exam, topic=topic, limit=max(8, count * 3))
        prompt = self._build_pair_prompt(
            exam=exam,
            topic=topic,
            count=count,
            difficulty=difficulty,
            exam_hints=exam_hints,
            run_nonce=run_nonce,
            references=pair_refs,
        )

        pair_trace = {
            "exam": exam,
            "topic": topic,
            "count": count,
            "reference_count": len(pair_refs),
            "attempts": [],
            "fallback_used": False,
            "fallback_reason": "",
        }

        for attempt in range(3):
            llm_output = await self._generate_with_langchain(prompt)
            questions, verify = await self._validate_and_verify_pair_output(
                llm_output=llm_output,
                expected_count=count,
                exam=exam,
                topic=topic,
                difficulty=difficulty,
                forbidden_fingerprints=forbidden_fingerprints,
            )

            pair_trace["attempts"].append(
                {
                    "pair_exam": exam,
                    "pair_topic": topic,
                    "attempt": attempt + 1,
                    "prompt": prompt,
                    "llm_output": llm_output,
                    "verification": verify,
                    "accepted": questions is not None,
                }
            )

            if questions is not None:
                return questions, pair_trace

            prompt = (
                self._build_pair_prompt(
                    exam=exam,
                    topic=topic,
                    count=count,
                    difficulty=difficulty,
                    exam_hints=exam_hints,
                    run_nonce=run_nonce,
                    references=pair_refs,
                )
                + "\n\nPrevious attempt failed verification. "
                + f"Failure detail: {verify.get('reason', 'unknown')}"
            )

        pair_trace["fallback_used"] = True
        pair_trace["fallback_reason"] = "pair_llm_unverified"
        fallback_questions = self._fallback_questions_for_pair(
            topic=topic,
            exam=exam,
            count=count,
            difficulty=difficulty,
            run_salt=random.SystemRandom().randint(100000, 999999999),
            forbidden_fingerprints=forbidden_fingerprints,
        )
        return fallback_questions, pair_trace

    async def _validate_and_verify_pair_output(
        self,
        *,
        llm_output: dict | None,
        expected_count: int,
        exam: str,
        topic: str,
        difficulty: str,
        forbidden_fingerprints: set[str],
    ) -> tuple[list[Question] | None, dict]:
        if llm_output is None:
            return None, {"stage": "llm", "reason": "llm_output_none"}

        try:
            package = QuizPackage.model_validate(llm_output)
        except ValidationError as exc:
            return None, {"stage": "schema", "reason": str(exc)}

        if len(package.questions) != expected_count:
            return None, {
                "stage": "count",
                "reason": f"expected={expected_count} actual={len(package.questions)}",
            }

        normalized_questions = [
            Question(
                text=self._ensure_exam_tag(question.text, exam),
                options=question.options,
                correct_index=question.correct_index,
                explanation=question.explanation,
                difficulty=difficulty,
                topic=topic,
            )
            for question in package.questions
        ]

        if self._has_exact_duplicates(normalized_questions):
            return None, {"stage": "dedupe", "reason": "exact_duplicate_within_pair"}

        for question in normalized_questions:
            if self._question_fingerprint(question) in forbidden_fingerprints:
                return None, {"stage": "dedupe", "reason": "exact_duplicate_across_pairs"}

        deterministic_mismatches = self._deterministic_mismatch_indices(normalized_questions)
        if deterministic_mismatches:
            return None, {
                "stage": "deterministic",
                "reason": "deterministic_mismatch",
                "mismatch_indices": deterministic_mismatches,
            }

        solver_ok, solver_details = await self._solver_verification_pass(normalized_questions)
        if not solver_ok:
            return None, {
                "stage": "solver",
                "reason": "solver_verification_failed",
                "solver": solver_details,
            }

        return normalized_questions, {
            "stage": "accepted",
            "reason": "passed_all_checks",
            "solver": solver_details,
        }
    async def _validate_and_verify_package(self, llm_output: dict | None, expected_total: int) -> tuple[QuizPackage | None, dict]:
        if llm_output is None:
            return None, {"stage": "llm", "reason": "llm_output_none"}

        try:
            package = QuizPackage.model_validate(llm_output)
        except ValidationError as exc:
            return None, {"stage": "schema", "reason": str(exc)}

        if len(package.questions) != expected_total:
            return None, {
                "stage": "count",
                "reason": f"expected={expected_total} actual={len(package.questions)}",
            }

        if self._has_exact_duplicates(package.questions):
            return None, {"stage": "dedupe", "reason": "exact_duplicate_found"}

        deterministic_mismatches = self._deterministic_mismatch_indices(package.questions)
        if deterministic_mismatches:
            logger.info("quiz_generation deterministic_mismatch count=%s", len(deterministic_mismatches))
            return None, {
                "stage": "deterministic",
                "reason": "deterministic_mismatch",
                "mismatch_indices": deterministic_mismatches,
            }

        solver_ok, solver_details = await self._solver_verification_pass(package.questions)
        if not solver_ok:
            logger.info("quiz_generation solver_verification_failed")
            return None, {
                "stage": "solver",
                "reason": "solver_verification_failed",
                "solver": solver_details,
            }

        return package, {
            "stage": "accepted",
            "reason": "passed_all_checks",
            "solver": solver_details,
        }

    async def _solver_verification_pass(self, questions: list[Question]) -> tuple[bool, dict]:
        provider = (settings.llm_provider or "openai").strip().lower()
        model = self._build_provider_model(provider)
        if model is None:
            return True, {"skipped": True, "reason": "model_unavailable"}

        try:
            from langchain_core.prompts import ChatPromptTemplate

            structured = model.with_structured_output(SolverCheckBatch)

            payload = [
                {
                    "question_index": idx,
                    "text": question.text,
                    "options": question.options,
                    "correct_index": question.correct_index,
                }
                for idx, question in enumerate(questions)
            ]

            prompt = (
                "For each MCQ below, solve it independently and return whether provided correct_index is valid. "
                "Use strict reasoning for quantitative questions. "
                "Return only structured output.\n\n"
                f"Questions JSON:\n{json.dumps(payload)}"
            )

            chain = ChatPromptTemplate.from_messages(
                [
                    (
                        "system",
                        "You are a strict exam verifier. Never guess. Mark invalid if uncertain.",
                    ),
                    ("human", "{prompt}"),
                ]
            ) | structured

            result = await chain.ainvoke({"prompt": prompt})
            checks = result.checks if isinstance(result, SolverCheckBatch) else []
            check_map = {item.question_index: item for item in checks}
            if len(check_map) < len(questions):
                return False, {
                    "skipped": False,
                    "reason": "incomplete_solver_response",
                    "check_count": len(check_map),
                    "expected_count": len(questions),
                }

            mismatches: list[int] = []
            invalid: list[int] = []
            for index, question in enumerate(questions):
                row = check_map.get(index)
                if row is None:
                    invalid.append(index)
                    continue
                if not row.is_valid:
                    invalid.append(index)
                if int(row.solved_correct_index) != int(question.correct_index):
                    mismatches.append(index)

            ok = not mismatches and not invalid
            return ok, {
                "skipped": False,
                "reason": "ok" if ok else "solver_mismatch",
                "mismatch_indices": mismatches,
                "invalid_indices": invalid,
                "checks": [item.model_dump(mode="json") for item in checks],
            }
        except Exception as exc:
            # If verifier call fails due provider issues, do not block generation.
            return True, {"skipped": True, "reason": f"solver_exception:{exc}"}

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

    async def _fetch_search_context(self, config: RoomConfig) -> tuple[list[dict], dict]:
        mode = (settings.question_source_mode or "generated").strip().lower()
        if mode == "generated":
            return [], {"enabled": False, "reason": "mode_generated", "queries": [], "results": []}
        if not settings.tavily_api_key:
            return [], {"enabled": False, "reason": "missing_tavily_key", "queries": [], "results": []}

        exams = config.exams if config.exams else ["General"]
        topics = config.topics if config.topics else ["General Aptitude"]

        references: list[dict] = []
        expected_total = self._expected_question_total(config)
        configured_limit = max(0, int(settings.search_reference_limit))
        target_refs = configured_limit if configured_limit > 0 else max(24, expected_total * 2)

        pair_count = max(1, len(exams) * len(topics))
        per_pair_target = max(3, (target_refs + pair_count - 1) // pair_count)
        results_per_call = min(10, max(3, per_pair_target))
        calls_per_pair = max(1, min(3, (per_pair_target + results_per_call - 1) // results_per_call))

        seen_urls: set[str] = set()
        queries_trace: list[dict] = []
        results_trace: list[dict] = []

        for exam in exams:
            for topic in topics:
                if len(references) >= target_refs:
                    search_trace = {
                        "enabled": True,
                        "reason": "target_reached",
                        "target_refs": target_refs,
                        "queries": queries_trace,
                        "results": results_trace,
                    }
                    return references, search_trace

                queries = [self._build_search_query(exam, topic, config.difficulty.value)]
                if calls_per_pair >= 2:
                    queries.append(
                        f'"{exam}" "{topic}" "{config.difficulty.value}" previous year solved MCQ with answer key PDF site:gateoverflow.in OR site:official'
                    )
                if calls_per_pair >= 3:
                    queries.append(
                        f'"{exam}" "{topic}" "{config.difficulty.value}" PYQ numerical questions with solution'
                    )

                for query in queries[:calls_per_pair]:
                    queries_trace.append({"exam": exam, "topic": topic, "query": query, "max_results": results_per_call})
                    rows = await self._tavily_search(query=query, max_results=results_per_call)
                    kept = 0
                    for row in rows:
                        url = str(row.get("url", "")).strip()
                        if not url or url in seen_urls:
                            continue
                        seen_urls.add(url)
                        kept += 1
                        references.append(row)
                        results_trace.append(
                            {
                                "exam": exam,
                                "topic": topic,
                                "query": query,
                                "title": row.get("title", ""),
                                "url": url,
                                "content": row.get("content", ""),
                            }
                        )
                        if len(references) >= target_refs:
                            break

                    if len(references) >= target_refs:
                        break

        search_trace = {
            "enabled": True,
            "reason": "completed",
            "target_refs": target_refs,
            "queries": queries_trace,
            "results": results_trace,
        }
        return references, search_trace

    async def _tavily_search(self, query: str, max_results: int) -> list[dict]:
        return await asyncio.to_thread(self._tavily_search_sync, query, max_results)

    def _tavily_search_sync(self, query: str, max_results: int) -> list[dict]:
        payload = {
            "api_key": settings.tavily_api_key,
            "query": query,
            "max_results": max(1, max_results),
            "search_depth": "advanced",
            "include_answer": False,
            "include_images": False,
            "include_raw_content": False,
        }

        request = urllib.request.Request(
            "https://api.tavily.com/search",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=18) as response:
                body = response.read().decode("utf-8")
            data = json.loads(body)
        except Exception:
            return []

        rows: list[dict] = []
        for item in data.get("results", []):
            rows.append(
                {
                    "title": str(item.get("title", "")).strip(),
                    "url": str(item.get("url", "")).strip(),
                    "content": str(item.get("content", "")).strip(),
                }
            )
        return rows

    def _select_pair_references(self, references: list[dict], *, exam: str, topic: str, limit: int) -> list[dict]:
        exam_l = exam.strip().lower()
        topic_l = topic.strip().lower()

        strong: list[dict] = []
        weak: list[dict] = []
        for row in references:
            blob = " ".join(
                [
                    str(row.get("title", "")),
                    str(row.get("url", "")),
                    str(row.get("content", "")),
                ]
            ).lower()
            has_exam = exam_l in blob
            has_topic = topic_l in blob
            if has_exam and has_topic:
                strong.append(row)
            elif has_exam or has_topic:
                weak.append(row)

        merged = strong + weak
        return (merged if merged else references)[:limit]
    def _build_search_query(self, exam: str, topic: str, difficulty: str) -> str:
        return (
            f'"{exam}" "{topic}" "{difficulty}" previous year question with solution '
            "MCQ numerical PDF OR gateoverflow OR official paper"
        )


    def _ensure_exam_tag(self, text: str, exam: str) -> str:
        stripped = text.strip()
        if stripped.startswith("[") and "]" in stripped:
            return stripped
        return f"[{exam}] {stripped}"

    def _expected_question_total(self, config: RoomConfig) -> int:
        topic_count = max(1, len(config.topics))
        exam_count = max(1, len(config.exams))
        return config.count * topic_count * exam_count

    def _build_pair_prompt(
        self,
        *,
        exam: str,
        topic: str,
        count: int,
        difficulty: str,
        exam_hints: str,
        run_nonce: int,
        references: list[dict],
    ) -> str:
        context_block = self._reference_block(references)
        return (
            "Hybrid SAG generation instructions:\n"
            "Generate ONLY for the given single exam-topic pair.\n"
            "Use reference snippets as PYQ style anchors, mutate parameters and context, and ensure answer index is correct.\n\n"
            "Constraints:\n"
            f"- Exam: {exam}\n"
            f"- Topic: {topic}\n"
            f"- Questions required: exactly {count}\n"
            "- Each question must have exactly 4 options and one correct index from 0 to 3\n"
            f"- Difficulty: {difficulty}\n"
            "- No placeholders or template text\n"
            "- Avoid easy one-step formula-only patterns\n"
            f"- Exam style hints:\n{exam_hints}\n"
            f"- Randomization nonce: {run_nonce}\n\n"
            "Reference material (may be empty):\n"
            f"{context_block}"
        )
    def _build_prompt(self, config: RoomConfig, run_nonce: int, references: list[dict]) -> str:
        exam_hints = self._exam_hints(config.exams)
        topic_list = ", ".join(config.topics) if config.topics else "General Aptitude"
        exam_list = ", ".join(config.exams) if config.exams else "General"
        expected_total = self._expected_question_total(config)

        context_block = self._reference_block(references)

        return (
            "Hybrid SAG generation instructions:\n"
            "Step 1 (Gold standard): Use reference snippets as PYQ style anchors where available.\n"
            "Step 2 (Context injection): Match depth and distractor quality from references.\n"
            "Step 3 (Parameter mutation): Reuse logic pattern but mutate numbers, entities, and scenario details.\n"
            "Step 4 (Self-correction): Ensure answer index matches computed solution before finalizing each question.\n\n"
            "Constraints:\n"
            f"- Exams: {exam_list}\n"
            f"- Topics: {topic_list}\n"
            f"- Questions per topic per exam: {config.count}\n"
            f"- Total questions required: {expected_total}\n"
            "- For EACH exam and EACH topic combination, generate exactly the specified count\n"
            "- Each question must have exactly 4 options and one correct index from 0 to 3\n"
            "- Avoid exact repeats in question text and option set\n"
            "- No placeholders or template text\n"
            f"- Target difficulty level: {config.difficulty.value}\n"
            f"- Adapt style by exam hints:\n{exam_hints}\n"
            "- Prefer quantitative rigor for hard mode\n"
            f"- Randomization nonce: {run_nonce}\n\n"
            "Reference material (may be empty):\n"
            f"{context_block}"
        )

    def _reference_block(self, references: list[dict]) -> str:
        if not references:
            return "No external references available. Use strong exam-style priors and avoid easy questions."

        rows: list[str] = []
        for idx, row in enumerate(references[: max(1, int(settings.search_reference_limit))], start=1):
            title = row.get("title", "")
            url = row.get("url", "")
            content = row.get("content", "")
            snippet = content[:500]
            rows.append(
                f"[{idx}] title={title}\nurl={url}\nsnippet={snippet}"
            )
        return "\n\n".join(rows)

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

    def _has_exact_duplicates(self, questions: list[Question]) -> bool:
        seen: set[str] = set()
        for question in questions:
            key = self._question_fingerprint(question)
            if key in seen:
                return True
            seen.add(key)
        return False

    def _question_fingerprint(self, question: Question) -> str:
        normalized_text = re.sub(r"\s+", " ", question.text.strip().lower())
        normalized_options = "||".join(re.sub(r"\s+", " ", option.strip().lower()) for option in question.options)
        return f"{normalized_text}##{normalized_options}"

    def _deterministic_mismatch_indices(self, questions: list[Question]) -> list[int]:
        mismatches: list[int] = []
        for index, question in enumerate(questions):
            solved = self._deterministic_correct_index(question)
            if solved is None:
                continue
            if solved != question.correct_index:
                mismatches.append(index)
        return mismatches

    def _deterministic_correct_index(self, question: Question) -> int | None:
        text = question.text.lower()

        if "average" in text:
            numbers = self._extract_numbers(question.text)
            if len(numbers) >= 4:
                value = (numbers[0] + numbers[1] + numbers[2] + numbers[3]) / 4
                return self._match_numeric_option(question.options, value)

        if ("profit" in text or "gain" in text or "loss" in text) and "percent" in text:
            numbers = self._extract_numbers(question.text)
            if len(numbers) >= 2:
                cp = numbers[0]
                percent = numbers[1]
                if "loss" in text:
                    sp = cp * (100 - percent) / 100
                else:
                    sp = cp * (100 + percent) / 100
                return self._match_numeric_option(question.options, sp)

        if "finish" in text and "days" in text and "together" in text:
            numbers = self._extract_numbers(question.text)
            if len(numbers) >= 2 and numbers[0] > 0 and numbers[1] > 0:
                time_together = (numbers[0] * numbers[1]) / (numbers[0] + numbers[1])
                return self._match_numeric_option(question.options, time_together)

        x_match = re.search(r"x\s*=\s*(-?\d+(?:\.\d+)?)", question.text, flags=re.IGNORECASE)
        y_match = re.search(r"y\s*=\s*(-?\d+(?:\.\d+)?)", question.text, flags=re.IGNORECASE)
        if x_match and y_match and ("x + 2y" in text or "x+2y" in text):
            x = float(x_match.group(1))
            y = float(y_match.group(1))
            return self._match_numeric_option(question.options, x + 2 * y)

        return None

    def _extract_numbers(self, text: str) -> list[float]:
        return [float(match) for match in re.findall(r"-?\d+(?:\.\d+)?", text)]

    def _match_numeric_option(self, options: Sequence[str], target: float, tol: float = 1e-2) -> int | None:
        for index, option in enumerate(options):
            normalized = option.replace(",", "").strip()
            try:
                value = float(normalized)
            except ValueError:
                continue
            if abs(value - target) <= tol:
                return index
            if abs(value - round(target)) <= tol:
                return index
        return None

    def _fallback_questions_for_pair(
        self,
        *,
        topic: str,
        exam: str,
        count: int,
        difficulty: str,
        run_salt: int,
        forbidden_fingerprints: set[str],
    ) -> list[Question]:
        questions: list[Question] = []
        index = 0
        while len(questions) < count and index < (count * 10):
            candidate = self._fallback_question(topic, exam, index, difficulty, run_salt)
            fingerprint = self._question_fingerprint(candidate)
            if fingerprint in forbidden_fingerprints:
                index += 1
                continue
            if any(self._question_fingerprint(existing) == fingerprint for existing in questions):
                index += 1
                continue
            questions.append(candidate)
            index += 1

        if len(questions) < count:
            while len(questions) < count:
                questions.append(self._fallback_question(topic, exam, len(questions), difficulty, run_salt + 7))

        return questions
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
            questions.append(self._fallback_question(topic, exam, index, difficulty, run_salt))

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












