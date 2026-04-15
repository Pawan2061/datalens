import { useState, useRef, useEffect } from 'react';
import { MessageSquare, Plus, Trash2, PanelLeftClose, PanelLeftOpen } from 'lucide-react';
import type { ChatSession } from '../../types/chat';

interface WorkspaceSidebarProps {
  sessions: ChatSession[];
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
  onRenameSession?: (sessionId: string, title: string) => void;
  onDeleteSession?: (sessionId: string) => void;
  onClearAllSessions?: () => void;
}

export default function WorkspaceSidebar({
  sessions,
  activeSessionId,
  onSelectSession,
  onNewChat,
  onRenameSession,
  onDeleteSession,
  onClearAllSessions,
}: WorkspaceSidebarProps) {
  const [collapsed, setCollapsed] = useState(false);

  const sortedSessions = [...sessions].sort((a, b) => b.createdAt - a.createdAt);

  const todayStart = new Date().setHours(0, 0, 0, 0);
  const yesterdayStart = todayStart - 86400000;

  const today = sortedSessions.filter((s) => s.createdAt >= todayStart);
  const yesterday = sortedSessions.filter((s) => s.createdAt >= yesterdayStart && s.createdAt < todayStart);
  const older = sortedSessions.filter((s) => s.createdAt < yesterdayStart);

  const renderGroup = (label: string, items: ChatSession[]) => {
    if (items.length === 0) return null;
    return (
      <div className="wv-sb-group">
        <p className="wv-sb-group-label">{label}</p>
        <div>
          {items.map((session) => (
            <SessionItem
              key={session.id}
              session={session}
              isActive={session.id === activeSessionId}
              onSelect={() => onSelectSession(session.id)}
              onRename={onRenameSession ? (title: string) => onRenameSession(session.id, title) : undefined}
              onDelete={onDeleteSession ? () => onDeleteSession(session.id) : undefined}
            />
          ))}
        </div>
      </div>
    );
  };

  /* ─── Collapsed state ─── */
  if (collapsed) {
    return (
      <div className="wv-sidebar wv-sidebar--collapsed">
        <div className="wv-sb-collapsed-icons">
          <button
            className="wv-sb-icon-btn"
            onClick={() => setCollapsed(false)}
            title="Expand chat history"
          >
            <PanelLeftOpen size={18} />
          </button>
          <button
            className="wv-sb-icon-btn"
            onClick={onNewChat}
            title="New chat"
          >
            <Plus size={18} />
          </button>
          {sessions.length > 0 && (
            <button
              className="wv-sb-icon-btn wv-sb-icon-btn--badge"
              onClick={() => setCollapsed(false)}
              title={`${sessions.length} conversation${sessions.length === 1 ? '' : 's'}`}
            >
              <MessageSquare size={16} />
              <span className="wv-sb-badge">{sessions.length}</span>
            </button>
          )}
        </div>
      </div>
    );
  }

  /* ─── Expanded state ─── */
  return (
    <div className="wv-sidebar wv-sidebar--expanded">
      {/* Top bar: toggle + new chat */}
      <div className="wv-sb-top">
        <button
          className="wv-sb-toggle-btn"
          onClick={() => setCollapsed(true)}
          title="Collapse sidebar"
        >
          <PanelLeftClose size={18} />
        </button>
        <button onClick={onNewChat} className="wv-sb-new-btn">
          <Plus size={15} />
          New chat
        </button>
      </div>

      {/* Session list */}
      <div className="wv-sb-list">
        {sortedSessions.length === 0 ? (
          <div className="wv-sb-empty">
            <div className="wv-sb-empty-icon">
              <MessageSquare size={18} />
            </div>
            <p>Your conversations<br />will appear here</p>
          </div>
        ) : (
          <>
            {renderGroup('Today', today)}
            {renderGroup('Yesterday', yesterday)}
            {renderGroup('Previous', older)}
          </>
        )}
      </div>

      {/* Footer: Clear all history */}
      {sessions.length > 0 && onClearAllSessions && (
        <div className="wv-sb-footer">
          <button
            className="wv-sb-clear-btn"
            onClick={onClearAllSessions}
            title="Clear all chat history"
          >
            <Trash2 size={13} />
            Clear all history
          </button>
        </div>
      )}
    </div>
  );
}

function SessionItem({
  session,
  isActive,
  onSelect,
  onRename,
  onDelete,
}: {
  session: ChatSession;
  isActive: boolean;
  onSelect: () => void;
  onRename?: (title: string) => void;
  onDelete?: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [editValue, setEditValue] = useState(session.title);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editing]);

  const handleDoubleClick = () => {
    if (onRename) {
      setEditValue(session.title);
      setEditing(true);
    }
  };

  const handleSave = () => {
    const trimmed = editValue.trim();
    if (trimmed && trimmed !== session.title && onRename) {
      onRename(trimmed);
    }
    setEditing(false);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSave();
    if (e.key === 'Escape') setEditing(false);
  };

  const handleDelete = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (onDelete) onDelete();
  };

  if (editing) {
    return (
      <div className={`wv-sb-item wv-sb-item--editing ${isActive ? 'wv-sb-item--active' : ''}`}>
        <input
          ref={inputRef}
          value={editValue}
          onChange={(e) => setEditValue(e.target.value)}
          onBlur={handleSave}
          onKeyDown={handleKeyDown}
          className="wv-sb-rename-input"
        />
      </div>
    );
  }

  return (
    <div className={`wv-sb-item ${isActive ? 'wv-sb-item--active' : ''}`}>
      <button
        onClick={onSelect}
        onDoubleClick={handleDoubleClick}
        className="wv-sb-item-text"
        title="Double-click to rename"
      >
        {session.title}
      </button>
      {onDelete && (
        <button
          className="wv-sb-item-delete"
          onClick={handleDelete}
          title="Delete chat"
        >
          <Trash2 size={13} />
        </button>
      )}
    </div>
  );
}
