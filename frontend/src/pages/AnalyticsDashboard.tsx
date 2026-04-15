import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  BarChart, Bar, LineChart, Line, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import { useAuthStore } from '../store/authStore';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const PALETTE = ['#6366f1', '#f97316', '#10b981', '#8b5cf6', '#ef4444', '#06b6d4', '#ec4899'];

interface DashboardData {
  period: string;
  total_queries: number;
  total_tokens: number;
  total_cost: number;
  avg_duration_ms: number;
  unique_users: number;
  daily_trends: { date: string; queries: number; tokens: number; cost: number; unique_users: number }[];
  top_users: { email: string; queries: number; tokens: number; cost: number }[];
  mode_distribution: Record<string, number>;
  model_distribution: Record<string, number>;
}

function getAuthHeaders(): Record<string, string> {
  try {
    const stored = localStorage.getItem('datalens-auth');
    if (stored) {
      const parsed = JSON.parse(stored);
      const token = parsed?.state?.token;
      if (token) return { Authorization: `Bearer ${token}` };
    }
  } catch { /* ignore */ }
  return {};
}

export default function AnalyticsDashboard() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const [period, setPeriod] = useState('30d');
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<'overview' | 'trends' | 'users' | 'models'>('overview');

  useEffect(() => {
    setLoading(true);
    fetch(`${API_BASE}/api/analytics/dashboard?period=${period}`, { headers: getAuthHeaders() })
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [period]);

  const modeData = data ? Object.entries(data.mode_distribution).map(([name, value]) => ({ name, value })) : [];
  const modelData = data ? Object.entries(data.model_distribution).map(([name, value]) => ({ name: name.split('/').pop() || name, value })) : [];

  return (
    <div className="anl-page">
      {/* Header */}
      <div className="anl-header">
        <button className="anl-back" onClick={() => navigate('/')}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>
        </button>
        <div>
          <h1 className="anl-title">Analytics Dashboard</h1>
          <p className="anl-subtitle">
            {user?.role === 'admin' ? 'Global overview' : 'Your workspaces'}
          </p>
        </div>
        <div className="anl-period-selector">
          {['7d', '30d', '90d'].map((p) => (
            <button key={p} className={`anl-period-btn ${period === p ? 'anl-period-btn--active' : ''}`} onClick={() => setPeriod(p)}>
              {p === '7d' ? '7 Days' : p === '30d' ? '30 Days' : '90 Days'}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="anl-loading">Loading analytics...</div>
      ) : !data ? (
        <div className="anl-loading">No analytics data available yet. Start asking questions to generate data.</div>
      ) : (
        <>
          {/* Stat Cards */}
          <div className="anl-stats">
            <div className="anl-stat-card">
              <div className="anl-stat-value">{data.total_queries.toLocaleString()}</div>
              <div className="anl-stat-label">Total Queries</div>
            </div>
            <div className="anl-stat-card">
              <div className="anl-stat-value">{data.unique_users}</div>
              <div className="anl-stat-label">Active Users</div>
            </div>
            <div className="anl-stat-card">
              <div className="anl-stat-value">{data.total_tokens.toLocaleString()}</div>
              <div className="anl-stat-label">Tokens Used</div>
            </div>
            <div className="anl-stat-card">
              <div className="anl-stat-value">${data.total_cost.toFixed(2)}</div>
              <div className="anl-stat-label">Total Cost</div>
            </div>
            <div className="anl-stat-card">
              <div className="anl-stat-value">{(data.avg_duration_ms / 1000).toFixed(1)}s</div>
              <div className="anl-stat-label">Avg Response</div>
            </div>
          </div>

          {/* Tabs */}
          <div className="anl-tabs">
            {(['overview', 'trends', 'users', 'models'] as const).map((t) => (
              <button key={t} className={`anl-tab ${activeTab === t ? 'anl-tab--active' : ''}`} onClick={() => setActiveTab(t)}>
                {t === 'overview' ? 'Query Trends' : t === 'trends' ? 'Cost Trends' : t === 'users' ? 'User Activity' : 'Model Usage'}
              </button>
            ))}
          </div>

          {/* Tab Content */}
          <div className="anl-content">
            {activeTab === 'overview' && (
              <div className="anl-chart-card">
                <h3 className="anl-chart-title">Daily Queries</h3>
                <ResponsiveContainer width="100%" height={320}>
                  <BarChart data={data.daily_trends}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                    <XAxis dataKey="date" tick={{ fill: '#94a3b8', fontSize: 11 }} tickFormatter={(v) => v.slice(5)} />
                    <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} />
                    <Tooltip contentStyle={{ background: 'rgba(15,10,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 12, color: '#fff' }} />
                    <Bar dataKey="queries" fill="#6366f1" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="unique_users" fill="#10b981" radius={[4, 4, 0, 0]} />
                    <Legend />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            {activeTab === 'trends' && (
              <div className="anl-chart-card">
                <h3 className="anl-chart-title">Daily Cost & Tokens</h3>
                <ResponsiveContainer width="100%" height={320}>
                  <LineChart data={data.daily_trends}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                    <XAxis dataKey="date" tick={{ fill: '#94a3b8', fontSize: 11 }} tickFormatter={(v) => v.slice(5)} />
                    <YAxis yAxisId="left" tick={{ fill: '#94a3b8', fontSize: 11 }} />
                    <YAxis yAxisId="right" orientation="right" tick={{ fill: '#94a3b8', fontSize: 11 }} />
                    <Tooltip contentStyle={{ background: 'rgba(15,10,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 12, color: '#fff' }} />
                    <Line yAxisId="left" dataKey="cost" stroke="#f97316" strokeWidth={2} dot={false} name="Cost ($)" />
                    <Line yAxisId="right" dataKey="tokens" stroke="#6366f1" strokeWidth={2} dot={false} name="Tokens" />
                    <Legend />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}

            {activeTab === 'users' && (
              <div className="anl-chart-card">
                <h3 className="anl-chart-title">Top Users by Queries</h3>
                <div className="anl-user-table">
                  <div className="anl-user-row anl-user-row--header">
                    <span>User</span>
                    <span>Queries</span>
                    <span>Tokens</span>
                    <span>Cost</span>
                  </div>
                  {data.top_users.map((u, i) => (
                    <div key={u.email} className="anl-user-row">
                      <span className="anl-user-email">
                        <span className="anl-user-rank">{i + 1}</span>
                        {u.email}
                      </span>
                      <span>{u.queries.toLocaleString()}</span>
                      <span>{u.tokens.toLocaleString()}</span>
                      <span>${u.cost.toFixed(4)}</span>
                    </div>
                  ))}
                  {data.top_users.length === 0 && <div className="anl-empty">No user activity yet</div>}
                </div>
              </div>
            )}

            {activeTab === 'models' && (
              <div className="anl-chart-grid">
                <div className="anl-chart-card">
                  <h3 className="anl-chart-title">Analysis Mode Distribution</h3>
                  <ResponsiveContainer width="100%" height={280}>
                    <PieChart>
                      <Pie data={modeData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={100} label={(props: any) => `${props.name ?? ''} ${((props.percent ?? 0) * 100).toFixed(0)}%`}>
                        {modeData.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
                      </Pie>
                      <Tooltip contentStyle={{ background: 'rgba(15,10,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 12, color: '#fff' }} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="anl-chart-card">
                  <h3 className="anl-chart-title">Model Usage</h3>
                  <ResponsiveContainer width="100%" height={280}>
                    <PieChart>
                      <Pie data={modelData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={100} label={(props: any) => `${props.name ?? ''} ${((props.percent ?? 0) * 100).toFixed(0)}%`}>
                        {modelData.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
                      </Pie>
                      <Tooltip contentStyle={{ background: 'rgba(15,10,30,0.95)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 12, color: '#fff' }} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
