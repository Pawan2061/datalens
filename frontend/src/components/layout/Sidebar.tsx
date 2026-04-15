import { MessageSquare, Plus } from 'lucide-react';
import type { ChatSession } from '../../types/chat';

interface SidebarProps {
  sessions: ChatSession[];
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewChat: () => void;
}

export default function Sidebar({ sessions, activeSessionId, onSelectSession, onNewChat }: SidebarProps) {
  const sortedSessions = [...sessions].sort((a, b) => b.createdAt - a.createdAt);

  const todayStart = new Date().setHours(0, 0, 0, 0);
  const yesterdayStart = todayStart - 86400000;

  const today = sortedSessions.filter(s => s.createdAt >= todayStart);
  const yesterday = sortedSessions.filter(s => s.createdAt >= yesterdayStart && s.createdAt < todayStart);
  const older = sortedSessions.filter(s => s.createdAt < yesterdayStart);

  const renderGroup = (label: string, items: ChatSession[]) => {
    if (items.length === 0) return null;
    return (
      <div className="mb-5">
        <p className="px-3 mb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-white/25">{label}</p>
        <div className="space-y-px">
          {items.map((session) => (
            <button
              key={session.id}
              onClick={() => onSelectSession(session.id)}
              className={`w-full text-left px-3 py-2 rounded-lg text-[13px] leading-snug transition-all duration-150 truncate block ${
                session.id === activeSessionId
                  ? 'bg-white/[0.08] text-white font-medium'
                  : 'text-white/50 hover:bg-white/[0.04] hover:text-white/70'
              }`}
            >
              {session.title}
            </button>
          ))}
        </div>
      </div>
    );
  };

  return (
    <aside className="w-[240px] bg-[#191a2c] flex flex-col shrink-0">
      <div className="p-3">
        <button
          onClick={onNewChat}
          className="w-full flex items-center gap-2 px-3 py-2.5 rounded-xl text-[13px] font-medium text-white/60 border border-white/[0.08] hover:bg-white/[0.04] hover:text-white/80 hover:border-white/[0.12] transition-all duration-150"
        >
          <Plus className="w-4 h-4" />
          New chat
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-2 pb-4">
        {sortedSessions.length === 0 ? (
          <div className="px-3 py-16 text-center">
            <div className="w-10 h-10 rounded-xl bg-white/[0.05] flex items-center justify-center mx-auto mb-3">
              <MessageSquare className="w-5 h-5 text-white/15" />
            </div>
            <p className="text-[13px] text-white/25 leading-relaxed">
              Your conversations<br />will appear here
            </p>
          </div>
        ) : (
          <>
            {renderGroup('Today', today)}
            {renderGroup('Yesterday', yesterday)}
            {renderGroup('Previous', older)}
          </>
        )}
      </div>

      {/* Bottom section */}
      <div className="p-3 border-t border-white/[0.06]">
        <div className="flex items-center gap-2.5 px-2">
          <div className="w-7 h-7 rounded-full bg-gradient-to-br from-brand-400 to-brand-600 flex items-center justify-center text-[11px] font-bold text-white">
            DL
          </div>
          <span className="text-[12px] text-white/40">DataLens v1.0</span>
        </div>
      </div>
    </aside>
  );
}
