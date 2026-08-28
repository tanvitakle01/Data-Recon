import { useCallback, useEffect, useMemo, useState } from "react";
import { AuthContext } from "./authContextObject";
import { registerUnauthorizedHandler } from "../services/api";
import * as authApi from "./authApi";

/**
 * Mirrors the existing per-feature Context convention — plain
 * useState/useCallback, no library. The difference here is every mutation is
 * a real network call: this app has no client-side session of its own, the
 * httpOnly cookie is the only session, and this context just reflects what
 * the backend already decided.
 */
export function AuthProvider({ children }) {
  const [status, setStatus] = useState("loading"); // loading | authenticated | anonymous
  const [user, setUser] = useState(null);

  const clearSession = useCallback(() => {
    setUser(null);
    setStatus("anonymous");
  }, []);

  useEffect(() => {
    registerUnauthorizedHandler(clearSession);
  }, [clearSession]);

  useEffect(() => {
    authApi
      .fetchCurrentUser()
      .then((data) => {
        setUser(data);
        setStatus("authenticated");
      })
      .catch(() => {
        setUser(null);
        setStatus("anonymous");
      });
  }, []);

  const signUp = useCallback(async (fields) => {
    const data = await authApi.signUp(fields);
    setUser(data);
    setStatus("authenticated");
    return data;
  }, []);

  const signIn = useCallback(async (fields) => {
    const data = await authApi.signIn(fields);
    setUser(data);
    setStatus("authenticated");
    return data;
  }, []);

  const signOut = useCallback(async () => {
    try {
      await authApi.signOut();
    } finally {
      clearSession();
    }
  }, [clearSession]);

  const requestPasswordReset = useCallback((email) => authApi.requestPasswordReset(email), []);
  const confirmPasswordReset = useCallback((args) => authApi.confirmPasswordReset(args), []);

  const value = useMemo(
    () => ({ status, user, signUp, signIn, signOut, requestPasswordReset, confirmPasswordReset }),
    [status, user, signUp, signIn, signOut, requestPasswordReset, confirmPasswordReset]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
