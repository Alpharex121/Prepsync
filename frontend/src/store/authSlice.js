import { createAsyncThunk, createSlice } from "@reduxjs/toolkit";

import { request } from "../lib/api";

const STORAGE_KEY = "prepsync_auth";

const initialToken = localStorage.getItem(STORAGE_KEY);

const initialState = {
  token: initialToken,
  user: null,
  isLoading: Boolean(initialToken),
};

export const hydrateSession = createAsyncThunk("auth/hydrateSession", async (_, thunkApi) => {
  const token = thunkApi.getState().auth.token;
  if (!token) {
    return null;
  }

  try {
    const profile = await request("/auth/me", {
      headers: { Authorization: `Bearer ${token}` },
    });
    return profile;
  } catch {
    localStorage.removeItem(STORAGE_KEY);
    return thunkApi.rejectWithValue("Session expired");
  }
});

export const loginUser = createAsyncThunk("auth/loginUser", async ({ username, password }, thunkApi) => {
  try {
    const data = await request("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    localStorage.setItem(STORAGE_KEY, data.access_token);
    return data;
  } catch (error) {
    return thunkApi.rejectWithValue(error.message ?? "Login failed");
  }
});

export const registerUser = createAsyncThunk(
  "auth/registerUser",
  async ({ username, password }, thunkApi) => {
    try {
      const data = await request("/auth/register", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      localStorage.setItem(STORAGE_KEY, data.access_token);
      return data;
    } catch (error) {
      return thunkApi.rejectWithValue(error.message ?? "Registration failed");
    }
  },
);

const authSlice = createSlice({
  name: "auth",
  initialState,
  reducers: {
    logout(state) {
      localStorage.removeItem(STORAGE_KEY);
      state.token = null;
      state.user = null;
      state.isLoading = false;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(hydrateSession.pending, (state) => {
        state.isLoading = true;
      })
      .addCase(hydrateSession.fulfilled, (state, action) => {
        state.user = action.payload;
        state.isLoading = false;
      })
      .addCase(hydrateSession.rejected, (state) => {
        state.token = null;
        state.user = null;
        state.isLoading = false;
      })
      .addCase(loginUser.fulfilled, (state, action) => {
        state.token = action.payload.access_token;
        state.user = { username: action.payload.username };
        state.isLoading = false;
      })
      .addCase(registerUser.fulfilled, (state, action) => {
        state.token = action.payload.access_token;
        state.user = { username: action.payload.username };
        state.isLoading = false;
      });
  },
});

export const { logout } = authSlice.actions;

export default authSlice.reducer;
