import { Component, useCallback, useEffect, useState, type ReactNode } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import LoginPage from './pages/LoginPage';

import WorkspaceView from './pages/WorkspaceView';
import PendingApprovalPage from './pages/PendingApprovalPage';
import AdminDashboard from './pages/AdminDashboard';
import AnalyticsDashboard from './pages/AnalyticsDashboard';
import { useAuthStore } from './store/authStore';
import { useWorkspaceStore } from './store/workspaceStore';

class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  render() {
    if (this.state.error) {
      return (
        <div style={{
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'linear-gradient(135deg, #0f0a1e 0%, #1a1136 100%)',
          fontFamily: "'Inter', system-ui, sans-serif",
        }}>
          <div style={{
            maxWidth: 480,
            width: '90%',
            background: 'rgba(255,255,255,0.06)',
            backdropFilter: 'blur(20px)',
            border: '1px solid rgba(255,255,255,0.1)',
            borderRadius: 20,
            padding: '40px 32px',
            textAlign: 'center',
          }}>
            <div style={{ fontSize: 48, marginBottom: 16 }}>⚠️</div>
            <h2 style={{ color: '#fff', fontSize: 22, fontWeight: 700, margin: '0 0 8px' }}>Something went wrong</h2>
            <p style={{ color: 'rgba(255,255,255,0.5)', fontSize: 14, margin: '0 0 24px', lineHeight: 1.5 }}>
              {this.state.error.message}
            </p>
            <div style={{ display: 'flex', gap: 12, justifyContent: 'center' }}>
              <button
                onClick={() => { this.setState({ error: null }); }}
                style={{
                  padding: '10px 24px', borderRadius: 12, border: '1px solid rgba(255,255,255,0.15)',
                  background: 'rgba(255,255,255,0.08)', color: '#fff', cursor: 'pointer', fontSize: 14, fontWeight: 500,
                }}
              >
                Try Again
              </button>
              <button
                onClick={() => { window.location.href = '/'; }}
                style={{
                  padding: '10px 24px', borderRadius: 12, border: 'none',
                  background: 'linear-gradient(135deg, #6366f1, #4f46e5)', color: '#fff', cursor: 'pointer', fontSize: 14, fontWeight: 600,
                }}
              >
                Back to Home
              </button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

function ProtectedRoute({ children, adminOnly = false, privilegedOnly = false }: { children: ReactNode; adminOnly?: boolean; privilegedOnly?: boolean }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const user = useAuthStore((s) => s.user);

  if (!isAuthenticated) return <Navigate to="/login" replace />;

  // Redirect pending/suspended users to the pending page
  if (user && (user.status === 'pending' || user.status === 'suspended')) {
    return <Navigate to="/pending" replace />;
  }

  // Admin-only routes
  if (adminOnly && user?.role !== 'admin') {
    return <Navigate to="/" replace />;
  }

  // Privileged routes (admin or manager). Moderator is allowed too — the
  // dashboard renders read-only for them and hides the Usage Logs tab.
  if (privilegedOnly && user?.role !== 'admin' && user?.role !== 'manager' && user?.role !== 'moderator') {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
}

function HomeRoute() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const workspaces = useWorkspaceStore((s) => s.workspaces);
  const loadWorkspacesFromBackend = useWorkspaceStore((s) => s.loadWorkspacesFromBackend);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadWorkspacesFromBackend().finally(() => setLoading(false));
  }, [loadWorkspacesFromBackend]);

  if (user?.role === 'admin' || user?.role === 'manager') return <Navigate to="/admin" replace />;
  if (loading) return null;
  const first = workspaces[0]?.id;
  // Only redirect to a workspace that actually exists for this user. Sending
  // them to a hardcoded default they can't access bounces back here → blank page.
  if (first) return <Navigate to={`/workspace/${first}`} replace />;
  return <NoWorkspaces onSignOut={logout} />;
}

function NoWorkspaces({ onSignOut }: { onSignOut: () => void }) {
  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      flexDirection: 'column', gap: 16, background: 'linear-gradient(135deg, #0f0a1e 0%, #1a1136 100%)',
      fontFamily: "'Inter', system-ui, sans-serif", textAlign: 'center', padding: 24,
    }}>
      <div style={{ fontSize: 40 }}>📊</div>
      <h2 style={{ color: '#fff', fontSize: 20, fontWeight: 700, margin: 0 }}>No workspaces yet</h2>
      <p style={{ color: 'rgba(255,255,255,0.55)', fontSize: 14, maxWidth: 360, margin: 0, lineHeight: 1.5 }}>
        You don't have access to any workspace yet. Ask an administrator to add you to one.
      </p>
      <button
        onClick={onSignOut}
        style={{
          marginTop: 8, padding: '10px 24px', borderRadius: 12, border: '1px solid rgba(255,255,255,0.15)',
          background: 'rgba(255,255,255,0.08)', color: '#fff', cursor: 'pointer', fontSize: 14, fontWeight: 500,
        }}
      >
        Sign out
      </button>
    </div>
  );
}

function isJwtExpired(token: string): boolean {
  try {
    const exp = JSON.parse(atob(token.split('.')[1]))?.exp;
    return typeof exp === 'number' && Date.now() / 1000 > exp;
  } catch {
    return false; // Can't decode — let the server reject it via 401
  }
}

// Guards against stale sessions without a blocking network round-trip.
// Checks JWT expiry client-side on mount and whenever the user returns
// to the tab. The apiFetch 401 handler covers mid-request expiry.
function SessionGuard({ children }: { children: ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const logout = useAuthStore((s) => s.logout);

  const checkExpiry = useCallback(() => {
    if (!isAuthenticated) return;
    try {
      const stored = localStorage.getItem('datalens-auth');
      const token = stored ? JSON.parse(stored)?.state?.token : null;
      if (token && isJwtExpired(token)) logout();
    } catch { /* ignore parse errors */ }
  }, [isAuthenticated, logout]);

  useEffect(() => {
    checkExpiry();
    const onFocus = () => { if (document.visibilityState === 'visible') checkExpiry(); };
    document.addEventListener('visibilitychange', onFocus);
    return () => document.removeEventListener('visibilitychange', onFocus);
  }, [checkExpiry]);

  return <>{children}</>;
}

export default function App() {
  return (
    <ErrorBoundary>
      <SessionGuard>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/pending" element={<PendingApprovalPage />} />
        <Route path="/admin" element={<ProtectedRoute privilegedOnly><AdminDashboard /></ProtectedRoute>} />
        <Route path="/analytics" element={<ProtectedRoute privilegedOnly><AnalyticsDashboard /></ProtectedRoute>} />
        <Route path="/" element={<ProtectedRoute><HomeRoute /></ProtectedRoute>} />
        <Route path="/workspace/:workspaceId" element={<ProtectedRoute><ErrorBoundary><WorkspaceView /></ErrorBoundary></ProtectedRoute>} />
      </Routes>
      </SessionGuard>
    </ErrorBoundary>
  );
}
