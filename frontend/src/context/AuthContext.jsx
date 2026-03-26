import { useEffect, useMemo } from "react";
import { useDispatch, useSelector } from "react-redux";

import { hydrateSession, loginUser, logout as logoutAction, registerUser } from "../store/authSlice";

export function AuthProvider({ children }) {
  const dispatch = useDispatch();
  const token = useSelector((state) => state.auth.token);

  useEffect(() => {
    if (token) {
      dispatch(hydrateSession());
    }
  }, [dispatch, token]);

  return children;
}

export function useAuth() {
  const dispatch = useDispatch();
  const { token, user, isLoading } = useSelector((state) => state.auth);

  return useMemo(
    () => ({
      token,
      user,
      isLoading,
      isAuthenticated: Boolean(token && user),
      async login(username, password) {
        await dispatch(loginUser({ username, password })).unwrap();
      },
      async register(username, password) {
        await dispatch(registerUser({ username, password })).unwrap();
      },
      logout() {
        dispatch(logoutAction());
      },
    }),
    [dispatch, isLoading, token, user],
  );
}

