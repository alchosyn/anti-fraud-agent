import { useState, useCallback, useEffect } from 'react';
import type { AuthState, UserInfo } from '../types';

const STORAGE_KEY = 'rl_auth';
const BASE = '/api';

function loadFromStorage(): AuthState | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed?.token && parsed?.user) return parsed as AuthState;
    return null;
  } catch {
    return null;
  }
}

function saveToStorage(auth: AuthState) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(auth));
}

function clearStorage() {
  localStorage.removeItem(STORAGE_KEY);
}

export function useAuth() {
  const [auth, setAuth] = useState<AuthState | null>(loadFromStorage);

  // Sync to localStorage whenever auth changes
  useEffect(() => {
    if (auth) {
      saveToStorage(auth);
    } else {
      clearStorage();
    }
  }, [auth]);

  const register = useCallback(
    async (username: string, password: string, displayName?: string) => {
      const res = await fetch(`${BASE}/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username,
          password,
          display_name: displayName || username,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Registration failed' }));
        throw new Error(err.detail || 'Registration failed');
      }
      const data = await res.json();
      const state: AuthState = {
        token: data.access_token,
        user: data.user as UserInfo,
      };
      setAuth(state);
      return state;
    },
    [],
  );

  const login = useCallback(
    async (username: string, password: string) => {
      const res = await fetch(`${BASE}/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Login failed' }));
        throw new Error(err.detail || 'Login failed');
      }
      const data = await res.json();
      const state: AuthState = {
        token: data.access_token,
        user: data.user as UserInfo,
      };
      setAuth(state);
      return state;
    },
    [],
  );

  const logout = useCallback(() => {
    setAuth(null);
  }, []);

  return {
    auth,
    isLoggedIn: auth !== null,
    token: auth?.token ?? null,
    user: auth?.user ?? null,
    register,
    login,
    logout,
  };
}
