import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Users, Activity, DollarSign, Clock, Check, X, Trash2,
  Settings, Loader2, AlertTriangle, RefreshCw, Plus, UserPlus,
  MessageSquare, ChevronDown, Database, BarChart3,
  Shield, Search, ChevronRight, LayoutDashboard,
  Building2, UserCog, ScrollText, TrendingUp, LogOut, Plug,
} from 'lucide-react';
import { useAuthStore, type User } from '../store/authStore';
import { useWorkspaceStore } from '../store/workspaceStore';
import CreateWorkspaceDialog from '../components/workspace/CreateWorkspaceDialog';
import ApiToolManager from '../components/workspace/ApiToolManager';
import type { CreateWorkspaceResult } from '../components/workspace/CreateWorkspaceDialog';
import type { ConnectionInfo } from '../types/connection';
import { createWorkspaceOnBackend } from '../services/api';
import { API_BASE } from '../services/apiBase';

type Section = 'dashboard' | 'workspaces' | 'managers' | 'users' | 'usage';
type UserFilter = 'all' | 'pending' | 'active' | 'suspended';

/* ─── Types ─── */
interface WorkspaceMember {
  email: string;
  name: string;
  avatar_url: string;
  status: string;
  added_at: string;
}

interface WorkspaceOwner {
  id: string;
  name: string;
  email: string;
  avatar_url: string;
  role: string;
}

interface WorkspaceMetrics {
  total_queries: number;
  total_tokens: number;
  total_cost: number;
}

interface AdminWorkspace {
  id: string;
  name: string;
  description: string;
  icon: string;
  created_at: string;
  last_active_at: string;
  connection_count: number;
  api_tools_count: number;
  owner: WorkspaceOwner;
  members: WorkspaceMember[];
  member_count: number;
  metrics: WorkspaceMetrics;
}

interface AdminStats {
  total_users: number;
  active_users: number;
  pending_users: number;
  suspended_users: number;
  total_questions_today: number;
  total_tokens_today: number;
  total_cost_today: number;
  total_cost_month: number;
  recent_signups: User[];
}

interface UsageEntry {
  user_name: string;
  user_email: string;
  questions: number;
  // Backend UsageRecord fields (see backend/app/schemas/persistence.py).
  // Older rows written before cache tracking was added won't have the
  // cache_* fields; treat them as 0.
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  cache_read_tokens?: number;
  cache_creation_tokens?: number;
  cost_usd: number;
  model_name?: string;
  timestamp: string;
}

function useAdminApi() {
  const token = useAuthStore((s) => s.token);
  const headers = useCallback((): Record<string, string> => {
    const h: Record<string, string> = { 'Content-Type': 'application/json' };
    // Use zustand token first, fall back to localStorage (handles hydration delay)
    let t = token;
    if (!t) {
      try {
        const stored = localStorage.getItem('datalens-auth');
        if (stored) t = JSON.parse(stored)?.state?.token || null;
      } catch { /* ignore */ }
    }
    if (t) h['Authorization'] = `Bearer ${t}`;
    return h;
  }, [token]);
  return { headers };
}

/* ─── Small reusable components ─── */

function StatCard({ icon, label, value, color }: {
  icon: React.ReactNode; label: string; value: string | number; color: string;
}) {
  return (
    <div className="adm-stat-card">
      <div className="adm-stat-icon" style={{ background: color + '18', color }}>{icon}</div>
      <div>
        <div className="adm-stat-value">{value}</div>
        <div className="adm-stat-label">{label}</div>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  return <span className={`adm-badge adm-badge--${status}`}>{status}</span>;
}

function RoleBadge({ role }: { role: string }) {
  const colors: Record<string, { bg: string; fg: string }> = {
    admin: { bg: '#fef2f2', fg: '#dc2626' },
    manager: { bg: '#eef2ff', fg: '#4f46e5' },
    user: { bg: '#f3f4f6', fg: '#6b7280' },
  };
  const c = colors[role] || colors.user;
  return (
    <span style={{
      display: 'inline-block', padding: '2px 10px', borderRadius: 20,
      fontSize: 11, fontWeight: 600, textTransform: 'capitalize',
      background: c.bg, color: c.fg,
    }}>
      {role}
    </span>
  );
}

function Avatar({ name, url, size = 32 }: { name: string; url?: string | null; size?: number }) {
  if (url) return <img src={url} alt="" style={{ width: size, height: size, borderRadius: '50%', objectFit: 'cover', flexShrink: 0 }} />;
  return (
    <div style={{
      width: size, height: size, borderRadius: '50%', flexShrink: 0,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'linear-gradient(135deg, #6366f1, #4f46e5)', color: '#fff',
      fontSize: size * 0.38, fontWeight: 700,
    }}>
      {name?.charAt(0)?.toUpperCase() || '?'}
    </div>
  );
}

/* ─── Limits Modal ─── */
function LimitsModal({ user, onClose, onSave }: {
  user: User; onClose: () => void; onSave: (limits: Record<string, unknown>) => void;
}) {
  const [maxQ, setMaxQ] = useState(String(user.max_questions_per_day));
  const [maxT, setMaxT] = useState(String(user.max_tokens_per_day));
  const [maxC, setMaxC] = useState(String(user.max_cost_usd_per_month));
  const [expiry, setExpiry] = useState(user.expiry_date || '');
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    await onSave({
      max_questions_per_day: parseInt(maxQ) || 0,
      max_tokens_per_day: parseInt(maxT) || 0,
      max_cost_usd_per_month: parseFloat(maxC) || 0,
      expiry_date: expiry || null,
    });
    setSaving(false);
    onClose();
  };

  return (
    <div className="adm-modal-overlay" onClick={onClose}>
      <div className="adm-modal" onClick={(e) => e.stopPropagation()}>
        <h3 className="adm-modal-title">Set Limits for {user.name}</h3>
        <div className="adm-modal-form">
          <label className="adm-modal-label">Max Questions/Day<input type="number" className="adm-modal-input" value={maxQ} onChange={(e) => setMaxQ(e.target.value)} /></label>
          <label className="adm-modal-label">Max Tokens/Day<input type="number" className="adm-modal-input" value={maxT} onChange={(e) => setMaxT(e.target.value)} /></label>
          <label className="adm-modal-label">Max Cost USD/Month<input type="number" step="0.01" className="adm-modal-input" value={maxC} onChange={(e) => setMaxC(e.target.value)} /></label>
          <label className="adm-modal-label">Expiry Date<input type="date" className="adm-modal-input" value={expiry} onChange={(e) => setExpiry(e.target.value)} /></label>
        </div>
        <div className="adm-modal-actions">
          <button className="adm-btn adm-btn--secondary" onClick={onClose}>Cancel</button>
          <button className="adm-btn adm-btn--primary" onClick={handleSave} disabled={saving}>
            {saving ? <Loader2 size={14} className="ts-spinner" /> : null} Save Limits
          </button>
        </div>
      </div>
    </div>
  );
}

