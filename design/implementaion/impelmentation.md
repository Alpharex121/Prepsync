# PrepSync Implementation Log (Phase 1 to Phase 11)

## Scope
This document consolidates what has been implemented across Phase 1 through Phase 11 and records the end-to-end runtime flow of the app (what happens when users click actions in UI).

## Phase-Wise Implementation Summary

### Phase 1: Project Setup & Foundation
- Monorepo structure established with `backend`, `frontend`, `shared`, and `design`.
- FastAPI backend scaffolded with environment-driven settings.
- React + Vite frontend scaffolded with routing and base app layout.
- Local development connections configured for PostgreSQL and Redis.
- Docker Compose added for local dependency stack.
- Lint/format pipelines and pre-commit hooks configured.
- CI baseline workflow added for lint and smoke-level checks.

### Phase 2: Auth & User Management
- Registration and login APIs implemented.
- Password hashing and JWT token issuance/verification integrated.
- Frontend auth state and token-based session handling integrated.
- Route protection applied to authenticated areas.
- Profile endpoint and frontend profile fetch wiring completed.

### Phase 3: Room Lifecycle (Core Backend)
- Room creation endpoint implemented.
- Join-check logic limited to `LOBBY` state implemented.
- Redis room-state model implemented (`status`, `config`, `questions`, `leaderboard`).
- State transitions implemented: `LOBBY -> GENERATING -> ACTIVE -> FINISHED`.
- Late-join guard for WebSocket handshake/session enforcement added.

### Phase 4: WebSocket Real-Time Engine
- Room-aware WebSocket connection/session manager added.
- Core event protocol implemented: `JOIN_ROOM`, `ROOM_STATE_CHANGE`, `SUBMIT_ANSWER`, `FINAL_RESULTS`.
- Server-authoritative timestamp model implemented (`ends_at`, `test_ends_at`).
- Submission grace window (`+2s`) added.
- Reconnect support and stale session cleanup implemented.

### Phase 5: AI Question Generation
- `QuizGenerator` implemented with LangChain structured output.
- Pydantic schemas introduced and enforced for generated payloads.
- Prompt strategy added for exam/topic-aware generation (e.g., GATE/SSC).
- Retry/self-correction added for schema-validation failures.
- Generated packages persisted to Redis and history storage.

### Phase 6: Quiz Mode
- `mode=QUIZ` room configuration fully implemented.
- Single active question per room flow implemented.
- Per-question timer and auto-advance implemented.
- Auto-advance triggers: timer expiry OR all active participants submitted.
- Mid-quiz leavers excluded from active-submit quorum.
- Live leaderboard update flow implemented.

### Phase 7: Test Mode
- `mode=TEST` room configuration fully implemented.
- Shared question set per room implemented (peered test paper).
- Individual progress/timing implemented per participant.
- Section/topic locking implemented.
- Free navigation within current active section implemented.
- Section submit locks completed section and unlocks next section.
- Users can progress sections independently.
- Early-finished users can leave room.
- Final result publication occurs when all users finish OR global test deadline is reached.

### Phase 8: Frontend UX (Quiz + Test)
- Lobby UI completed (config, participant list, start controls).
- Quiz UI completed (single question, countdown, submit state).
- Test UI completed (section panel, question palette, total timer).
- Section lock/submit indicators added.
- Result screen implemented (rank, score, solution/review).
- Loading/empty/error/reconnect states added.

### Phase 9: History, Reports & Analytics
- Persistent session history saved for quiz and test modes.
- History listing screen added with filters (mode/date/topic/exam).
- Detailed attempt report view implemented.
- Section-wise performance insight computation and display added.
- Admin analytics endpoints for room-level data added.

### Phase 10: Security, Reliability & Quality
- Server-side payload validation enforced for client events.
- Anti-cheat checks added for late/duplicate submissions.
- Rate limiting added for auth and room actions.
- Unit tests added for room state machine.
- Integration tests added for WebSocket event flow.
- End-to-end test coverage added for quiz and test flows.
- Structured logging, metrics hooks, and error-monitoring hooks added.

