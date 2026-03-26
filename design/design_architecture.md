# Technical Requirements Document: PrepSync

## Project Name:

**PrepSync (Real-Time Competitive Quiz Platform)**

## Core Purpose:

A synchronized, room-based platform for competitive exam preparation (GATE, SSC, etc.) using LLM-generated content.

---

## 1. Tech Stack Overview

**Frontend:**
React.js, Redux Toolkit (Global State), Tailwind CSS (UI), Framer Motion (Animations).

**Backend:**
FastAPI (Python, Asynchronous ASGI), Uvicorn.

**Real-Time:**
WebSockets (FastAPI) + Redis Pub/Sub.

**AI Orchestration:**
LangChain + Pydantic (Structured Output) + Gemini/Groq.

**Persistence:**
PostgreSQL (User/History), Redis (Active Room State/Leaderboards).

---

## 2. Core Requirements & Constraints

**Room-Based Sync:**
All users in a room must see the same question at the same time.

**No Mid-Quiz Joining:**
Once a quiz starts or enters the generation phase, new users cannot join.

**Admin Controls:**
The Room Admin defines:

- Room Mode: `QUIZ` or `TEST`.
- Exams: Comma-separated (e.g., "GATE, SSC").
- Topics: Comma-separated (e.g., "Aptitude, OS, DBMS").
- Question Count: Number of questions per topic.
- Time Limit:
  - `QUIZ`: Seconds per individual question.
  - `TEST`: Total test duration.

**Room Modes:**

- **QUIZ Mode (Current Implementation):**
  - Only the current question is visible to all users.
  - Each question runs with per-question timer (`x` minutes/seconds as configured).
  - Users can only save/submit answer for the current question.
  - Next question is pushed when either:
    - timer ends, or
    - all active participants have submitted.
  - If a user leaves quiz midway, that user is not counted in the "all participants answered" check.

- **TEST Mode:**
  - Test content is peer-synced like quiz mode (all users receive the same generated test set for the room).
  - Time limit is same for all users, but tracked individually per user session.
  - All questions are visible within the user's active section.
  - Users can navigate questions in any order within current section.
  - Test is locked section-wise by topic; user cannot switch to next section until current section is submitted.
  - After submitting a section, the previous section is locked for that user.
  - If User A submits Section 1 early, User A can move to Section 2 while User B remains in Section 1.
  - If User A finishes entire test early, User A may leave room; final room result is declared only when either:
    - all participants finish test, or
    - exam time limit ends.
  - Total question formula:
    - `total_questions = questions_per_topic * number_of_topics * number_of_exams`
    - Example: topics = (Averages, Profit and Loss, Work and Time), exams = (GATE, SSC), questions/topic = 10
    - `total_questions = 10 * 3 * 2 = 60`
    - Section "Averages" has `10 * 2 = 20` questions (one set per exam style), and users can move across only these 20 while in that section.

**Adaptive AI:**
LLM must generate questions specific to the exam style (e.g., Numerical/Logical for GATE, Speed/Fact-based for SSC).

**Master Clock:**
Synchronization must rely on server-side absolute timestamps, not client-side intervals.

---

## 3. System Architecture & Flow

### A. The Room State Machine

Rooms must transition through these states in Redis:

- **LOBBY:** Users can join/leave. Admin configures settings.
- **GENERATING:** Admin triggers quiz. LLM is called via Background Task. Mid-joins blocked.
- **ACTIVE:** Session is live (`QUIZ` or `TEST`). Mid-joins blocked.
- **FINISHED:** Final scoreboard and solutions displayed.

---

### B. The Synchronization Engine (WebSocket)

To prevent "Timer Drift," the server calculates authoritative end times:

- `QUIZ`: per-question `ends_at`.
- `TEST`: one `test_ends_at` for total test duration (with section metadata).

**Server sends:**

```json
{
  "type": "NEW_QUESTION",
  "data": {...},
  "ends_at": 1711410045000
}
```

**Client calculates:**

```
TimeRemaining = ends_at - Date.now()
```

**Buffer:**
Server allows a +2 second latency window for answer submissions.

---

## 4. AI Generation Pipeline (LangChain)

The agent should implement a `QuizGenerator` service using LangChain's `with_structured_output`.

### Pydantic Schema:

```python
class Question(BaseModel):
    text: str
    options: List[str] # Exactly 4
    correct_index: int # 0-3
    explanation: str
    difficulty: str # Adapted to exam type
    topic: str

class QuizPackage(BaseModel):
    questions: List[Question]
```

### Prompt Strategy:

Use a System Message that instructs the LLM to balance difficulty based on the exams input.
If "GATE" is present, use higher-order cognitive questions.
If "SSC" is present, use speed-oriented aptitude questions.

---

## 5. Data Models

### Redis (Hot State)

- `room:{id}:status`: (string) Current state.
- `room:{id}:config`: (hash) mode, count, time_per_q, time_per_section, exams, topics.
- `room:{id}:questions`: (list) JSON blobs of generated questions.
- `room:{id}:leaderboard`: (ZSET) Member: user_id, Score: points.

### PostgreSQL (Persistent)

**Users Table:**

- ID
- Username
- PasswordHash

**QuizHistory Table:**

- ID
- RoomID
- Mode (`QUIZ`/`TEST`)
- ConfigParams
- CreatedAt

**Analytics Table:**

- UserID
- RoomID
- QuestionID
- IsCorrect
- TimeTaken

**History Access Requirement:**
Users can revisit any completed quiz or test from history to view results and report/solution details.

---

## 6. API & WebSocket Event Contract

### REST API

- **POST /rooms/create:** Returns room_id
- **GET /rooms/{id}/join-check:** Verifies if status is LOBBY before attempting WS connection

### WebSocket Events

**Client -> Server**

- JOIN_ROOM: user_id, room_id

**Admin -> Server**

- START_GENERATION: config_params

**Server -> Room**

- ROOM_STATE_CHANGE: `status: "GENERATING"`
- NEXT_QUESTION: question_data, ends_at_timestamp
- TEST_SECTION_START: section_topic, section_question_count, test_ends_at_timestamp
- FINAL_RESULTS: leaderboard_data, all_solutions

**Client -> Server**

- SUBMIT_ANSWER: question_index, selected_option

---

## 7. Security & Safeguards

**Late Join Guard:**
The WebSocket middleware must reject connections if `room:{id}:status != "LOBBY"`.

**Anti-Cheat:**
Answers submitted after `ends_at + 2.0s` are automatically discarded by the FastAPI backend.

**Validation:**
Every LLM response must pass the Pydantic `QuizPackage` validation.
If it fails, the agent must implement a "Self-Correction" loop (retry once with the error message).

---

## 8. Implementation Priority for Coding Agent

- **Base:** FastAPI server + Redis Connection Manager.
- **Real-Time:** WebSocket handler with Room State logic.
- **AI:** LangChain service for Adaptive Question Generation.
- **Frontend:** React Redux slice to handle the "Master Clock" and live updates.
- **Analytics:** PostgreSQL integration for solution review and scoreboard.

