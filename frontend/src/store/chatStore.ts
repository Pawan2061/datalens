import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { ChatMessage, ChatSession, AgentStep, InsightResult } from '../types/chat';
import {
  upsertSession,
  deleteSessionOnBackend,
  clearAllSessionsOnBackend,
  fetchSessionList,
  fetchSession,
} from '../services/api';

// ── Debounce helper ─────────────────────────────────────────────────
const _saveTimers: Record<string, ReturnType<typeof setTimeout>> = {};

function debouncedSaveSession(sessionId: string, delayMs = 2000) {
  if (_saveTimers[sessionId]) clearTimeout(_saveTimers[sessionId]);
  _saveTimers[sessionId] = setTimeout(() => {
    const state = useChatStore.getState();
    const session = state.sessions.find((s) => s.id === sessionId);
    if (session?.workspaceId) {
      state.syncSessionToBackend(session);
    }
    delete _saveTimers[sessionId];
  }, delayMs);
}

// ── Store ───────────────────────────────────────────────────────────
interface ChatState {
  sessions: ChatSession[];
  activeSessionId: string | null;
  _backendLoaded: Record<string, boolean>;

  createSession: (id: string, workspaceId?: string) => void;
  setActiveSession: (id: string) => void;
  addMessage: (sessionId: string, message: ChatMessage) => void;
  addStep: (sessionId: string, messageId: string, step: AgentStep) => void;
  setInsightResult: (sessionId: string, messageId: string, result: InsightResult) => void;
  setMessageStreaming: (sessionId: string, messageId: string, streaming: boolean) => void;
  appendNarrativeChunk: (sessionId: string, messageId: string, token: string) => void;
  renameSession: (sessionId: string, title: string) => void;
  deleteSession: (sessionId: string) => void;
  deleteMessage: (sessionId: string, messageId: string) => void;
  setMessageFeedback: (sessionId: string, messageId: string, feedback: 'positive' | 'negative' | null) => void;
  getActiveSession: () => ChatSession | undefined;

  // Persistence sync
  loadSessionsFromBackend: (workspaceId: string) => Promise<void>;
  syncSessionToBackend: (session: ChatSession) => Promise<void>;
  clearAllSessions: (workspaceId: string) => void;
}