/* ================================================================
   SECTION: Dashboard
   ================================================================ */
function DashboardSection({ stats, workspaces, loading, onOpenWorkspace }: {
  stats: AdminStats | null; workspaces: AdminWorkspace[]; loading: boolean;
  onOpenWorkspace: (id: string) => void;
}) {
  if (loading) return <div className="adm-loading"><Loader2 size={24} className="ts-spinner" /> Loading...</div>;

  return (
    <>
      <div className="adm-stats-grid">
        <StatCard icon={<Users size={20} />} label="Total Users" value={stats?.total_users ?? 0} color="#6366f1" />
        <StatCard icon={<Check size={20} />} label="Active" value={stats?.active_users ?? 0} color="#059669" />
        <StatCard icon={<Clock size={20} />} label="Pending" value={stats?.pending_users ?? 0} color="#d97706" />
        <StatCard icon={<X size={20} />} label="Suspended" value={stats?.suspended_users ?? 0} color="#dc2626" />
      </div>

      <div className="adm-stats-grid">
        <StatCard icon={<BarChart3 size={20} />} label="Workspaces" value={workspaces.length} color="#6366f1" />
        <StatCard icon={<MessageSquare size={20} />} label="Today's Questions" value={stats?.total_questions_today ?? 0} color="#818cf8" />
        <StatCard icon={<DollarSign size={20} />} label="Today Cost" value={`$${(stats?.total_cost_today ?? 0).toFixed(2)}`} color="#f97316" />
        <StatCard icon={<DollarSign size={20} />} label="Month Cost" value={`$${(stats?.total_cost_month ?? 0).toFixed(2)}`} color="#dc2626" />
      </div>

      {/* Top workspaces summary table */}
      <h3 className="adm-section-title">Top Workspaces</h3>
      <div className="adm-table-wrapper">
        <table className="adm-table">
          <thead>
            <tr><th>Workspace</th><th>Manager</th><th>Members</th><th>Connections</th><th>Queries</th><th>Cost</th></tr>
          </thead>
          <tbody>
            {[...workspaces].sort((a, b) => b.metrics.total_queries - a.metrics.total_queries).slice(0, 10).map((ws) => (
              <tr key={ws.id} style={{ cursor: 'pointer' }} onClick={() => onOpenWorkspace(ws.id)}>
                <td>
                  <div className="adm-user-cell">
                    <div className="adm-ws-card-icon" style={{ width: 32, height: 32, borderRadius: 8, fontSize: 12 }}><BarChart3 size={14} /></div>
                    <div>
                      <div className="adm-user-name">{ws.name}</div>
                      <div className="adm-user-email">{ws.description || '--'}</div>
                    </div>
                  </div>
                </td>
                <td>
                  <div className="adm-user-cell">
                    <Avatar name={ws.owner.name} url={ws.owner.avatar_url} size={24} />
                    <span style={{ fontSize: 13 }}>{ws.owner.name}</span>
                  </div>
                </td>
                <td>{ws.member_count}</td>
                <td>{ws.connection_count}</td>
                <td>{ws.metrics.total_queries.toLocaleString()}</td>
                <td>${ws.metrics.total_cost.toFixed(2)}</td>
              </tr>
            ))}
            {workspaces.length === 0 && <tr><td colSpan={6} className="adm-empty">No workspaces yet</td></tr>}
          </tbody>
        </table>
      </div>

      {/* Recent signups */}
      {stats?.recent_signups && stats.recent_signups.length > 0 && (
        <>
          <h3 className="adm-section-title" style={{ marginTop: 32 }}>Recent Signups</h3>
          <div className="adm-recent-list">
            {stats.recent_signups.slice(0, 5).map((u) => (
              <div key={u.id} className="adm-recent-item">
                <Avatar name={u.name} url={u.avatar_url} size={32} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="adm-recent-name">{u.name}</div>
                  <div className="adm-recent-email">{u.email}</div>
                </div>
                <RoleBadge role={u.role} />
                <StatusBadge status={u.status} />
              </div>
            ))}
          </div>
        </>
      )}
    </>
  );
}

/* ================================================================
   SECTION: Workspaces (full management)
   ================================================================ */
