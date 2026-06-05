import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { API_BASE } from '../services/apiBase';

export interface User {
  id: string;
  email: string;
  name: string;
  avatar_url: string | null;
  role: 'user' | 'moderator' | 'manager' | 'admin';
  status: 'pending' | 'active' | 'suspended' | 'expired';
  customer_code: string;  // "" = unscoped (admin/legacy); non-empty = bound
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
  // Set by GET /api/admin/users (derived server-side); only present in admin lists.
  cost_blocked?: boolean;
  // Set by GET /api/auth/me — server-side cost thresholds (avoid hard-coding).
  cost_warn_threshold_usd?: number;
  cost_block_threshold_usd_per_day?: number;
}

interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  isAdmin: boolean;
  isManager: boolean;
  isModerator: boolean;
  isPrivileged: boolean;  // admin or manager — drives SQL/technical visibility (moderator excluded)
  canSelectScope: boolean;     // may use the "Viewing as" customer dropdown
  canManageProfile: boolean;   // may generate/view the data intelligence profile
  canAccessDashboard: boolean; // may open the admin dashboard (moderator = view-only)
  isPending: boolean;
  isCustomerScoped: boolean;  // non-admin bound to a customer_code
  login: (email: string, password: string, recaptchaToken: string) => Promise<void>;
  refreshUser: () => Promise<void>;
  logout: () => void;
}

function deriveFlags(user: User | null) {
  const isAdmin = user?.role === 'admin';
  const isManager = user?.role === 'manager';
  const isModerator = user?.role === 'moderator';
  const isPrivileged = isAdmin || isManager;
  return {
    isAdmin,
    isManager,
    isModerator,
    isPrivileged,
    // Moderator gets admin-like reach for these three, but NOT the
    // SQL/technical visibility that isPrivileged grants in the chat.
    canSelectScope: isPrivileged || isModerator,
    canManageProfile: isPrivileged || isModerator,
    canAccessDashboard: isPrivileged || isModerator,
    isPending: user?.status === 'pending',
    isCustomerScoped: !isAdmin && !isManager && !isModerator && !!user?.customer_code,
  };
}

type AuthSetter = (state: Partial<AuthState>) => void;

async function applyAuthResponse(
  response: Response,
  set: AuthSetter,
  fallbackMessage: string,
) {
  if (!response.ok) {
    let detail = fallbackMessage;
    try {
      const err = await response.json();
      if (typeof err?.detail === 'string' && err.detail) detail = err.detail;
    } catch {
      // Body not JSON — keep the fallback.
    }
    throw new Error(detail);
  }
  const data = await response.json();
  set({
    user: data.user,
    token: data.token,
    isAuthenticated: true,
    ...deriveFlags(data.user),
  });
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      token: null,
      isAuthenticated: false,
      isAdmin: false,
      isManager: false,
      isModerator: false,
      isPrivileged: false,
      canSelectScope: false,
      canManageProfile: false,
      canAccessDashboard: false,
      isPending: false,
      isCustomerScoped: false,

      login: async (email: string, password: string, recaptchaToken: string) => {
        const response = await fetch(`${API_BASE}/api/auth/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email, password, recaptcha_token: recaptchaToken }),
        });
        await applyAuthResponse(response, set, 'Login failed');
      },

      refreshUser: async () => {
        const { token } = get();
        if (!token) return;
        const response = await fetch(`${API_BASE}/api/auth/me`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!response.ok) {
          if (response.status === 401) {
            set({ user: null, token: null, isAuthenticated: false, ...deriveFlags(null) });
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
        set({ user: null, token: null, isAuthenticated: false, ...deriveFlags(null) });
        // Clear per-user stores so next login doesn't see stale data
        localStorage.removeItem('datalens-workspaces');
        localStorage.removeItem('datalens-chat');
      },
    }),
    { name: 'datalens-auth' }
  )
);