export const useChatStore = create<ChatState>()(
  persist(
    (set, get) => ({
      sessions: [],
      activeSessionId: null,
      _backendLoaded: {},

      createSession: (id: string, workspaceId?: string) => {
        set((state) => ({
          sessions: [
            ...state.sessions,
            {
              id,
              title: 'New Chat',
              messages: [],
              createdAt: Date.now(),
              workspaceId,
            },
          ],
          activeSessionId: id,
        }));
      },

      setActiveSession: (id: string) => {
        set({ activeSessionId: id });
      },

      addMessage: (sessionId: string, message: ChatMessage) => {
        set((state) => ({
          sessions: state.sessions.map((session) => {
            if (session.id !== sessionId) return session;
            const updatedMessages = [...session.messages, message];
            const title =
              session.messages.length === 0 && message.role === 'user'
                ? message.content.slice(0, 60) + (message.content.length > 60 ? '...' : '')
                : session.title;
            return { ...session, messages: updatedMessages, title };
          }),
        }));
      },

      addStep: (sessionId: string, messageId: string, step: AgentStep) => {
        set((state) => ({
          sessions: state.sessions.map((session) => {
            if (session.id !== sessionId) return session;
            return {
              ...session,
              messages: session.messages.map((msg) => {
                if (msg.id !== messageId) return msg;
                return { ...msg, steps: [...msg.steps, step] };
              }),
            };
          }),
        }));
      },

      setInsightResult: (sessionId: string, messageId: string, result: InsightResult) => {
        set((state) => ({
          sessions: state.sessions.map((session) => {
            if (session.id !== sessionId) return session;
            return {
              ...session,
              messages: session.messages.map((msg) => {
                if (msg.id !== messageId) return msg;
                return { ...msg, insightResult: result };
              }),
            };
          }),
        }));
      },

      setMessageStreaming: (sessionId: string, messageId: string, streaming: boolean) => {
        set((state) => ({
          sessions: state.sessions.map((session) => {
            if (session.id !== sessionId) return session;
            return {
              ...session,
              messages: session.messages.map((msg) => {
                if (msg.id !== messageId) return msg;
                return { ...msg, isStreaming: streaming };
              }),
            };
          }),
        }));
        // When streaming ends, schedule a debounced save to backend
        if (!streaming) {
          debouncedSaveSession(sessionId, 1500);
        }
      },

      appendNarrativeChunk: (sessionId: string, messageId: string, token: string) => {
        set((state) => ({
          sessions: state.sessions.map((session) => {
            if (session.id !== sessionId) return session;
            return {
              ...session,
              messages: session.messages.map((msg) => {
                if (msg.id !== messageId) return msg;
                return { ...msg, streamingNarrative: (msg.streamingNarrative ?? '') + token };
              }),
            };
          }),
        }));
      },

      renameSession: (sessionId: string, title: string) => {
        set((state) => ({
          sessions: state.sessions.map((session) =>
            session.id === sessionId ? { ...session, title } : session
          ),
        }));
        debouncedSaveSession(sessionId, 1000);
      },

      deleteSession: (sessionId: string) => {
        const session = get().sessions.find((s) => s.id === sessionId);
        set((state) => ({
          sessions: state.sessions.filter((s) => s.id !== sessionId),
          activeSessionId: state.activeSessionId === sessionId ? null : state.activeSessionId,
        }));
        if (session?.workspaceId) {
          deleteSessionOnBackend(sessionId, session.workspaceId).catch(() => {});
        }
      },

      deleteMessage: (sessionId: string, messageId: string) => {
        set((state) => ({
          sessions: state.sessions.map((session) => {
            if (session.id !== sessionId) return session;
            const messages = session.messages;
            const idx = messages.findIndex((m) => m.id === messageId);
            if (idx === -1) return session;

            const target = messages[idx];
            let newMessages: ChatMessage[];

            if (target.role === 'user') {
              const nextMsg = messages[idx + 1];
              if (nextMsg && nextMsg.role === 'assistant') {
                newMessages = messages.filter((_, i) => i !== idx && i !== idx + 1);
              } else {
                newMessages = messages.filter((_, i) => i !== idx);
              }
            } else {
              newMessages = messages.filter((_, i) => i !== idx);
            }

            return { ...session, messages: newMessages };
          }),
        }));
        debouncedSaveSession(sessionId, 1000);
      },

      setMessageFeedback: (sessionId: string, messageId: string, feedback: 'positive' | 'negative' | null) => {
        set((state) => ({
          sessions: state.sessions.map((session) => {
            if (session.id !== sessionId) return session;
            return {
              ...session,
              messages: session.messages.map((msg) => {
                if (msg.id !== messageId) return msg;
                return { ...msg, feedback: msg.feedback === feedback ? null : feedback };
              }),
            };
          }),
        }));
        debouncedSaveSession(sessionId, 1000);
      },

      getActiveSession: () => {
        const { sessions, activeSessionId } = get();
        return sessions.find((s) => s.id === activeSessionId);
      },

      // ── Persistence sync ──────────────────────────────────────────

      loadSessionsFromBackend: async (workspaceId: string) => {
        if (get()._backendLoaded[workspaceId]) return;

        try {
          const summaries = await fetchSessionList(workspaceId);
          if (!summaries || summaries.length === 0) {
            set((state) => ({
              _backendLoaded: { ...state._backendLoaded, [workspaceId]: true },
            }));
            return;
          }

          const fullSessions: ChatSession[] = [];
          for (const summary of summaries) {
            try {
              const doc = await fetchSession(summary.id, workspaceId);
              const messages = (doc.messages as ChatMessage[]) || [];
              fullSessions.push({
                id: summary.id,
                title: summary.title || 'New Chat',
                messages: messages.map((m) => ({
                  ...m,
                  steps: m.steps || [],
                  isStreaming: false,
                })),
                createdAt: new Date(summary.created_at).getTime() || Date.now(),
                workspaceId,
              });
            } catch {
              // Skip individual session load failures
            }
          }

          set((state) => {
            const otherSessions = state.sessions.filter((s) => s.workspaceId !== workspaceId);
            // Keep local-only sessions that haven't been synced yet
            const localOnly = state.sessions.filter(
              (s) => s.workspaceId === workspaceId && !fullSessions.some((fs) => fs.id === s.id)
            );
            return {
              sessions: [...otherSessions, ...fullSessions, ...localOnly],
              _backendLoaded: { ...state._backendLoaded, [workspaceId]: true },
            };
          });
        } catch {
          set((state) => ({
            _backendLoaded: { ...state._backendLoaded, [workspaceId]: true },
          }));
        }
      },

      syncSessionToBackend: async (session: ChatSession) => {
        if (!session.workspaceId) return;
        try {
          await upsertSession(session.id, {
            workspace_id: session.workspaceId,
            title: session.title,
            messages: session.messages as unknown as Record<string, unknown>[],
          });
        } catch {
          // Silently fail — localStorage still has the data
        }
      },

      clearAllSessions: (workspaceId: string) => {
        const sessionsToDelete = get().sessions.filter((s) => s.workspaceId === workspaceId);
        set((state) => ({
          sessions: state.sessions.filter((s) => s.workspaceId !== workspaceId),
          activeSessionId: sessionsToDelete.some((s) => s.id === state.activeSessionId)
            ? null
            : state.activeSessionId,
        }));
        clearAllSessionsOnBackend(workspaceId).catch(() => {});
      },
    }),
    {
      name: 'datalens-chat',
      partialize: (state) => ({
        sessions: state.sessions,
        activeSessionId: state.activeSessionId,
      }),
      onRehydrateStorage: () => {
        return (state) => {
          if (state) {
            state.sessions = state.sessions.map((session) => ({
              ...session,
              messages: session.messages.map((msg) =>
                msg.isStreaming ? { ...msg, isStreaming: false } : msg
              ),
            }));
          }
        };
      },
    }
  )
);
