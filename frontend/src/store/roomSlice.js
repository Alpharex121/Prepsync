import { createSlice } from "@reduxjs/toolkit";

const initialState = {
  mode: "",
  count: "",
  timePerQ: "",
  timePerSection: "",
  difficulty: "",
  topics: "",
  exams: "",

  roomIdInput: "",
  roomId: "",
  roomStatus: "IDLE",
  error: "",
  info: "",
  isBusy: false,

  connectionState: "disconnected",

  ownerId: "",
  participants: [],

  endsAt: 0,
  testEndsAt: 0,
  countdown: 0,

  totalQuizQuestions: 0,
  quizQuestionIndex: 0,
  quizQuestion: null,
  selectedOption: -1,
  submitted: false,

  leaderboard: [],
  finalResults: null,

  sectionIndex: 0,
  sectionTopic: "",
  totalSections: 0,
  lockedSections: [],
  sectionQuestions: [],
  activeTestQuestionIndex: -1,
  testAnsweredQuestionIndices: [],
  endVote: null,
};

function applySessionReset(state) {
  state.totalQuizQuestions = 0;
  state.quizQuestionIndex = 0;
  state.quizQuestion = null;
  state.selectedOption = -1;
  state.submitted = false;
  state.sectionIndex = 0;
  state.sectionTopic = "";
  state.totalSections = 0;
  state.lockedSections = [];
  state.sectionQuestions = [];
  state.activeTestQuestionIndex = -1;
  state.testAnsweredQuestionIndices = [];
  state.finalResults = null;
  state.leaderboard = [];
  state.endVote = null;
}

const roomSlice = createSlice({
  name: "room",
  initialState,
  reducers: {
    patchRoom(state, action) {
      Object.assign(state, action.payload);
    },
    addParticipant(state, action) {
      const userId = String(action.payload || "").trim();
      if (!userId) {
        return;
      }
      if (!state.participants.includes(userId)) {
        state.participants.push(userId);
      }
    },
    setParticipants(state, action) {
      const raw = Array.isArray(action.payload) ? action.payload : [];
      const unique = [];
      for (const userId of raw) {
        const normalized = String(userId || "").trim();
        if (normalized && !unique.includes(normalized)) {
          unique.push(normalized);
        }
      }
      state.participants = unique;
    },
    resetSessionViews(state) {
      applySessionReset(state);
    },
    resetRoomState() {
      return { ...initialState };
    },
  },
});

export const { patchRoom, addParticipant, setParticipants, resetSessionViews, resetRoomState } = roomSlice.actions;

export default roomSlice.reducer;