### Phase 11: Release & Production Hardening
- Production env templates and secrets strategy completed.
- SQL migration baseline and seed scripts added.
- Deployment workflow finalized for backend/frontend image pipeline.
- Load-test baseline scaffolding added for concurrent usage validation.
- Rollback and incident response checklist documented.
- v1 release notes and known limitations published.

## Complete Product Flow (Click-by-Click + System Behavior)

### 1. Authentication Flow
1. User opens app and lands on auth screen.
2. User clicks `Register` or `Login` and submits form.
3. Frontend calls auth API.
4. Backend validates credentials, hashes/verifies password, returns JWT.
5. Frontend stores auth token in client auth state.
6. User is redirected to authenticated app area.

### 2. Create Room Flow (Admin)
1. Admin clicks `Create Room`.
2. Admin selects mode: `QUIZ` or `TEST`.
3. Admin sets config (topics, exam types, question counts, timers). Quiz total duration is derived as questions-per-session × time-per-question, while test timing is per section..
4. Admin clicks `Create`.
5. Backend creates room record/state in Redis + persistent storage.
6. Room opens in `LOBBY` state and room code/link is generated.

### 3. Join Room Flow (Participant)
1. User enters room code or link and clicks `Join`.
2. Frontend calls join-check API.
3. Backend verifies room is joinable (`LOBBY`) and user eligibility.
4. Frontend opens WebSocket and sends `JOIN_ROOM` event.
5. Server adds participant session and broadcasts lobby participant update.

### 4. Start Session Flow (Admin)
1. Admin clicks `Start` in lobby.
2. Backend transitions room `LOBBY -> GENERATING`.
3. Question package is generated/fetched and validated.
4. Backend persists package, computes timing metadata, and transitions room to `ACTIVE`.
5. Server broadcasts start payload and timer anchors to all connected users.

### 5. Quiz Mode Runtime Flow
1. User sees only the current question and per-question countdown.
2. User selects option and clicks `Save/Submit`.
3. Frontend emits `SUBMIT_ANSWER` via WebSocket.
4. Backend validates submission (on-time, not duplicate) and records it.
5. Question advances when:
- countdown expires, or
- all currently active participants have submitted.
6. On advance, backend broadcasts next-question payload and new `ends_at`.
7. Leaderboard updates are pushed after scoring events.
8. If a user disconnects/leaves, user is removed from active quorum used for early advance.
9. At final question completion, room transitions to `FINISHED` and results are broadcast.

### 6. Test Mode Runtime Flow
1. User receives full question set grouped by section/topic.
2. User starts in section 1 and can move between questions within that section only.
3. User cannot jump to another section before submitting the current section.
4. User saves answers in any order inside current section.
5. User clicks `Submit Section`.
6. Backend locks that section for that user and unlocks the next section.
7. Different users can be in different sections at the same time.
8. Each user progresses independently while sharing the same test paper blueprint.
9. If user completes all sections early, user can leave room.
10. Final room-level result publication happens when all participants finish or exam end time is reached.

### 7. Reconnect and Reliability Flow
1. If connection drops, frontend enters reconnect state.
2. On reconnect, WebSocket session is re-established.
3. Backend re-syncs authoritative room/user state and timer anchors.
4. User continues from latest valid state without client-side clock authority.

### 8. Results, History, and Reports Flow
1. After room completion, result payload is shown in result screen.
2. User clicks `History`.
3. Frontend requests history API with selected filters.
4. Backend returns attempts across quiz/test sessions.
5. User opens an attempt report.
6. Frontend requests detailed report API.
7. Backend returns question-wise correctness, timing, and section-wise insights.
8. User can revisit past attempts/reports any time from history.

### 9. Security and Guardrail Behavior During Flows
- All realtime payloads are schema-validated server side.
- Duplicate submits are rejected.
- Late submissions outside allowed window are rejected.
- Auth and room actions are rate-limited.
- Structured logs/metrics are emitted for observability and incident handling.

### 10. Release/Operations Flow
1. Team prepares production env values in secret manager.
2. Deployment pipeline builds and publishes backend/frontend images.
3. Migration script is executed on target DB.
4. Smoke checks are executed after deploy.
5. If incident occurs, rollback checklist is followed.
6. Release notes and known limitations are referenced for support/ops communication.

