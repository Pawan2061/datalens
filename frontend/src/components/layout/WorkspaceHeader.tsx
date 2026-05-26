import { Database, FileText } from 'lucide-react';
import type { Workspace } from '../../types/workspace';
import type { ConnectionInfo } from '../../types/connection';
import ProfileStatus from '../workspace/ProfileStatus';
import { useAuthStore } from '../../store/authStore';

interface WorkspaceHeaderProps {
  workspace: Workspace;
  activeConnection: ConnectionInfo | null;
  onOpenConnectionDialog: () => void;
  customerName?: string;
}

export default function WorkspaceHeader({
  workspace,
  activeConnection,
  onOpenConnectionDialog,
  customerName,
}: WorkspaceHeaderProps) {
  const isPrivileged = useAuthStore((s) => s.isPrivileged);

  return (
    <header className="wv-header">
      <div className="wv-header-left">
        <span className="wv-header-workspace">{workspace.name}</span>
        {customerName && (
          <span style={{
            fontSize: 11,
            fontWeight: 600,
            color: '#6366f1',
            background: 'rgba(99,102,241,0.08)',
            border: '1px solid rgba(99,102,241,0.2)',
            borderRadius: 6,
            padding: '2px 8px',
            letterSpacing: '0.01em',
          }}>
            {customerName}
          </span>
        )}
        {activeConnection && (
          <ProfileStatus
            workspaceId={workspace.id}
            connectionId={activeConnection.id}
            connectionName={activeConnection.name || activeConnection.database}
            readOnly={!isPrivileged}
          />
        )}
      </div>

      <div className="wv-header-right">
        <button
          onClick={onOpenConnectionDialog}
          className={`wv-conn-badge ${activeConnection ? 'wv-conn-badge--active' : ''}`}
        >
          <span className={`wv-conn-dot ${activeConnection ? 'wv-conn-dot--active' : ''}`} />
          {activeConnection?.connectorType === 'file' ? <FileText size={14} /> : <Database size={14} />}
          <span>{activeConnection ? (activeConnection.name || activeConnection.database) : 'Connect'}</span>
        </button>
      </div>
    </header>
  );
}
