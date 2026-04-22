import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { API_BASE } from '../services/apiBase';

export interface User {
  id: string;
  email: string;
  name: string;
  avatar_url: string | null;
  role: 'user' | 'manager' | 'admin';
  status: 'pending' | 'active' | 'suspended' | 'expired';
  max_questions_per_day: number;
  max_tokens_per_day: number;
  max_cost_usd_per_month: number;
  expiry_date: string | null;
  total_questions: number;
  total_tokens: number;
  total_cost_usd: number;
  today_questions: number;
  today_tokens: number;
  today_cost_usd: number;
  month_cost_usd: number;
}

interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  isAdmin: boolean;
  isManager: boolean;
  isPrivileged: boolean;  // admin or manager
  isPending: boolean;
  login: (name: string, email: string) => Promise<void>;
  loginWithGoogle: (credential: string) => Promise<void>;
  loginWithGitHub: (code: string) => Promise<void>;
  refreshUser: () => Promise<void>;
  logout: () => void;
}

function deriveFlags(user: User | null) {
  return {
    isAdmin: user?.role === 'admin',
    isManager: user?.role === 'manager',
    isPrivileged: user?.role === 'admin' || user?.role === 'manager',
    isPending: user?.status === 'pending',
  };
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      token: null,
      isAuthenticated: false,
      isAdmin: false,
      isManager: false,
      isPrivileged: false,
      isPending: false,

      login: async (name: string, email: string) => {
        const response = await fetch(`${API_BASE}/api/auth/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, email }),
        });
        if (response.status === 403) {
          const data = await response.json();
          set({
            user: data.user,
            token: data.token,
            isAuthenticated: true,
            ...deriveFlags(data.user),
          });
          return;
        }
        if (!response.ok) throw new Error('Login failed');
        const data = await response.json();
        set({
          user: data.user,
          token: data.token,
          isAuthenticated: true,
          ...deriveFlags(data.user),
        });
      },

      loginWithGoogle: async (credential: string) => {
        const response = await fetch(`${API_BASE}/api/auth/google`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ credential }),
        });
        if (response.status === 403) {
          const data = await response.json();
          set({
            user: data.user,
            token: data.token,
            isAuthenticated: true,
            ...deriveFlags(data.user),
          });
          return;
        }
        if (!response.ok) throw new Error('Google sign-in failed');
        const data = await response.json();
        set({
          user: data.user,
          token: data.token,
          isAuthenticated: true,
          ...deriveFlags(data.user),
        });
      },

      loginWithGitHub: async (code: string) => {
        const response = await fetch(`${API_BASE}/api/auth/github`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ code }),
        });
        if (response.status === 403) {
          const data = await response.json();
          set({
            user: data.user,
            token: data.token,
            isAuthenticated: true,
            ...deriveFlags(data.user),
          });
          return;
        }
        if (!response.ok) throw new Error('GitHub sign-in failed');
        const data = await response.json();
        set({
          user: data.user,
          token: data.token,
          isAuthenticated: true,
          ...deriveFlags(data.user),
        });
      },

      refreshUser: async () => {
        const { token } = get();
        if (!token) return;
        const response = await fetch(`${API_BASE}/api/auth/me`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!response.ok) {
          if (response.status === 401) {
            set({ user: null, token: null, isAuthenticated: false, isAdmin: false, isManager: false, isPrivileged: false, isPending: false });
          }
          return;
        }
        const user: User = await response.json();
        set({
          user,
          isAuthenticated: true,
          ...deriveFlags(user),
        });
      },

      logout: () => {
        set({ user: null, token: null, isAuthenticated: false, isAdmin: false, isManager: false, isPrivileged: false, isPending: false });
        // Clear per-user stores so next login doesn't see stale data
        localStorage.removeItem('datalens-workspaces');
        localStorage.removeItem('datalens-chat');
      },
    }),
    { name: 'datalens-auth' }
  )
);
