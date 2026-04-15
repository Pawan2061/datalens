import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, BarChart3, ArrowRight, Database, Clock, Sparkles, LogOut, Trash2, Search, Shield } from 'lucide-react';
import { useWorkspaceStore } from '../store/workspaceStore';
import { useAuthStore } from '../store/authStore';
import CreateWorkspaceDialog from '../components/workspace/CreateWorkspaceDialog';
import type { CreateWorkspaceResult } from '../components/workspace/CreateWorkspaceDialog';
import type { ConnectionInfo } from '../types/connection';
import { createWorkspaceOnBackend } from '../services/api';

function timeAgo(ts: number): string {
  const diff = Date.now() - ts;
  const minutes = Math.floor(diff / 60000);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return `${Math.floor(days / 7)}w ago`;
}

export default function WorkspaceSelectionPage() {
  const navigate = useNavigate();
  const userName = useAuthStore((s) => s.user?.name || 'User');
  const userEmail = useAuthStore((s) => s.user?.email || '');
  const logout = useAuthStore((s) => s.logout);
  const isAdmin = useAuthStore((s) => s.isAdmin);
  const isPrivileged = useAuthStore((s) => s.isPrivileged);
  const refreshUser = useAuthStore((s) => s.refreshUser);
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const { workspaces, setActiveWorkspace, createWorkspace, deleteWorkspace, addConnectionToWorkspace, loadWorkspacesFromBackend } = useWorkspaceStore();
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [search, setSearch] = useState('');

  useEffect(() => {
    if (isAuthenticated) {
      refreshUser();  // sync role/status/quota from server
      loadWorkspacesFromBackend();
    }
  }, [isAuthenticated, refreshUser, loadWorkspacesFromBackend]);

  const sortedWorkspaces = [...workspaces]
    .sort((a, b) => b.lastActiveAt - a.lastActiveAt)
    .filter((ws) => !search || ws.name.toLowerCase().includes(search.toLowerCase()));
  const totalSources = workspaces.reduce((sum, w) => sum + w.connectionIds.length, 0);

  const handleSelectWorkspace = (id: string) => {
    setActiveWorkspace(id);
    navigate(`/workspace/${id}`);
  };

  const handleDeleteWorkspace = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    deleteWorkspace(id);
  };

  const handleCreate = async (data: CreateWorkspaceResult): Promise<string> => {
    let backendId: string | undefined;
    try {
      const doc = await createWorkspaceOnBackend({
        name: data.name,
        description: data.description || '',
        icon: data.icon || 'bar-chart-3',
      });
      backendId = doc.id as string;
    } catch { /* fallback */ }

    const ws = createWorkspace({
      name: data.name,
      description: data.description,
      icon: data.icon,
      backendId,
    } as Parameters<typeof createWorkspace>[0]);
    setActiveWorkspace(ws.id);

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
      addConnectionToWorkspace(ws.id, connInfo);
    }
    return ws.id;
  };

  const handleNavigateToWorkspace = (workspaceId: string) => {
    setShowCreateDialog(false);
    navigate(`/workspace/${workspaceId}`);
  };

  const initials = userName.split(' ').map((n) => n[0]).join('').slice(0, 2).toUpperCase();

  return (
    <div className="dl-home">
      {/* Top navigation bar */}
      <header className="dl-topnav">
        <div className="dl-topnav-left">
          <svg width="32" height="32" viewBox="0 0 40 40" fill="none">
            <rect width="40" height="40" rx="12" fill="url(#tn-grad)" />
            <path d="M12 26 L17 18 L22 22 L28 14" stroke="#fff" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
            <circle cx="17" cy="18" r="2" fill="#fdba74" />
            <circle cx="28" cy="14" r="2" fill="#fdba74" />
            <defs><linearGradient id="tn-grad" x1="0" y1="0" x2="40" y2="40"><stop offset="0%" stopColor="#6366f1" /><stop offset="100%" stopColor="#4f46e5" /></linearGradient></defs>
          </svg>
          <span className="dl-topnav-brand">DataLens</span>
        </div>
        <div className="dl-topnav-right">
          {isAdmin && (
            <button className="dl-topnav-admin" onClick={() => navigate('/admin')} title="Admin Dashboard">
              <Shield size={16} />
              Admin
            </button>
          )}
          <div className="dl-topnav-avatar" title={userEmail}>
            {initials}
          </div>
          <button className="dl-topnav-logout" onClick={() => { logout(); navigate('/login'); }} title="Sign out">
            <LogOut size={16} />
          </button>
        </div>
      </header>

      {/* Hero section */}
      <div className="dl-hero">
        <div className="dl-hero-inner">
          <h1 className="dl-hero-greeting">Good {new Date().getHours() < 12 ? 'morning' : new Date().getHours() < 18 ? 'afternoon' : 'evening'}, {userName.split(' ')[0]}</h1>
          <p className="dl-hero-sub">What data would you like to explore today?</p>
        </div>

        {/* Stat pills */}
        <div className="dl-stats">
          <div className="dl-stat">
            <BarChart3 size={16} />
            <span className="dl-stat-val">{workspaces.length}</span>
            <span className="dl-stat-label">Workspaces</span>
          </div>
          <div className="dl-stat">
            <Database size={16} />
            <span className="dl-stat-val">{totalSources}</span>
            <span className="dl-stat-label">Sources</span>
          </div>
          <div className="dl-stat">
            <Sparkles size={16} />
            <span className="dl-stat-val">0</span>
            <span className="dl-stat-label">Insights</span>
          </div>
        </div>
      </div>

      {/* Workspaces grid */}
      <div className="dl-ws-area">
        <div className="dl-ws-toolbar">
          <h2 className="dl-ws-title">Your Workspaces</h2>
          <div className="dl-ws-actions">
            <div className="dl-ws-search">
              <Search size={14} />
              <input
                type="text"
                placeholder="Search workspaces..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            {isPrivileged && (
              <button className="dl-ws-create-btn" onClick={() => setShowCreateDialog(true)}>
                <Plus size={16} />
                New Workspace
              </button>
            )}
          </div>
        </div>

        <div className="dl-ws-grid">
          {sortedWorkspaces.map((ws, i) => (
            <div
              key={ws.id}
              className="dl-ws-card"
              onClick={() => handleSelectWorkspace(ws.id)}
              style={{ animationDelay: `${i * 60}ms` }}
              role="button"
              tabIndex={0}
            >
              <div className="dl-ws-card-head">
                <div className="dl-ws-card-icon">
                  <BarChart3 size={18} />
                </div>
                <div className="dl-ws-card-menu">
                  <button className="dl-ws-card-del" onClick={(e) => handleDeleteWorkspace(e, ws.id)} title="Delete">
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>
              <h3 className="dl-ws-card-name">{ws.name}</h3>
              <p className="dl-ws-card-desc">{ws.description || 'No description'}</p>
              <div className="dl-ws-card-foot">
                <span><Database size={12} /> {ws.connectionIds.length} source{ws.connectionIds.length !== 1 ? 's' : ''}</span>
                <span><Clock size={12} /> {timeAgo(ws.lastActiveAt)}</span>
              </div>
              <div className="dl-ws-card-hover-arrow"><ArrowRight size={16} /></div>
            </div>
          ))}

          {/* Create new card — only for managers and admins */}
          {isPrivileged && (
            <button className="dl-ws-card dl-ws-card--new" onClick={() => setShowCreateDialog(true)}>
              <div className="dl-ws-card-plus"><Plus size={28} /></div>
              <h3 className="dl-ws-card-name">New Workspace</h3>
              <p className="dl-ws-card-desc">Start a new data exploration</p>
            </button>
          )}
        </div>
      </div>

      <CreateWorkspaceDialog
        isOpen={showCreateDialog}
        onClose={() => setShowCreateDialog(false)}
        onCreate={handleCreate}
        onNavigate={handleNavigateToWorkspace}
      />
    </div>
  );
}