function WorkspacesSection({ workspaces, loading, onOpenWorkspace, onDeleteWorkspace, headers, onRefresh }: {
  workspaces: AdminWorkspace[]; loading: boolean;
  onOpenWorkspace: (id: string) => void;
  onDeleteWorkspace: (id: string, name: string) => void;
  headers: Record<string, string>;
  onRefresh: () => void;
}) {
  const navigate = useNavigate();
  const wsStore = useWorkspaceStore();
  const [search, setSearch] = useState('');
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [newEmail, setNewEmail] = useState('');
  const [addingMember, setAddingMember] = useState<string | null>(null);
  const [removingMember, setRemovingMember] = useState<string | null>(null);
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [bulkText, setBulkText] = useState('');
  const [showBulk, setShowBulk] = useState<string | null>(null);
  const [bulkAdding, setBulkAdding] = useState(false);
  const [apiToolsWsId, setApiToolsWsId] = useState<string | null>(null);

  const addMembersBulk = async (wsId: string) => {
    const emails = bulkText
      .split(/[\n,;]+/)
      .map((e) => e.trim().toLowerCase())
      .filter((e) => e && e.includes('@'));
    if (emails.length === 0) return;
    setBulkAdding(true);
    let added = 0;
    for (const email of emails) {
      try {
        const res = await fetch(`${API_BASE}/api/workspaces/${wsId}/members`, {
          method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' },
          body: JSON.stringify({ email }),
        });
        if (res.ok) added++;
      } catch { /* skip */ }
    }
    setBulkAdding(false);
    setBulkText('');
    setShowBulk(null);
    onRefresh();
  };

  const addMember = async (wsId: string) => {
    if (!newEmail.trim()) return;
    setAddingMember(wsId);
    try {
      const res = await fetch(`${API_BASE}/api/workspaces/${wsId}/members`, {
        method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: newEmail.trim() }),
      });
      if (!res.ok) { const e = await res.json().catch(() => ({})); alert(e.detail || 'Failed to add member'); return; }
      setNewEmail('');
      onRefresh();
    } catch { alert('Network error'); }
    finally { setAddingMember(null); }
  };

  const removeMember = async (wsId: string, email: string) => {
    if (!confirm(`Remove ${email} from this workspace?`)) return;
    setRemovingMember(email);
    try {
      await fetch(`${API_BASE}/api/workspaces/${wsId}/members/${encodeURIComponent(email)}`, {
        method: 'DELETE', headers,
      });
      onRefresh();
    } catch { alert('Network error'); }
    finally { setRemovingMember(null); }
  };

  const handleCreate = async (data: CreateWorkspaceResult): Promise<string> => {
    // Build connection_ids from the wizard result
    const connectionIds: string[] = [];
    if (data.connection?.id) connectionIds.push(data.connection.id);

    // Create workspace on backend (sets owner_id from JWT)
    const doc = await createWorkspaceOnBackend({
      name: data.name,
      description: data.description || '',
      icon: data.icon || 'bar-chart-3',
      connection_ids: connectionIds,
    });
    const backendId = doc.id as string;

    // Also create in local store for navigation
    const ws = wsStore.createWorkspace({
      name: data.name,
      description: data.description,
      icon: data.icon,
      backendId,
    } as Parameters<typeof wsStore.createWorkspace>[0]);
    wsStore.setActiveWorkspace(ws.id);

    if (data.connection) {
      const { id, config, selectedTables, schema } = data.connection;
      const connInfo: ConnectionInfo = {
        id,
        name: config.name,
        connectorType: config.connectorType,
        host: 'host' in config ? config.host : ('endpoint' in config ? config.endpoint : 'local'),
        database: 'database' in config ? config.database : config.name,
        status: 'connected',
        selectedTableNames: selectedTables,
        schema,
      };
      wsStore.addConnectionToWorkspace(ws.id, connInfo);

      // Trigger profiling on the backend workspace
      if (backendId && id) {
        try {
          await fetch(`${API_BASE}/api/workspaces/${backendId}/profile/generate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...headers },
            body: JSON.stringify({
              connection_id: id,
              selected_tables: selectedTables || [],
            }),
          });
        } catch { /* profiling is non-blocking */ }
      }
    }
    onRefresh();
    return ws.id;
  };

  const handleNavigateToWorkspace = (workspaceId: string) => {
    setShowCreateDialog(false);
    navigate(`/workspace/${workspaceId}`);
  };

  if (loading) return <div className="adm-loading"><Loader2 size={24} className="ts-spinner" /> Loading workspaces...</div>;

  const filtered = workspaces.filter((ws) =>
    !search ||
    ws.name.toLowerCase().includes(search.toLowerCase()) ||
    ws.owner.name.toLowerCase().includes(search.toLowerCase()) ||
    ws.owner.email.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <>
      <div className="adm-ws-toolbar">
        <div className="adm-ws-search-bar">
          <Search size={14} />
          <input type="text" placeholder="Search workspaces, managers..." value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 13, color: '#9ca3af' }}>{filtered.length} workspace{filtered.length !== 1 ? 's' : ''}</span>
          <button className="adm-btn adm-btn--primary" style={{ fontSize: 13, padding: '7px 16px' }} onClick={() => setShowCreateDialog(true)}>
            <Plus size={14} /> New Workspace
          </button>
        </div>
      </div>

      <CreateWorkspaceDialog
        isOpen={showCreateDialog}
        onClose={() => setShowCreateDialog(false)}
        onCreate={handleCreate}
        onNavigate={handleNavigateToWorkspace}
      />

      {filtered.length === 0 ? (
        <div className="adm-empty" style={{ padding: 60 }}>No workspaces found</div>
      ) : (
        <div className="adm-ws-list">
          {filtered.map((ws) => {
            const isOpen = expandedId === ws.id;
            return (
              <div key={ws.id} className={`adm-ws-card ${isOpen ? 'adm-ws-card--open' : ''}`}>
                <div className="adm-ws-card-header" onClick={() => setExpandedId(isOpen ? null : ws.id)}>
                  <div className="adm-ws-card-icon"><BarChart3 size={16} /></div>
                  <div className="adm-ws-card-info">
                    <h3 className="adm-ws-card-name">{ws.name}</h3>
                    <p className="adm-ws-card-desc">{ws.description || 'No description'}</p>
                  </div>
                  <div className="adm-ws-card-stats">
                    <span className="adm-ws-mini-stat"><Users size={13} /> {ws.member_count}</span>
                    <span className="adm-ws-mini-stat"><Database size={13} /> {ws.connection_count}</span>
                    <span className="adm-ws-mini-stat"><MessageSquare size={13} /> {ws.metrics.total_queries}</span>
                    <span className="adm-ws-mini-stat"><DollarSign size={13} /> ${ws.metrics.total_cost.toFixed(2)}</span>
                  </div>
                  <ChevronRight size={16} style={{ color: '#9ca3af', transform: isOpen ? 'rotate(90deg)' : 'none', transition: 'transform 0.2s' }} />
                </div>

                {isOpen && (
                  <div className="adm-ws-card-body">
                    <div className="adm-ws-metrics">
                      <div className="adm-ws-metric"><span className="adm-ws-metric-val">{ws.metrics.total_queries}</span><span className="adm-ws-metric-lbl">Queries</span></div>
                      <div className="adm-ws-metric"><span className="adm-ws-metric-val">{ws.metrics.total_tokens.toLocaleString()}</span><span className="adm-ws-metric-lbl">Tokens</span></div>
                      <div className="adm-ws-metric"><span className="adm-ws-metric-val">${ws.metrics.total_cost.toFixed(2)}</span><span className="adm-ws-metric-lbl">Cost</span></div>
                      <div className="adm-ws-metric"><span className="adm-ws-metric-val">{ws.connection_count}</span><span className="adm-ws-metric-lbl">Connections</span></div>
                      <div className="adm-ws-metric"><span className="adm-ws-metric-val">{ws.api_tools_count}</span><span className="adm-ws-metric-lbl">API Tools</span></div>
                    </div>

                    {/* Manager */}
                    <div className="adm-ws-section">
                      <h4 className="adm-ws-section-title"><Shield size={13} /> Manager / Owner</h4>
                      <div className="adm-ws-person">
                        <Avatar name={ws.owner.name} url={ws.owner.avatar_url} size={28} />
                        <div className="adm-ws-person-info">
                          <span className="adm-ws-person-name">{ws.owner.name || 'Unknown'}</span>
                          <span className="adm-ws-person-email">{ws.owner.email}</span>
                        </div>
                        <RoleBadge role={ws.owner.role} />
                      </div>
                    </div>

                    {/* Members with add/remove */}
                    <div className="adm-ws-section">
                      <h4 className="adm-ws-section-title"><Users size={13} /> Members ({ws.members.length})</h4>

                      {/* Add member form */}
                      <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
                        <input type="email" placeholder="Enter email to add member..." value={expandedId === ws.id ? newEmail : ''} onChange={(e) => setNewEmail(e.target.value)}
                          onKeyDown={(e) => e.key === 'Enter' && addMember(ws.id)}
                          style={{ flex: 1, padding: '6px 12px', borderRadius: 6, border: '1px solid #d1d5db', fontSize: 13 }} />
                        <button className="adm-btn adm-btn--primary" style={{ fontSize: 12, padding: '6px 14px' }}
                          disabled={addingMember === ws.id || !newEmail.trim()} onClick={() => addMember(ws.id)}>
                          {addingMember === ws.id ? <Loader2 size={13} className="ts-spinner" /> : <><UserPlus size={13} /> Add</>}
                        </button>
                        <button className="adm-btn adm-btn--secondary" style={{ fontSize: 12, padding: '6px 12px' }}
                          onClick={() => setShowBulk(showBulk === ws.id ? null : ws.id)}>
                          Bulk Add
                        </button>
                      </div>

                      {/* Bulk add members */}
                      {showBulk === ws.id && (
                        <div style={{ marginBottom: 12, padding: 12, background: '#f9fafb', borderRadius: 8, border: '1px solid #e5e7eb' }}>
                          <p style={{ fontSize: 12, color: '#6b7280', margin: '0 0 8px' }}>
                            Paste emails separated by commas, semicolons, or new lines:
                          </p>
                          <textarea
                            value={bulkText} onChange={(e) => setBulkText(e.target.value)}
                            placeholder={"user1@example.com\nuser2@example.com\nuser3@example.com"}
                            rows={4}
                            style={{ width: '100%', padding: '8px 12px', borderRadius: 6, border: '1px solid #d1d5db', fontSize: 13, fontFamily: 'inherit', resize: 'vertical' }}
                          />
                          <div style={{ display: 'flex', gap: 8, marginTop: 8, justifyContent: 'flex-end' }}>
                            <button className="adm-btn adm-btn--secondary" style={{ fontSize: 12, padding: '5px 12px' }}
                              onClick={() => { setShowBulk(null); setBulkText(''); }}>Cancel</button>
                            <button className="adm-btn adm-btn--primary" style={{ fontSize: 12, padding: '5px 14px' }}
                              disabled={bulkAdding || !bulkText.trim()} onClick={() => addMembersBulk(ws.id)}>
                              {bulkAdding ? <><Loader2 size={13} className="ts-spinner" /> Adding...</> : `Add ${bulkText.split(/[\n,;]+/).filter(e => e.trim().includes('@')).length} Members`}
                            </button>
                          </div>
                        </div>
                      )}

                      {ws.members.length === 0 ? (
                        <p className="adm-ws-empty-text">No members added yet</p>
                      ) : (
                        <div className="adm-ws-members-list">
                          {ws.members.map((m) => (
                            <div key={m.email} className="adm-ws-person">
                              <Avatar name={m.name} url={m.avatar_url} size={28} />
                              <div className="adm-ws-person-info">
                                <span className="adm-ws-person-name">{m.name}</span>
                                <span className="adm-ws-person-email">{m.email}</span>
                              </div>
                              <StatusBadge status={m.status} />
                              <button className="adm-btn" style={{ padding: '4px 8px', color: '#dc2626', border: 'none', background: 'none', cursor: 'pointer' }}
                                title="Remove member" disabled={removingMember === m.email}
                                onClick={() => removeMember(ws.id, m.email)}>
                                {removingMember === m.email ? <Loader2 size={14} className="ts-spinner" /> : <X size={14} />}
                              </button>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    <div className="adm-ws-card-footer">
                      <div className="adm-ws-timestamps">
                        <span><Clock size={12} /> Created: {ws.created_at ? new Date(ws.created_at).toLocaleDateString() : '--'}</span>
                        <span><Activity size={12} /> Last Active: {ws.last_active_at ? new Date(ws.last_active_at).toLocaleDateString() : '--'}</span>
                      </div>
                      <div style={{ display: 'flex', gap: 8 }}>
                        <button
                          className="adm-btn"
                          style={{ fontSize: 12, padding: '6px 14px', color: '#6366f1', borderColor: '#e0e7ff' }}
                          onClick={(e) => { e.stopPropagation(); setApiToolsWsId(ws.id); }}
                        >
                          <Plug size={13} /> API Tools
                        </button>
                        <button
                          className="adm-btn adm-btn--danger"
                          style={{ fontSize: 12, padding: '6px 14px' }}
                          onClick={(e) => { e.stopPropagation(); onDeleteWorkspace(ws.id, ws.name); }}
                        >
                          <Trash2 size={13} /> Delete
                        </button>
                        <button className="adm-btn adm-btn--primary" style={{ fontSize: 12, padding: '6px 16px' }} onClick={(e) => { e.stopPropagation(); onOpenWorkspace(ws.id); }}>
                          Open Workspace <ChevronRight size={14} />
                        </button>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {apiToolsWsId && (
        <ApiToolManager
          workspaceId={apiToolsWsId}
          onClose={() => { setApiToolsWsId(null); onRefresh(); }}
        />
      )}
    </>
  );
}

/* ================================================================
   SECTION: Managers
   ================================================================ */
function ManagersSection({ workspaces, users, loading }: {
  workspaces: AdminWorkspace[]; users: User[]; loading: boolean;
}) {
  if (loading) return <div className="adm-loading"><Loader2 size={24} className="ts-spinner" /> Loading...</div>;

  // Group workspaces by owner
  const managers = users.filter((u) => u.role === 'manager' || u.role === 'admin');
  const wsByOwner: Record<string, AdminWorkspace[]> = {};
  for (const ws of workspaces) {
    const oid = ws.owner.id;
    if (!wsByOwner[oid]) wsByOwner[oid] = [];
    wsByOwner[oid].push(ws);
  }

  return (
    <>
      {managers.length === 0 ? (
        <div className="adm-empty" style={{ padding: 60 }}>No managers found</div>
      ) : (
        <div className="adm-mgr-list">
          {managers.map((mgr) => {
            const owned = wsByOwner[mgr.id] || [];
            const totalQueries = owned.reduce((s, w) => s + w.metrics.total_queries, 0);
            const totalCost = owned.reduce((s, w) => s + w.metrics.total_cost, 0);
            const totalMembers = owned.reduce((s, w) => s + w.member_count, 0);
            return (
              <div key={mgr.id} className="adm-mgr-card">
                <div className="adm-mgr-header">
                  <Avatar name={mgr.name} url={mgr.avatar_url} size={40} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="adm-mgr-name">{mgr.name}</div>
                    <div className="adm-mgr-email">{mgr.email}</div>
                  </div>
                  <RoleBadge role={mgr.role} />
                  <StatusBadge status={mgr.status} />
                </div>
                <div className="adm-mgr-stats">
                  <div className="adm-mgr-stat"><span className="adm-mgr-stat-val">{owned.length}</span><span className="adm-mgr-stat-lbl">Workspaces</span></div>
                  <div className="adm-mgr-stat"><span className="adm-mgr-stat-val">{totalMembers}</span><span className="adm-mgr-stat-lbl">Members</span></div>
                  <div className="adm-mgr-stat"><span className="adm-mgr-stat-val">{totalQueries}</span><span className="adm-mgr-stat-lbl">Queries</span></div>
                  <div className="adm-mgr-stat"><span className="adm-mgr-stat-val">${totalCost.toFixed(2)}</span><span className="adm-mgr-stat-lbl">Cost</span></div>
                </div>
                {owned.length > 0 && (
                  <div className="adm-mgr-workspaces">
                    <h5 className="adm-ws-section-title" style={{ marginTop: 0 }}><BarChart3 size={12} /> Workspaces</h5>
                    {owned.map((ws) => (
                      <div key={ws.id} className="adm-mgr-ws-row">
                        <span className="adm-mgr-ws-name">{ws.name}</span>
                        <span className="adm-ws-mini-stat"><Users size={11} /> {ws.member_count}</span>
                        <span className="adm-ws-mini-stat"><Database size={11} /> {ws.connection_count}</span>
                        <span className="adm-ws-mini-stat"><MessageSquare size={11} /> {ws.metrics.total_queries}</span>
                        <span className="adm-ws-mini-stat"><DollarSign size={11} /> ${ws.metrics.total_cost.toFixed(2)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}

/* ================================================================
   SECTION: Users
   ================================================================ */
function UsersSection({ users, loading, onAction, headers }: {
  users: User[]; loading: boolean;
  onAction: (action: string, userId: string, payload?: Record<string, unknown>) => Promise<void>;
  headers: () => Record<string, string>;
}) {
  const [filter, setFilter] = useState<UserFilter>('all');
  const [limitsUser, setLimitsUser] = useState<User | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const filtered = filter === 'all' ? users : users.filter((u) => u.status === filter);
  const counts = {
    all: users.length,
    pending: users.filter((u) => u.status === 'pending').length,
    active: users.filter((u) => u.status === 'active').length,
    suspended: users.filter((u) => u.status === 'suspended').length,
  };

  const handleAction = async (action: string, userId: string, payload?: Record<string, unknown>) => {
    setActionLoading(userId);
    await onAction(action, userId, payload);
    setActionLoading(null);
    setDeleteConfirm(null);
  };

  const handleRoleChange = async (userId: string, newRole: string) => {
    try {
      await fetch(`${API_BASE}/api/admin/users/${userId}`, {
        method: 'PUT', headers: headers(), body: JSON.stringify({ role: newRole }),
      });
      await onAction('refresh', '');
    } catch { /* ignore */ }
  };

  if (loading) return <div className="adm-loading"><Loader2 size={24} className="ts-spinner" /> Loading users...</div>;

  return (
    <div className="adm-users">
      <div className="adm-tabs">
        {(['all', 'pending', 'active', 'suspended'] as UserFilter[]).map((f) => (
          <button key={f} className={`adm-tab ${filter === f ? 'adm-tab--active' : ''}`} onClick={() => setFilter(f)}>
            {f.charAt(0).toUpperCase() + f.slice(1)}
            <span className="adm-tab-count">{counts[f]}</span>
          </button>
        ))}
      </div>

      <div className="adm-table-wrapper">
        <table className="adm-table">
          <thead>
            <tr>
              <th>User</th>
              <th>Role</th>
              <th>Status</th>
              <th>Questions Today</th>
              <th>Tokens Today</th>
              <th>Cost (Month)</th>
              <th>Expiry</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((u) => (
              <tr key={u.id}>
                <td>
                  <div className="adm-user-cell">
                    <Avatar name={u.name} url={u.avatar_url} size={28} />
                    <div>
                      <div className="adm-user-name">{u.name}</div>
                      <div className="adm-user-email">{u.email}</div>
                    </div>
                  </div>
                </td>
                <td>
                  <select className="adm-role-select" value={u.role} onChange={(e) => handleRoleChange(u.id, e.target.value)}>
                    <option value="user">User</option>
                    <option value="manager">Manager</option>
                    <option value="admin">Admin</option>
                  </select>
                </td>
                <td><StatusBadge status={u.status} /></td>
                <td>{u.today_questions}</td>
                <td>{u.today_tokens?.toLocaleString()}</td>
                <td>${u.month_cost_usd?.toFixed(2)}</td>
                <td>{u.expiry_date || '--'}</td>
                <td>
                  <div className="adm-actions">
                    {actionLoading === u.id ? (
                      <Loader2 size={14} className="ts-spinner" />
                    ) : deleteConfirm === u.id ? (
                      <div className="adm-confirm">
                        <span style={{ fontSize: 12, color: '#dc2626' }}>Delete?</span>
                        <button className="adm-action-btn adm-action-btn--danger" onClick={() => handleAction('delete', u.id)}>Yes</button>
                        <button className="adm-action-btn" onClick={() => setDeleteConfirm(null)}>No</button>
                      </div>
                    ) : (
                      <>
                        {u.status === 'pending' && <button className="adm-action-btn adm-action-btn--success" title="Approve" onClick={() => handleAction('approve', u.id)}><Check size={14} /></button>}
                        {u.status !== 'suspended' && <button className="adm-action-btn adm-action-btn--warning" title="Suspend" onClick={() => handleAction('suspend', u.id)}><AlertTriangle size={14} /></button>}
                        {u.status === 'suspended' && <button className="adm-action-btn adm-action-btn--success" title="Reactivate" onClick={() => handleAction('approve', u.id)}><Check size={14} /></button>}
                        <button className="adm-action-btn" title="Set Limits" onClick={() => setLimitsUser(u)}><Settings size={14} /></button>
                        <button className="adm-action-btn adm-action-btn--danger" title="Delete" onClick={() => setDeleteConfirm(u.id)}><Trash2 size={14} /></button>
                      </>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && <tr><td colSpan={8} className="adm-empty">No users found</td></tr>}
          </tbody>
        </table>
      </div>

      {limitsUser && (
        <LimitsModal user={limitsUser} onClose={() => setLimitsUser(null)} onSave={async (limits) => { await onAction('limits', limitsUser.id, limits); }} />
      )}
    </div>
  );
}

/* ================================================================
   SECTION: Usage
   ================================================================ */
function UsageSection({ usage, loading }: { usage: UsageEntry[]; loading: boolean }) {
  if (loading) return <div className="adm-loading"><Loader2 size={24} className="ts-spinner" /> Loading usage...</div>;
  const fmt = (n?: number) => (n ?? 0).toLocaleString();
  return (
    <div className="adm-usage">
      <div className="adm-table-wrapper">
        <table className="adm-table">
          <thead>
            <tr>
              <th>User</th>
              <th>Questions</th>
              <th title="Fresh input tokens (non-cached)">Input</th>
              <th title="Output tokens (assistant response)">Output</th>
              <th title="Prompt cache: read + write tokens (Anthropic only)">Cache</th>
              <th>Cost</th>
              <th>Model</th>
              <th>Time</th>
            </tr>
          </thead>
          <tbody>
            {usage.map((entry, i) => {
              const cacheRead = entry.cache_read_tokens ?? 0;
              const cacheWrite = entry.cache_creation_tokens ?? 0;
              const cacheTotal = cacheRead + cacheWrite;
              const cacheTitle =
                cacheTotal > 0
                  ? `Read ${cacheRead.toLocaleString()} • Written ${cacheWrite.toLocaleString()}`
                  : 'No prompt cache usage';
              return (
                <tr key={i}>
                  <td><div><div className="adm-user-name">{entry.user_name}</div><div className="adm-user-email">{entry.user_email}</div></div></td>
                  <td>{entry.questions}</td>
                  <td>{fmt(entry.input_tokens)}</td>
                  <td>{fmt(entry.output_tokens)}</td>
                  <td title={cacheTitle}>{fmt(cacheTotal)}</td>
                  <td>${entry.cost_usd?.toFixed(4)}</td>
                  <td><span className="adm-model-badge">{entry.model_name || '—'}</span></td>
                  <td className="adm-time">{new Date(entry.timestamp).toLocaleString()}</td>
                </tr>
              );
            })}
            {usage.length === 0 && <tr><td colSpan={8} className="adm-empty">No usage data</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ================================================================
   MAIN: Admin Dashboard
   ================================================================ */
export default function AdminDashboard() {
  const navigate = useNavigate();
  const { headers } = useAdminApi();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const setActiveWorkspace = useWorkspaceStore((s) => s.setActiveWorkspace);

  const openWorkspace = (id: string) => {
    setActiveWorkspace(id);
    navigate(`/workspace/${id}`);
  };

  const role = user?.role || 'user';
  const isAdmin = role === 'admin';
  const isPrivileged = role === 'admin' || role === 'manager';

  // Non-admins default to workspaces view
  const [section, setSection] = useState<Section>(isAdmin ? 'dashboard' : 'workspaces');
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [workspaces, setWorkspaces] = useState<AdminWorkspace[]>([]);
  const [usage, setUsage] = useState<UsageEntry[]>([]);
  const [statsLoading, setStatsLoading] = useState(true);
  const [usersLoading, setUsersLoading] = useState(true);
  const [wsLoading, setWsLoading] = useState(true);
  const [usageLoading, setUsageLoading] = useState(true);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' } | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState<{ id: string; name: string } | null>(null);
  const [deleting, setDeleting] = useState(false);

  const fetchStats = useCallback(async () => {
    if (!isAdmin) { setStatsLoading(false); return; }
    setStatsLoading(true);
    try { const r = await fetch(`${API_BASE}/api/admin/stats`, { headers: headers() }); if (r.ok) setStats(await r.json()); } catch {}
    setStatsLoading(false);
  }, [headers, isAdmin]);

  const fetchUsers = useCallback(async () => {
    if (!isAdmin) { setUsersLoading(false); return; }
    setUsersLoading(true);
    try { const r = await fetch(`${API_BASE}/api/admin/users`, { headers: headers() }); if (r.ok) setUsers(await r.json()); } catch {}
    setUsersLoading(false);
  }, [headers, isAdmin]);

  const fetchWorkspaces = useCallback(async () => {
    // Skip if no auth token available yet (zustand hydration pending)
    const h = headers();
    if (!h['Authorization']) { return; }
    setWsLoading(true);
    try {
      // Admins get enriched workspace data, others get regular workspace list
      const url = isAdmin ? `${API_BASE}/api/admin/workspaces` : `${API_BASE}/api/workspaces`;
      const r = await fetch(url, { headers: h });
      if (r.ok) {
        const data = await r.json();
        if (isAdmin) {
          setWorkspaces(data);
        } else {
          // Map regular workspace format to AdminWorkspace shape
          setWorkspaces((data.workspaces || data).map((ws: Record<string, unknown>) => ({
            id: ws.id, name: ws.name, description: ws.description || '',
            owner: { id: ws.owner_id || '', name: '', email: '', role: 'manager', avatar_url: '' },
            members: (ws.members as Array<Record<string, string>>) || [],
            member_count: ((ws.members as unknown[]) || []).length,
            connection_count: 0, api_tools_count: 0,
            created_at: ws.created_at || '', last_active_at: '',
            metrics: { total_queries: 0, total_tokens: 0, total_cost: 0 },
          })));
        }
      }
    } catch {}
    setWsLoading(false);
  }, [headers, isAdmin]);

  const fetchUsage = useCallback(async () => {
    if (!isAdmin) { setUsageLoading(false); return; }
    setUsageLoading(true);
    try { const r = await fetch(`${API_BASE}/api/admin/usage`, { headers: headers() }); if (r.ok) setUsage(await r.json()); } catch {}
    setUsageLoading(false);
  }, [headers, isAdmin]);

  useEffect(() => { fetchWorkspaces(); if (isAdmin) { fetchStats(); fetchUsers(); } }, [fetchStats, fetchWorkspaces, fetchUsers, isAdmin]);
  useEffect(() => { if (section === 'usage') fetchUsage(); }, [section, fetchUsage]);

  const refreshAll = () => { fetchStats(); fetchWorkspaces(); fetchUsers(); if (section === 'usage') fetchUsage(); };

  const showToast = (message: string, type: 'success' | 'error' = 'success') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 4000);
  };

  const deleteWorkspace = (id: string, name: string) => {
    setDeleteConfirm({ id, name });
  };

  const confirmDelete = async () => {
    if (!deleteConfirm) return;
    setDeleting(true);
    try {
      const res = await fetch(`${API_BASE}/api/admin/workspaces/${deleteConfirm.id}`, { method: 'DELETE', headers: headers() });
      if (res.ok) {
        showToast(`Workspace "${deleteConfirm.name}" deleted successfully`, 'success');
        fetchWorkspaces();
        fetchStats();
      } else {
        const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
        showToast(err.detail || 'Failed to delete workspace', 'error');
      }
    } catch (e) {
      showToast(`Network error: ${e}`, 'error');
    }
    setDeleting(false);
    setDeleteConfirm(null);
  };

  const handleUserAction = async (action: string, userId: string, payload?: Record<string, unknown>) => {
    try {
      if (action === 'refresh') { await Promise.all([fetchStats(), fetchUsers(), fetchWorkspaces()]); return; }
      if (action === 'approve') await fetch(`${API_BASE}/api/admin/users/${userId}`, { method: 'PUT', headers: headers(), body: JSON.stringify({ status: 'active' }) });
      else if (action === 'suspend') await fetch(`${API_BASE}/api/admin/users/${userId}`, { method: 'PUT', headers: headers(), body: JSON.stringify({ status: 'suspended' }) });
      else if (action === 'limits') await fetch(`${API_BASE}/api/admin/users/${userId}`, { method: 'PUT', headers: headers(), body: JSON.stringify(payload) });
      else if (action === 'delete') await fetch(`${API_BASE}/api/admin/users/${userId}`, { method: 'DELETE', headers: headers() });
      await Promise.all([fetchStats(), fetchUsers(), fetchWorkspaces()]);
    } catch {}
  };

  const sectionTitles: Record<Section, string> = {
    dashboard: 'Dashboard',
    workspaces: 'Workspaces',
    managers: 'Managers',
    users: 'User Management',
    usage: 'Usage Logs',
  };

  return (
    <div className="adm-layout">
      {/* ── Sidebar ── */}
      <aside className="adm-sidebar">
        <div className="adm-sidebar-header" style={{ cursor: 'pointer' }} onClick={() => navigate('/')}>
          <svg width="28" height="28" viewBox="0 0 40 40" fill="none">
            <rect width="40" height="40" rx="12" fill="url(#adm-logo-grad)" />
            <path d="M12 26 L17 18 L22 22 L28 14" stroke="#fff" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
            <defs><linearGradient id="adm-logo-grad" x1="0" y1="0" x2="40" y2="40"><stop offset="0%" stopColor="#6366f1" /><stop offset="100%" stopColor="#4f46e5" /></linearGradient></defs>
          </svg>
          <span className="adm-sidebar-brand">DataLens</span>
        </div>

        <nav className="adm-nav">
          {isAdmin && (
            <>
              <div className="adm-nav-group-label">Overview</div>
              <button className={`adm-nav-item ${section === 'dashboard' ? 'adm-nav-item--active' : ''}`} onClick={() => { setSection('dashboard'); setMobileMenuOpen(false); }}>
                <LayoutDashboard size={18} /> Dashboard
              </button>
            </>
          )}

          <div className="adm-nav-group-label">Manage</div>
          <button className={`adm-nav-item ${section === 'workspaces' ? 'adm-nav-item--active' : ''}`} onClick={() => { setSection('workspaces'); setMobileMenuOpen(false); }}>
            <Building2 size={18} /> Workspaces
          </button>
          {isAdmin && (
            <>
              <button className={`adm-nav-item ${section === 'managers' ? 'adm-nav-item--active' : ''}`} onClick={() => { setSection('managers'); setMobileMenuOpen(false); }}>
                <UserCog size={18} /> Managers
              </button>
              <button className={`adm-nav-item ${section === 'users' ? 'adm-nav-item--active' : ''}`} onClick={() => { setSection('users'); setMobileMenuOpen(false); }}>
                <Users size={18} /> Users
              </button>
            </>
          )}

          {isPrivileged && (
            <>
              <div className="adm-nav-group-label">Reports</div>
              <button className="adm-nav-item" onClick={() => navigate('/analytics')}>
                <TrendingUp size={18} /> Analytics
              </button>
            </>
          )}
          <button className={`adm-nav-item ${section === 'usage' ? 'adm-nav-item--active' : ''}`} onClick={() => { setSection('usage'); setMobileMenuOpen(false); }}>
            <ScrollText size={18} /> Usage Logs
          </button>
        </nav>

        <div className="adm-sidebar-footer">
          {user && (
            <div className="adm-sidebar-user">
              <Avatar name={user.name} url={user.avatar_url} size={28} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="adm-sidebar-user-name">{user.name}</div>
                <div className="adm-sidebar-user-role">{user.role}</div>
              </div>
            </div>
          )}
          <button
            className="adm-nav-item"
            style={{ color: '#f87171', marginTop: 8 }}
            onClick={() => { logout(); navigate('/login'); }}
          >
            <LogOut size={18} /> Sign Out
          </button>
        </div>
      </aside>

      {/* ── Mobile header ── */}
      <div className="adm-mobile-header">
        <button className="adm-mobile-menu-btn" onClick={() => setMobileMenuOpen(!mobileMenuOpen)}>
          <ChevronDown size={20} style={{ transform: mobileMenuOpen ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }} />
        </button>
        <span className="adm-sidebar-brand">DataLens Admin</span>
        <button className="adm-mobile-refresh" onClick={refreshAll}><RefreshCw size={16} /></button>
      </div>
      {mobileMenuOpen && (
        <div className="adm-mobile-nav">
          {(['dashboard', 'workspaces', 'managers', 'users', 'usage'] as Section[]).map((key) => (
            <button key={key} className={`adm-nav-item ${section === key ? 'adm-nav-item--active' : ''}`} onClick={() => { setSection(key); setMobileMenuOpen(false); }}>
              {sectionTitles[key]}
            </button>
          ))}
          <button className="adm-nav-item" onClick={() => navigate('/analytics')}>Analytics</button>
        </div>
      )}

      {/* ── Main content ── */}
      <main className="adm-main">
        <div className="adm-topbar">
          <h1 className="adm-page-title">{sectionTitles[section]}</h1>
          <button className="adm-btn adm-btn--secondary" onClick={refreshAll}><RefreshCw size={14} /> Refresh</button>
        </div>

        <div className="adm-content">
          {section === 'dashboard' && <DashboardSection stats={stats} workspaces={workspaces} loading={statsLoading && wsLoading} onOpenWorkspace={openWorkspace} />}
          {section === 'workspaces' && <WorkspacesSection workspaces={workspaces} loading={wsLoading} onOpenWorkspace={openWorkspace} onDeleteWorkspace={deleteWorkspace} headers={headers()} onRefresh={refreshAll} />}
          {section === 'managers' && <ManagersSection workspaces={workspaces} users={users} loading={usersLoading && wsLoading} />}
          {section === 'users' && <UsersSection users={users} loading={usersLoading} onAction={handleUserAction} headers={headers} />}
          {section === 'usage' && <UsageSection usage={usage} loading={usageLoading} />}
        </div>
      </main>

      {/* Toast notification */}
      {toast && (
        <div className={`adm-toast adm-toast--${toast.type}`}>
          {toast.type === 'success' ? <Check size={16} /> : <AlertTriangle size={16} />}
          <span>{toast.message}</span>
          <button onClick={() => setToast(null)} style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', padding: 2 }}><X size={14} /></button>
        </div>
      )}

      {/* Delete confirmation popup */}
      {deleteConfirm && (
        <div className="adm-modal-overlay" onClick={() => !deleting && setDeleteConfirm(null)}>
          <div className="adm-modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 420 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
              <div style={{ width: 40, height: 40, borderRadius: 10, background: '#fef2f2', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#dc2626' }}>
                <Trash2 size={20} />
              </div>
              <div>
                <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>Delete Workspace</h3>
                <p style={{ margin: '4px 0 0', fontSize: 13, color: '#6b7280' }}>This action cannot be undone</p>
              </div>
            </div>
            <p style={{ fontSize: 14, color: '#374151', lineHeight: 1.5, margin: '0 0 20px' }}>
              Are you sure you want to delete <strong>{deleteConfirm.name}</strong>? All sessions, canvas data, and analytics for this workspace will be permanently removed.
            </p>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button className="adm-btn adm-btn--secondary" onClick={() => setDeleteConfirm(null)} disabled={deleting}>
                Cancel
              </button>
              <button className="adm-btn adm-btn--danger" onClick={confirmDelete} disabled={deleting} style={{ fontWeight: 600 }}>
                {deleting ? <Loader2 size={14} className="ts-spinner" /> : <Trash2 size={14} />}
                {deleting ? 'Deleting...' : 'Delete Workspace'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
