import { Database, FileText } from 'lucide-react';
import type { Workspace } from '../../types/workspace';
import type { ConnectionInfo } from '../../types/connection';
import ProfileStatus from '../workspace/ProfileStatus';
import { useAuthStore } from '../../store/authStore';

interface WorkspaceHeaderProps {
  workspace: Workspace;
  activeConnection: ConnectionInfo | null;
  onOpenConnectionDialog: () => void;
}

export default function WorkspaceHeader({
  workspace,
  activeConnection,
  onOpenConnectionDialog,
}: WorkspaceHeaderProps) {
  const isPrivileged = useAuthStore((s) => s.isPrivileged);

  return (
    <header className="wv-header">
      <div className="wv-header-left">
        <span className="wv-header-workspace">{workspace.name}</span>
        {isPrivileged && activeConnection && (
          <ProfileStatus
            workspaceId={workspace.id}
            connectionId={activeConnection.id}
            connectionName={activeConnection.name || activeConnection.database}
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
