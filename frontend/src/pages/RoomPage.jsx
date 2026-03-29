import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useDispatch, useSelector } from "react-redux";

import { useAuth } from "../context/AuthContext";
import { API_BASE_URL, request } from "../lib/api";
import { addParticipant, patchRoom, resetSessionViews, setParticipants } from "../store/roomSlice";

function toWsUrl(apiBase, roomId, userId) {
  const url = new URL(apiBase);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = `/ws/rooms/${roomId}`;
  url.search = userId ? `user_id=${encodeURIComponent(userId)}` : "";
  return url.toString();
}

function formatSeconds(ms) {
  if (!ms || ms <= 0) {
    return "00:00";
  }
  const totalSeconds = Math.ceil(ms / 1000);
  const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

export default function RoomPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const { roomId: routeRoomId } = useParams();
  const dispatch = useDispatch();
  const room = useSelector((state) => state.room);

  const {
    mode,
    count,
    timePerQ,
    timePerSection,
    difficulty,
    topics,
    exams,
    roomIdInput,
    roomId,
    roomStatus,
    error,
    info,
    isBusy,
    connectionState,
    ownerId,
    participants,
    endsAt,
    testEndsAt,
    countdown,
    totalQuizQuestions,
    quizQuestionIndex,
    quizQuestion,
    selectedOption,
    submitted,
    finalResults,
    sectionIndex,
    sectionTopic,
    totalSections,
    lockedSections,
    sectionQuestions,
    activeTestQuestionIndex,
    testAnsweredQuestionIndices,
    endVote,
  } = room;

  const socketRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const reconnectAttemptsRef = useRef(0);
  const shouldReconnectRef = useRef(false);
  const pendingAttemptRef = useRef(null);
  const quizQuestionStartRef = useRef(0);
  const currentQuizQuestionIndexRef = useRef(-1);
  const quizSubmitInFlightRef = useRef(false);
  const testQuestionStartRef = useRef({});
  const testAnsweredRef = useRef([]);
  const [presenceToasts, setPresenceToasts] = useState([]);
  const [quizAnsweredUsers, setQuizAnsweredUsers] = useState([]);

  function updateRoom(patch) {
    dispatch(patchRoom(patch));
  }

  function pushPresenceToast(message) {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    setPresenceToasts((prev) => [...prev, { id, message }]);
    setTimeout(() => {
      setPresenceToasts((prev) => prev.filter((toast) => toast.id !== id));
    }, 3000);
  }

  useEffect(() => {
    if (roomStatus !== "ACTIVE") {
      updateRoom({ countdown: 0 });
      return undefined;
    }

    const timer = setInterval(() => {
      const target = mode === "QUIZ" ? endsAt : testEndsAt;
      updateRoom({ countdown: Math.max(0, target - Date.now()) });
    }, 250);
    return () => clearInterval(timer);
  }, [endsAt, mode, roomStatus, testEndsAt]);

  useEffect(() => {
    return () => {
      shouldReconnectRef.current = false;
      if (socketRef.current) {
        socketRef.current.close();
        socketRef.current = null;
      }
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    };
  }, []);

  
  useEffect(() => {
    updateRoom({ selectedOption: -1 });
  }, [activeTestQuestionIndex]);

  useEffect(() => {
    testAnsweredRef.current = testAnsweredQuestionIndices;
  }, [testAnsweredQuestionIndices]);

  useEffect(() => {
    if (mode === "QUIZ") {
      setQuizAnsweredUsers([]);
    }
  }, [mode, quizQuestionIndex]);


  useEffect(() => {
    if (!user?.username) {
      return;
    }

    let cancelled = false;

    async function syncRoomRoute() {
      if (!routeRoomId) {
        const ongoing = await request(`/rooms/current?user_id=${encodeURIComponent(user.username)}`);
        if (cancelled) {
          return;
        }
        if (ongoing?.has_ongoing && ongoing.room_id && ongoing.status && ongoing.status !== "FINISHED") {
          navigate(`/room/${ongoing.room_id}`, { replace: true });
          return;
        }

        shouldReconnectRef.current = false;
        if (socketRef.current) {
          socketRef.current.close();
          socketRef.current = null;
        }
        if (reconnectTimerRef.current) {
          clearTimeout(reconnectTimerRef.current);
          reconnectTimerRef.current = null;
        }
        reconnectAttemptsRef.current = 0;
        updateRoom({
          roomId: "",
          roomIdInput: "",
          roomStatus: "IDLE",
          ownerId: "",
          participants: [],
          connectionState: "disconnected",
          info: "",
          error: "",
        });
        return;
      }

      const check = await request(`/rooms/${routeRoomId}/join-check?user_id=${encodeURIComponent(user.username)}`);
      if (cancelled) {
        return;
      }

      if (!check.can_join) {
        updateRoom({
          error: `Quiz already started or closed (status: ${check.status}).`,
          roomStatus: check.status,
          roomId: "",
        });
        navigate("/room", { replace: true });
        return;
      }

      updateRoom({
        roomId: routeRoomId,
        roomIdInput: routeRoomId,
        roomStatus: check.status,
        ownerId: "",
        participants: [],
        error: "",
      });
      connectSocket(routeRoomId);
    }
    syncRoomRoute().catch(() => {
      if (!cancelled) {
        updateRoom({ error: "Unable to resolve current room" });
      }
    });

    return () => {
      cancelled = true;
    };
  }, [routeRoomId, user?.username]);

  function parseCsv(value) {
    return value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }

  async function persistAttempt(attempt) {
    if (!attempt || !roomId) {
      return;
    }

    try {
      await request("/history/attempt", {
        method: "POST",
        body: JSON.stringify({
          room_id: roomId,
          user_id: user.username,
          question_index: attempt.question_index,
          selected_option: attempt.selected_option,
          time_taken_ms: attempt.time_taken_ms,
        }),
      });
    } catch {
      // Do not block gameplay if history write fails.
    }
  }

  async function createRoom() {
    updateRoom({ error: "", info: "", isBusy: true });
    dispatch(resetSessionViews());

    try {
      const response = await request(`/rooms/create?user_id=${encodeURIComponent(user.username)}`, {
        method: "POST",
        body: JSON.stringify({
          config: {
            mode,
            count: Number(count),
            ...(mode === "QUIZ"
              ? { time_per_q: Number(timePerQ) }
              : { time_per_section: Number(timePerSection) }),
            difficulty,
            topics: parseCsv(topics),
            exams: parseCsv(exams),
          },
        }),
      });

      updateRoom({
        roomId: response.room_id,
        roomIdInput: response.room_id,
        roomStatus: response.status,
        ownerId: user.username,
        participants: [user.username],
        info: `Room created: ${response.room_id}`,
      });
      navigate(`/room/${response.room_id}`);
    } catch (createError) {
      updateRoom({ error: createError.message });
    } finally {
      updateRoom({ isBusy: false });
    }
  }

  async function joinRoom() {
    updateRoom({ error: "", info: "", isBusy: true });

    try {
      const response = await request(`/rooms/${roomIdInput}/join-check?user_id=${encodeURIComponent(user.username)}`);
      if (!response.can_join) {
        updateRoom({
          error: `Quiz already started or closed (status: ${response.status}).`,
          roomStatus: response.status,
          roomId: "",
        });
        return;
      }
      updateRoom({ roomId: roomIdInput, roomStatus: response.status });
      navigate(`/room/${roomIdInput}`);
    } catch (joinError) {
      updateRoom({ error: joinError.message });
    } finally {
      updateRoom({ isBusy: false });
    }
  }

  function connectSocket(targetRoomId) {
    if (!targetRoomId || !user?.username) {
      return;
    }

    shouldReconnectRef.current = true;
    if (socketRef.current) {
      socketRef.current.close();
    }

    const ws = new WebSocket(toWsUrl(API_BASE_URL, targetRoomId, user.username));
    socketRef.current = ws;
    updateRoom({ connectionState: "connecting" });

    ws.onopen = () => {
      updateRoom({ connectionState: "connected" });
      reconnectAttemptsRef.current = 0;
      ws.send(
        JSON.stringify({
          type: "JOIN_ROOM",
          user_id: user.username,
        }),
      );
    };

    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        handleSocketEvent(payload);
      } catch {
        updateRoom({ error: "Failed to parse realtime event" });
      }
    };

    ws.onclose = (event) => {
      updateRoom({ connectionState: "disconnected" });
      if (event.code === 4403) {
        updateRoom({ error: "Quiz already started. New users cannot join this room now." });
        return;
      }
      if (!shouldReconnectRef.current) {
        return;
      }
      scheduleReconnect(targetRoomId);
    };

    ws.onerror = () => {
      updateRoom({ connectionState: "error" });
    };
  }

  function scheduleReconnect(targetRoomId) {
    if (!targetRoomId) {
      return;
    }
    if (!shouldReconnectRef.current) {
      return;
    }
    if (reconnectAttemptsRef.current >= 5) {
      updateRoom({ error: "Realtime connection lost. Please reconnect manually." });
      return;
    }

    reconnectAttemptsRef.current += 1;
    updateRoom({ connectionState: "reconnecting" });

    reconnectTimerRef.current = setTimeout(() => {
      if (!shouldReconnectRef.current) {
        return;
      }
      connectSocket(targetRoomId);
    }, 1000 * reconnectAttemptsRef.current);
  }

  function handleSocketEvent(payload) {
    if (payload.type === "ERROR") {
      updateRoom({ error: payload.detail ?? "Unknown realtime error" });
      return;
    }

    if (payload.type === "JOIN_ROOM_ACK") {
      const joinedQuestionIndex = payload.current_question ?? 0;
      currentQuizQuestionIndexRef.current = joinedQuestionIndex;
      quizSubmitInFlightRef.current = false;

      updateRoom({
        roomStatus: payload.status,
        endsAt: payload.ends_at ?? 0,
        testEndsAt: payload.test_ends_at ?? 0,
        ownerId: payload.owner_id ?? ownerId,
        totalQuizQuestions: payload.total_questions ?? totalQuizQuestions,
        endVote: payload.end_vote ?? null,
        info: "",
        error: "",
      });
      dispatch(setParticipants(payload.participants ?? [payload.user_id].filter(Boolean)));

      if ((payload.test_ends_at ?? 0) > 0) {
        updateRoom({ mode: "TEST" });
      }

      if (payload.question_data) {
        updateRoom({
          mode: "QUIZ",
          quizQuestion: payload.question_data,
          quizQuestionIndex: joinedQuestionIndex,
          selectedOption: -1,
          submitted: false,
          error: "",
        });
        quizQuestionStartRef.current = Date.now();
      }
      return;
    }

    if (payload.type === "TEST_SECTION_START") {
      updateRoom({
        mode: "TEST",
        roomStatus: "ACTIVE",
        sectionIndex: payload.section_index ?? 0,
        sectionTopic: payload.section_topic ?? "",
        totalSections: payload.total_sections ?? 0,
        lockedSections: payload.locked_sections ?? [],
        sectionQuestions: payload.questions ?? [],
        testEndsAt: payload.test_ends_at ?? 0,
        info: `Section ${payload.section_index + 1} started: ${payload.section_topic}`,
        testAnsweredQuestionIndices: [],
      });
      testAnsweredRef.current = [];
      const firstQuestion = (payload.questions ?? [])[0];
      updateRoom({ activeTestQuestionIndex: firstQuestion?.question_index ?? -1 });
      if (firstQuestion?.question_index !== undefined) {
        testQuestionStartRef.current[firstQuestion.question_index] = Date.now();
      }
      return;
    }

    if (payload.type === "QUESTION_NAVIGATED") {
      updateRoom({ activeTestQuestionIndex: payload.question_index });
      testQuestionStartRef.current[payload.question_index] = Date.now();
      return;
    }

    if (payload.type === "ROOM_STATE_CHANGE") {
      const patch = {
        roomStatus: payload.status,
        endsAt: payload.ends_at ?? 0,
        testEndsAt: payload.test_ends_at ?? 0,
      };
      if (payload.status === "GENERATING") {
        patch.info = "Admin is generating questions. Please wait...";
      }
      if (payload.status === "ACTIVE") {
        patch.info = "";
        patch.error = "";
      }
      updateRoom(patch);

      if ((payload.test_ends_at ?? 0) > 0) {
        updateRoom({ mode: "TEST" });
      }
      if ((payload.ends_at ?? 0) > 0) {
        updateRoom({ mode: "QUIZ" });
      }
      if (payload.status !== "ACTIVE") {
        setQuizAnsweredUsers([]);
        patch.endVote = null;
      }
      return;
    }

    if (payload.type === "NEXT_QUESTION") {
      const nextQuizIndex = payload.question_index ?? 0;
      currentQuizQuestionIndexRef.current = nextQuizIndex;
      quizSubmitInFlightRef.current = false;

      updateRoom({
        mode: "QUIZ",
        quizQuestionIndex: nextQuizIndex,
        totalQuizQuestions: payload.total_questions ?? totalQuizQuestions,
        quizQuestion: payload.question_data ?? null,
        endsAt: payload.ends_at ?? 0,
        selectedOption: -1,
        submitted: false,
        error: "",
        info: "",
      });
      quizQuestionStartRef.current = Date.now();
      setQuizAnsweredUsers([]);
      return;
    }

    if (payload.type === "USER_JOINED") {
      if (Array.isArray(payload.participants)) {
        dispatch(setParticipants(payload.participants));
      } else {
        dispatch(addParticipant(payload.user_id));
      }
      if (payload.user_id && payload.user_id !== user.username) {
        pushPresenceToast(`${payload.user_id} joined the room`);
      }
      return;
    }

    if (payload.type === "USER_LEFT") {
      if (Array.isArray(payload.participants)) {
        dispatch(setParticipants(payload.participants));
      }
      if (payload.user_id && payload.user_id !== user.username) {
        pushPresenceToast(`${payload.user_id} left the room`);
      }
      return;
    }

    if (payload.type === "SUBMIT_ANSWER_ACK") {
      if (mode === "QUIZ" && payload.question_index === currentQuizQuestionIndexRef.current && payload.user_id) {
        setQuizAnsweredUsers((prev) => (prev.includes(payload.user_id) ? prev : [...prev, payload.user_id]));
      }
      return;
    }

    if (payload.type === "SUBMIT_ACCEPTED") {
      if (mode === "QUIZ" && payload.question_index === currentQuizQuestionIndexRef.current) {
        updateRoom({ submitted: true });
        quizSubmitInFlightRef.current = false;
      }
      if (payload.current_section !== undefined || payload.test_ends_at !== undefined) {
        const questionIndex = payload.question_index;
        if (typeof questionIndex === "number") {
          const currentAnswered = Array.isArray(testAnsweredRef.current) ? testAnsweredRef.current : [];
          const nextAnswered = currentAnswered.includes(questionIndex) ? currentAnswered : [...currentAnswered, questionIndex];
          testAnsweredRef.current = nextAnswered;
          updateRoom({ testAnsweredQuestionIndices: nextAnswered });
        }
      }
      if (pendingAttemptRef.current) {
        persistAttempt(pendingAttemptRef.current);
        pendingAttemptRef.current = null;
      }
      return;
    }

    if (payload.type === "SUBMIT_REJECTED") {
      pendingAttemptRef.current = null;
      quizSubmitInFlightRef.current = false;

      if (mode === "QUIZ" && String(payload.detail || "").toLowerCase().includes("already submitted")) {
        updateRoom({ submitted: true, error: payload.detail ?? "Submission rejected" });
      } else {
        updateRoom({ submitted: false, error: payload.detail ?? "Submission rejected" });
      }
      return;
    }

    if (payload.type === "SECTION_SUBMIT_ACCEPTED") {
      if (payload.finished) {
        updateRoom({ info: "You finished the test. Waiting for final results." });
      } else {
        updateRoom({ info: `Moved to section ${payload.current_section + 1}` });
      }
      return;
    }

    if (payload.type === "SECTION_SUBMIT_REJECTED" || payload.type === "NAVIGATION_REJECTED") {
      updateRoom({ error: payload.detail ?? "Action rejected" });
      return;
    }

    if (payload.type === "END_SESSION_VOTE_UPDATE") {
      updateRoom({
        endVote: {
          active: true,
          requestedBy: payload.requested_by ?? "",
          yesVoters: payload.yes_voters ?? [],
          requiredVotes: payload.required_votes ?? 0,
          remainingVotes: payload.remaining_votes ?? 0,
        },
        info: payload.remaining_votes > 0
          ? `End vote in progress (${(payload.yes_voters ?? []).length}/${payload.required_votes ?? 0})`
          : "All votes received. Ending session...",
      });
      return;
    }

    if (payload.type === "END_SESSION_VOTE_REJECTED") {
      updateRoom({ error: payload.detail ?? "Unable to register end vote" });
      return;
    }

    if (payload.type === "END_SESSION_VOTE_PASSED") {
      updateRoom({ info: "All participants voted yes. Ending session..." });
      return;
    }

    if (payload.type === "FINAL_RESULTS") {
      updateRoom({ finalResults: payload.leaderboard ?? [], roomStatus: "FINISHED", endsAt: 0, testEndsAt: 0, countdown: 0, info: "", endVote: null });
    }
  }

  async function startGeneration() {
    if (!roomId) {
      return;
    }

    if (ownerId && ownerId !== user.username) {
      updateRoom({ info: "Ask the room creator to start the session." });
      return;
    }

    updateRoom({ error: "", info: "", isBusy: true });

    try {
      const response = await request(`/rooms/${roomId}/generate-questions?user_id=${encodeURIComponent(user.username)}`, {
        method: "POST",
      });
      updateRoom({
        roomStatus: response.status,
        endsAt: response.ends_at ?? 0,
        testEndsAt: response.test_ends_at ?? 0,
        mode: (response.test_ends_at ?? 0) > 0 ? "TEST" : "QUIZ",
        totalQuizQuestions: response.question_count ?? 0,
        info: "",
      });
    } catch (generationError) {
      updateRoom({ error: generationError.message });
    } finally {
      updateRoom({ isBusy: false });
    }
  }

  function sendSocket(event) {
    if (!socketRef.current || socketRef.current.readyState !== WebSocket.OPEN) {
      updateRoom({ error: "WebSocket is not connected" });
      return false;
    }
    socketRef.current.send(JSON.stringify(event));
    return true;
  }

  function submitQuizAnswer() {
    if (selectedOption < 0 || submitted || quizSubmitInFlightRef.current) {
      return;
    }

    const startedAt = quizQuestionStartRef.current || Date.now();
    pendingAttemptRef.current = {
      question_index: quizQuestionIndex,
      selected_option: selectedOption,
      time_taken_ms: Math.max(0, Date.now() - startedAt),
    };

    quizSubmitInFlightRef.current = true;
    updateRoom({ submitted: true, error: "" });

    const sent = sendSocket({
      type: "SUBMIT_ANSWER",
      question_index: quizQuestionIndex,
      selected_option: selectedOption,
    });

    if (!sent) {
      quizSubmitInFlightRef.current = false;
      updateRoom({ submitted: false });
    }
  }

  function submitTestAnswer() {
    if (activeTestQuestionIndex < 0 || selectedOption < 0) {
      return;
    }

    const startedAt = testQuestionStartRef.current[activeTestQuestionIndex] || Date.now();
    pendingAttemptRef.current = {
      question_index: activeTestQuestionIndex,
      selected_option: selectedOption,
      time_taken_ms: Math.max(0, Date.now() - startedAt),
    };

    sendSocket({
      type: "SUBMIT_ANSWER",
      question_index: activeTestQuestionIndex,
      selected_option: selectedOption,
    });
  }

  function navigateToTestQuestion(questionIndex) {
    updateRoom({ activeTestQuestionIndex: questionIndex });
    sendSocket({ type: "NAVIGATE_QUESTION", question_index: questionIndex });
  }

  function submitSection() {
    sendSocket({ type: "SUBMIT_SECTION", section_index: sectionIndex });
  }

  function voteToEndSession() {
    updateRoom({ error: "" });
    sendSocket({ type: "END_SESSION_VOTE" });
  }

  const hasVotedToEnd = Boolean(endVote?.yesVoters?.includes(user?.username));

  const activeTestQuestion = useMemo(
    () => sectionQuestions.find((question) => question.question_index === activeTestQuestionIndex) ?? null,
    [sectionQuestions, activeTestQuestionIndex],
  );

  return (
    <section className="room-page">
      <h2>Room Workspace</h2>

      <div className="status-strip">
        <span>Room: {roomId || "not selected"}</span>
        <span>Status: {roomStatus}</span>
        <span>Socket: {connectionState}</span>
        <span>Timer: {formatSeconds(countdown)}</span>
      </div>

      {error ? <p className="error-text">{error}</p> : null}
      {info ? <p className="info-text">{info}</p> : null}

      <div className="room-layout" style={{ display: 'grid', gridTemplateColumns: roomId ? '1fr 300px' : '1fr', gap: '2rem', alignItems: 'start', position: 'relative' }}>
        <div className="room-main" style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
          {!roomId ? (
        <div className="split-hero animate-slide-up">
          <div className="empty-state">
            <svg viewBox="0 0 400 400" fill="none" xmlns="http://www.w3.org/2000/svg">
              <circle cx="200" cy="200" r="100" stroke="#8b5cf6" strokeWidth="2" strokeDasharray="10 10">
                <animateTransform attributeName="transform" type="rotate" from="0 200 200" to="360 200 200" dur="30s" repeatCount="indefinite"/>
              </circle>
              <circle cx="200" cy="200" r="130" stroke="#3b82f6" strokeWidth="1.5" strokeDasharray="5 15">
                <animateTransform attributeName="transform" type="rotate" from="360 200 200" to="0 200 200" dur="40s" repeatCount="indefinite"/>
              </circle>
              <path d="M200 130L260 240H140L200 130Z" fill="url(#core_neon)"/>
              <defs>
                <linearGradient id="core_neon" x1="200" y1="130" x2="200" y2="240" gradientUnits="userSpaceOnUse">
                  <stop stopColor="#a78bfa" stopOpacity="0.8"/>
                  <stop offset="1" stopColor="#3b82f6" stopOpacity="0.3"/>
                </linearGradient>
              </defs>
            </svg>
            <h3 style={{color: 'var(--text-primary)', marginBottom: '0'}}>Waiting for connection...</h3>
            <p className="muted-text">Create or join a workspace to begin.</p>
          </div>
          <div className="card-grid" style={{gridTemplateColumns: 'minmax(280px, 1fr)'}}>
            <article className="panel">
              <h3>Create Room</h3>
              <div className="form-grid">
                <label>Mode</label>
                <select value={mode} onChange={(event) => updateRoom({ mode: event.target.value })}>
                  <option value="QUIZ">Quiz</option>
                  <option value="TEST">Test</option>
                </select>

                <label>Difficulty</label>
                <select value={difficulty} onChange={(event) => updateRoom({ difficulty: event.target.value })}>
                  <option value="easy">Easy</option>
                  <option value="medium">Medium</option>
                  <option value="hard">Hard</option>
                </select>

                <label>Questions / Topic</label>
                <input
                  type="number"
                  min="1"
                  value={count}
                  onChange={(event) => updateRoom({ count: event.target.value })}
                />

                {mode === "QUIZ" ? (
                  <>
                    <label>Time / Question (sec)</label>
                    <input
                      type="number"
                      min="5"
                      value={timePerQ}
                      onChange={(event) => updateRoom({ timePerQ: event.target.value })}
                    />
                  </>
                ) : null}

                {mode === "TEST" ? (
                  <>
                    <label>Time / Section (sec)</label>
                    <input
                      type="number"
                      min="30"
                      value={timePerSection}
                      onChange={(event) => updateRoom({ timePerSection: event.target.value })}
                    />
                  </>
                ) : null}
              </div>
              <button type="button" disabled={isBusy} onClick={createRoom} style={{marginTop: '1.25rem', width: '100%'}}>
                {isBusy ? "Creating..." : "Create Room"}
              </button>
            </article>

            <article className="panel">
              <h3>Join Existing Room</h3>
              <div className="form-grid">
                <label>Room ID</label>
                <input value={roomIdInput} onChange={(event) => updateRoom({ roomIdInput: event.target.value })} />
              </div>
              <button type="button" disabled={isBusy || !roomIdInput} onClick={joinRoom} style={{marginTop: '1.25rem', width: '100%'}}>
                Join Room
              </button>
            </article>
          </div>
        </div>
      ) : null}

      {roomId && roomStatus === "LOBBY" ? (
        <article className="panel">
          <h3>Lobby</h3>
          <p>Participants: {participants.length ? participants.join(", ") : "none yet"}</p>
          {ownerId !== user.username ? (
            <p className="muted-text">
              {ownerId ? "Ask the room creator to start the session." : "Syncing room admin details..."}
            </p>
          ) : (
            <button type="button" disabled={isBusy} onClick={startGeneration}>
              {isBusy ? "Generating..." : "Start Session"}
            </button>
          )}
        </article>
      ) : null}

      {roomStatus === "GENERATING" ? (
        <article className="panel">
          <h3>Generating Questions</h3>
          <p className="muted-text">Room admin is generating questions. Please wait...</p>
        </article>
      ) : null}

      {roomStatus === "ACTIVE" && mode === "QUIZ" ? (
        <article className="panel">
          <h3>Quiz Player</h3>
          {!quizQuestion ? <p className="muted-text">Waiting for current question...</p> : null}
          {quizQuestion ? (
            <>
              <p className="question-text">
                Q{quizQuestionIndex + 1}/{Math.max(totalQuizQuestions, quizQuestionIndex + 1)}. {quizQuestion.text}
              </p>
              <div className="option-list">
                {quizQuestion.options?.map((option, index) => (
                  <button
                    type="button"
                    key={`${option}-${index}`}
                    className={selectedOption === index ? "option-btn active" : "option-btn"}
                    onClick={() => updateRoom({ selectedOption: index })}
                    disabled={submitted}
                  >
                    {String.fromCharCode(65 + index)}. {option}
                  </button>
                ))}
              </div>
              <button type="button" disabled={selectedOption < 0 || submitted} onClick={submitQuizAnswer}>
                {submitted ? "Submitted" : "Submit Answer"}
              </button>
              <div className="action-row" style={{ marginTop: "1rem" }}>
                <button type="button" className="secondary-btn" disabled={hasVotedToEnd} onClick={voteToEndSession}>
                  {hasVotedToEnd ? "Voted to End" : "Vote to End Quiz"}
                </button>
              </div>
              {endVote?.active ? (
                <p className="muted-text">
                  End vote: {endVote.yesVoters?.length ?? 0}/{endVote.requiredVotes ?? participants.length} yes
                  {endVote.requestedBy ? ` (requested by ${endVote.requestedBy})` : ""}
                </p>
              ) : null}
            </>
          ) : null}
        </article>
      ) : null}

      {roomStatus === "ACTIVE" && mode === "TEST" ? (
        <article className="panel">
          <h3>Test Player</h3>
          <p>
            Section {sectionIndex + 1}/{totalSections}: {sectionTopic || "-"}
          </p>

          <div className="section-locks">
            {Array.from({ length: totalSections }).map((_, index) => {
              const isLocked = lockedSections.includes(index);
              const isCurrent = index === sectionIndex;
              return (
                <span key={index} className={isCurrent ? "chip current" : isLocked ? "chip locked" : "chip"}>
                  S{index + 1}
                </span>
              );
            })}
          </div>

          {sectionQuestions.length === 0 ? <p className="muted-text">Waiting for section questions...</p> : null}

          <div className="question-palette">
            {sectionQuestions.map((question, idx) => (
              <button
                key={question.question_index}
                type="button"
                className={testAnsweredQuestionIndices.includes(question.question_index) ? "palette-btn answered" : activeTestQuestionIndex === question.question_index ? "palette-btn active" : "palette-btn"}
                onClick={() => navigateToTestQuestion(question.question_index)}
              >
                Q{idx + 1}
              </button>
            ))}
          </div>

          {activeTestQuestion ? (
            <>
              <p className="question-text">
                Q{Math.max(1, sectionQuestions.findIndex((question) => question.question_index === activeTestQuestion.question_index) + 1)}. {activeTestQuestion.text}
              </p>
              <div className="option-list">
                {activeTestQuestion.options?.map((option, index) => (
                  <button
                    type="button"
                    key={`${option}-${index}`}
                    className={selectedOption === index ? "option-btn active" : "option-btn"}
                    onClick={() => updateRoom({ selectedOption: index })}
                    disabled={testAnsweredQuestionIndices.includes(activeTestQuestionIndex)}
                  >
                    {String.fromCharCode(65 + index)}. {option}
                  </button>
                ))}
              </div>
              <div className="action-row">
                <button
                  type="button"
                  disabled={selectedOption < 0 || testAnsweredQuestionIndices.includes(activeTestQuestionIndex)}
                  onClick={submitTestAnswer}
                >
                  Save Answer
                </button>
                <button type="button" className="secondary-btn" onClick={submitSection}>
                  Submit Section
                </button>
                <button type="button" className="secondary-btn" disabled={hasVotedToEnd} onClick={voteToEndSession}>
                  {hasVotedToEnd ? "Voted to End" : "Vote to End Test"}
                </button>
              </div>
              {endVote?.active ? (
                <p className="muted-text">
                  End vote: {endVote.yesVoters?.length ?? 0}/{endVote.requiredVotes ?? participants.length} yes
                  {endVote.requestedBy ? ` (requested by ${endVote.requestedBy})` : ""}
                </p>
              ) : null}
            </>
          ) : null}
        </article>
      ) : null}

      {roomStatus === "FINISHED" ? (
        <article className="panel">
          <h3>Final Result & Report</h3>
          {finalResults?.length ? (
            <ol>
              {finalResults.map((entry) => (
                <li key={entry.user_id}>
                  {entry.user_id}: {entry.score}
                </li>
              ))}
            </ol>
          ) : (
            <p className="muted-text">No leaderboard data received.</p>
          )}
          <p className="muted-text">Use History page for detailed report and analytics.</p>
        </article>
      ) : null}
        </div>

      {roomId ? (
        <aside className="realtime-sidebar panel" style={{ position: 'sticky', top: '100px', alignSelf: 'start', padding: '1.5rem', margin: 0 }}>
          <h3 style={{ marginTop: 0, marginBottom: '1rem', fontSize: '1.25rem' }}>Participants ({participants.length})</h3>
          <ul className="participant-list">
            {participants.map((participant) => {
              const answered = mode === "QUIZ" && roomStatus === "ACTIVE" && quizAnsweredUsers.includes(participant);
              return (
                <li key={participant} className="participant-item">
                  <span className={answered ? "answer-dot answered" : "answer-dot"} />
                  <span>{participant}</span>
                </li>
              );
            })}
          </ul>

          <div className="presence-toast-stack">
            {presenceToasts.map((toast) => (
              <div key={toast.id} className="presence-toast">{toast.message}</div>
            ))}
          </div>
        </aside>
      ) : null}
      </div>
    </section>
  );
}




























































