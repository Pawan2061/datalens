import { BarChart3, Users, Settings, Wallet, Database, FolderOpen, ArrowUpRight, Clock } from 'lucide-react';
import type { Workspace } from '../../types/workspace';

interface WorkspaceCardProps {
  workspace: Workspace;
  onClick: () => void;
  index?: number;
}

const ICON_MAP: Record<string, typeof BarChart3> = {
  'bar-chart-3': BarChart3,
  users: Users,
  settings: Settings,
  wallet: Wallet,
  database: Database,
  folder: FolderOpen,
};

const THEMES: Record<string, { gradient: string; shadow: string }> = {
  'bar-chart-3': { gradient: 'linear-gradient(135deg, #0066cc, #0052a3)', shadow: 'rgba(0,102,204,0.3)' },
  users: { gradient: 'linear-gradient(135deg, #00b894, #00856d)', shadow: 'rgba(0,184,148,0.3)' },
  settings: { gradient: 'linear-gradient(135deg, #f59e0b, #d97706)', shadow: 'rgba(245,158,11,0.3)' },
  wallet: { gradient: 'linear-gradient(135deg, #8b5cf6, #7c3aed)', shadow: 'rgba(139,92,246,0.3)' },
  database: { gradient: 'linear-gradient(135deg, #06b6d4, #0891b2)', shadow: 'rgba(6,182,212,0.3)' },
  folder: { gradient: 'linear-gradient(135deg, #f43f5e, #e11d48)', shadow: 'rgba(244,63,94,0.3)' },
};

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

export default function WorkspaceCard({ workspace, onClick, index = 0 }: WorkspaceCardProps) {
  const Icon = ICON_MAP[workspace.icon] || FolderOpen;
  const theme = THEMES[workspace.icon] || THEMES['bar-chart-3'];

  return (
    <button
      onClick={onClick}
      className="wsp-card"
      style={{ animationDelay: `${index * 100}ms` }}
    >
      {/* Color accent bar */}
      <div className="wsp-card-accent" style={{ background: theme.gradient }} />

      <div className="wsp-card-body">
        {/* Icon + arrow */}
        <div className="wsp-card-top">
          <div
            className="wsp-card-icon"
            style={{ background: theme.gradient, boxShadow: `0 8px 24px ${theme.shadow}` }}
          >
            <Icon size={22} color="#fff" />
          </div>
          <div className="wsp-card-arrow">
            <ArrowUpRight size={16} />
          </div>
        </div>

        {/* Title + description */}
        <h3 className="wsp-card-title">{workspace.name}</h3>
        <p className="wsp-card-desc">{workspace.description}</p>

        {/* Footer */}
        <div className="wsp-card-footer">
          <span className="wsp-card-meta">
            <Database size={13} />
            {workspace.connectionIds.length} source{workspace.connectionIds.length !== 1 ? 's' : ''}
          </span>
          <span className="wsp-card-meta">
            <Clock size={13} />
            {timeAgo(workspace.lastActiveAt)}
          </span>
        </div>
      </div>
    </button>
  );
}
