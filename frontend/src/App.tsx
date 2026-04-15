import { Component, type ReactNode } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import LoginPage from './pages/LoginPage';

import WorkspaceView from './pages/WorkspaceView';
import PendingApprovalPage from './pages/PendingApprovalPage';
import AdminDashboard from './pages/AdminDashboard';
import AnalyticsDashboard from './pages/AnalyticsDashboard';
import { useAuthStore } from './store/authStore';

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

  // Privileged routes (admin or manager)
  if (privilegedOnly && user?.role !== 'admin' && user?.role !== 'manager') {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
}

function HomeRoute() {
  const user = useAuthStore((s) => s.user);
  // Admins & managers land on admin panel
  if (user?.role === 'admin' || user?.role === 'manager') return <Navigate to="/admin" replace />;
  // Regular users go to their first workspace or a simple picker
  return <Navigate to="/admin" replace />;
}

export default function App() {
  return (
    <ErrorBoundary>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/pending" element={<PendingApprovalPage />} />
        <Route path="/admin" element={<ProtectedRoute><AdminDashboard /></ProtectedRoute>} />
        <Route path="/analytics" element={<ProtectedRoute privilegedOnly><AnalyticsDashboard /></ProtectedRoute>} />
        <Route path="/" element={<ProtectedRoute><HomeRoute /></ProtectedRoute>} />
        <Route path="/workspace/:workspaceId" element={<ProtectedRoute><ErrorBoundary><WorkspaceView /></ErrorBoundary></ProtectedRoute>} />
      </Routes>
    </ErrorBoundary>
  );
}
