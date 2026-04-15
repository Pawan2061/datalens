import { Database, Zap, Plus } from 'lucide-react';
import type { ConnectionInfo } from '../../types/connection';

interface HeaderProps {
  activeConnection: ConnectionInfo | null;
  onOpenConnectionDialog: () => void;
  onNewChat: () => void;
}

export default function Header({ activeConnection, onOpenConnectionDialog, onNewChat }: HeaderProps) {
  return (
    <header className="h-[52px] border-b border-border-light bg-surface flex items-center justify-between px-5 shrink-0">
      <div className="flex items-center gap-2.5">
        <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 flex items-center justify-center shadow-sm">
          <Zap className="w-3.5 h-3.5 text-white" />
        </div>
        <span className="text-[15px] font-semibold tracking-[-0.01em] text-text-primary">DataLens</span>
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={onNewChat}
          className="flex items-center gap-1.5 px-3 py-1.5 text-[13px] font-medium text-text-secondary hover:text-text-primary hover:bg-surface-hover rounded-lg transition-all duration-150"
        >
          <Plus className="w-3.5 h-3.5" />
          New chat
        </button>

        <div className="w-px h-5 bg-border-light mx-0.5" />

        <button
          onClick={onOpenConnectionDialog}
          className={`flex items-center gap-2 pl-2.5 pr-3 py-1.5 rounded-full text-[13px] font-medium transition-all duration-150 ${
            activeConnection
              ? 'bg-success-bg text-success hover:opacity-80'
              : 'bg-surface-hover text-text-secondary hover:bg-surface-active'
          }`}
        >
          <div className={`w-[7px] h-[7px] rounded-full ${activeConnection ? 'bg-success animate-pulse-glow' : 'bg-text-placeholder'}`} />
          <Database className="w-3.5 h-3.5" />
          <span>{activeConnection ? (activeConnection.name || activeConnection.database) : 'Connect'}</span>
        </button>
      </div>
    </header>
  );
}
