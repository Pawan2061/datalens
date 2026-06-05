import { useState, useCallback, useRef } from 'react';
import { useChatStore } from '../store/chatStore';
import { useAuthStore } from '../store/authStore';
import { sendMessage as apiSendMessage, sendDataEmail, createEventSource, type HistoryMessage } from '../services/api';
import type { ChatMessage, AgentStep, InsightResult } from '../types/chat';

const EMAIL_RE = /([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})/;

function detectEmailIntent(text: string): string | null {
  const m = EMAIL_RE.exec(text);
  if (!m) return null;
  const email = m[1];

  // Hindi/Hinglish send verbs (bhejna, bhejo, bhej do, etc.) are unambiguous
  if (/\bbhej(?:na|o|do|de|dena|ne)?\b/i.test(text)) return email;

  // Hinglish destination marker right after the email address: "X@y.com pe …" / "X@y.com ko …"
  const after = text.slice(m.index + email.length);
  if (/^\s*(?:pe|ko)\b/i.test(after)) return email;

  // English: send/forward/share/mail/email + destination prep (to/with) immediately before the address
  const before = text.slice(0, m.index);
  if (/\b(?:send|forward|share|mail|email)\b.{0,80}?\b(?:to|with)\b\s*$/i.test(before)) return email;

  return null;
}

function hasExportableInsight(ir: InsightResult): boolean {
  return (ir.tables?.length ?? 0) > 0 ||
    (ir.charts ?? []).some(
      (c) => !['kpi', 'gauge'].includes(c.chart_type) && (c.data?.length ?? 0) > 0,
    );
}

function generateId(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return Date.now().toString(36) + Math.random().toString(36).slice(2);
  }
}

export function useChat(workspaceId?: string) {
  // Use individual selectors to avoid subscribing to entire store
  const sessions = useChatStore((s) => s.sessions);
  const activeSessionId = useChatStore((s) => s.activeSessionId);
  const createSession = useChatStore((s) => s.createSession);
  const addMessage = useChatStore((s) => s.addMessage);
  const addStep = useChatStore((s) => s.addStep);
  const setInsightResult = useChatStore((s) => s.setInsightResult);
  const setMessageStreaming = useChatStore((s) => s.setMessageStreaming);
  const appendNarrativeChunk = useChatStore((s) => s.appendNarrativeChunk);
  const setActiveSession = useChatStore((s) => s.setActiveSession);

  const [isLoading, setIsLoading] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);

  const activeSession = sessions.find((s) => s.id === activeSessionId);

  const sendMessage = useCallback(
    async (content: string, connectionId: string, mode: 'quick' | 'deep' = 'quick', customerScope: string = '', customerScopeName: string = '') => {
      setIsLoading(true);

      // Read fresh state at call time
      let sessionId = useChatStore.getState().activeSessionId;
      if (!sessionId) {
        sessionId = generateId();
        createSession(sessionId, workspaceId);
      }

      const userMessage: ChatMessage = {
        id: generateId(),
        role: 'user',
        content,
        timestamp: Date.now(),
        steps: [],
      };
      addMessage(sessionId, userMessage);

      // ── Email intent: bypass LLM entirely ─────────────────────────────────
      const emailTarget = detectEmailIntent(content);
      if (emailTarget) {
        const snapshot = useChatStore.getState().sessions;
        const thisSession = snapshot.find((s) => s.id === sessionId);
        const lastInsight =
          thisSession?.messages
            .slice()
            .reverse()
            .find((m) => m.role === 'assistant' && m.insightResult && hasExportableInsight(m.insightResult))
            ?.insightResult ?? null;

        let replyContent: string;
        if (!lastInsight) {
          replyContent =
            "There's no recent query result to send. Run an analysis first, then ask me to email it.";
        } else {
          try {
            await sendDataEmail(
              emailTarget,
              lastInsight.summary.title,
              lastInsight.tables,
              lastInsight.charts,
            );
            replyContent = `Sent to **${emailTarget}** — the data is attached as an Excel file.`;
          } catch (err) {
            replyContent = `Could not send email to ${emailTarget}: ${err instanceof Error ? err.message : 'unknown error'}`;
          }
        }

        addMessage(sessionId, {
          id: generateId(),
          role: 'assistant',
          content: replyContent,
          timestamp: Date.now(),
          steps: [],
          isStreaming: false,
        });
        setIsLoading(false);
        return;
      }
      // ── end email intent ───────────────────────────────────────────────────

      const assistantMessageId = generateId();
      const assistantMessage: ChatMessage = {
        id: assistantMessageId,
        role: 'assistant',
        content: '',
        timestamp: Date.now(),
        steps: [],
        isStreaming: true,
        analysisMode: mode,
      };
      addMessage(sessionId, assistantMessage);

      // ── Backend mode ──
      let requestFailed = false;
      try {
        if (eventSourceRef.current) {
          eventSourceRef.current.close();
        }

        const currentSessionId = sessionId;
        const es = createEventSource(currentSessionId);
        eventSourceRef.current = es;

        // Build condensed conversation history for the agent
        const currentState = useChatStore.getState();
        const currentSession = currentState.sessions.find((s) => s.id === sessionId);
        const history: HistoryMessage[] = [];
        if (currentSession) {
          // Take recent messages (exclude the user msg + assistant msg we just added)
          const prior = currentSession.messages.slice(0, -2).slice(-10);
          for (const msg of prior) {
            if (msg.role === 'user') {
              history.push({ role: 'user', content: msg.content.slice(0, 300) });
            } else if (msg.role === 'assistant' && msg.insightResult) {
              const ir = msg.insightResult;
              const title = ir.summary?.title || '';
              const narr = ir.summary?.narrative || '';
              history.push({
                role: 'assistant',
                content: `[Analysis: "${title}" — ${narr.slice(0, 150)}]`,
              });
            } else if (msg.role === 'assistant' && msg.content) {
              history.push({ role: 'assistant', content: msg.content.slice(0, 200) });
            }
          }
        }

        const handleEvent = (eventType: string) => (event: MessageEvent) => {
          let parsed: Record<string, unknown>;
          try {
            parsed = JSON.parse(event.data);
          } catch {
            parsed = { content: event.data };
          }

          const stepType = eventType as AgentStep['type'];
          const validTypes: AgentStep['type'][] = [
            'thinking',
            'plan',
            'sub_query_start',
            'sub_query_result',
            'api_call_start',
            'api_call_result',
            'consolidating',
            'chart_selected',
            'clarification',
            'error',
          ];

          if (validTypes.includes(stepType)) {
            const step: AgentStep = {
              type: stepType,
              content: (parsed.content as string) || (parsed.description as string) || JSON.stringify(parsed),
              sql: parsed.sql as string | undefined,
              data: parsed.data as Record<string, unknown> | undefined,
              timestamp: Date.now(),
              completed: true,
            };
            addStep(currentSessionId, assistantMessageId, step);
          }
        };

        es.addEventListener('thinking', handleEvent('thinking'));
        es.addEventListener('plan', handleEvent('plan'));
        es.addEventListener('sub_query_start', handleEvent('sub_query_start'));
        es.addEventListener('sub_query_result', handleEvent('sub_query_result'));
        es.addEventListener('api_call_start', handleEvent('api_call_start'));
        es.addEventListener('api_call_result', handleEvent('api_call_result'));
        es.addEventListener('consolidating', handleEvent('consolidating'));
        es.addEventListener('narrative_chunk', (event: MessageEvent) => {
          try {
            const parsed = JSON.parse(event.data);
            const token = parsed.token as string;
            if (token) {
              appendNarrativeChunk(currentSessionId, assistantMessageId, token);
            }
          } catch {
            // ignore malformed chunks
          }
        });
        es.addEventListener('chart_selected', handleEvent('chart_selected'));
        es.addEventListener('clarification', (event: MessageEvent) => {
          try {
            const parsed = JSON.parse(event.data);
            const question = (parsed.question as string) || event.data;
            // Show clarification as assistant content so user can reply
            addStep(currentSessionId, assistantMessageId, {
              type: 'clarification',
              content: question,
              timestamp: Date.now(),
              completed: true,
            });
            // Update the assistant message content with the clarification question
            const store = useChatStore.getState();
            const session = store.sessions.find((s) => s.id === currentSessionId);
            if (session) {
              const msg = session.messages.find((m) => m.id === assistantMessageId);
              if (msg) {
                msg.content = question;
              }
            }
          } catch {
            // fallback
          }
        });
        es.addEventListener('error', handleEvent('error'));

        es.addEventListener('final_result', (event: MessageEvent) => {
          try {
            const insightResult: InsightResult = JSON.parse(event.data);
            setInsightResult(currentSessionId, assistantMessageId, insightResult);
          } catch {
            addStep(currentSessionId, assistantMessageId, {
              type: 'error',
              content: 'Failed to parse final result',
              timestamp: Date.now(),
              completed: true,
            });
          }
        });

        es.addEventListener('done', () => {
          setMessageStreaming(currentSessionId, assistantMessageId, false);
          setIsLoading(false);
          es.close();
          if (eventSourceRef.current === es) {
            eventSourceRef.current = null;
          }
          // Refresh the user so today_cost_usd (and the cost warning banner)
          // reflect the spend just recorded by this turn. Fire-and-forget;
          // swallow errors so a flaky /me never surfaces as an unhandled rejection.
          void useAuthStore.getState().refreshUser().catch(() => {});
        });

        es.onerror = () => {
          if (requestFailed) {
            return;
          }
          addStep(currentSessionId, assistantMessageId, {
            type: 'error',
            content: 'Connection to server lost',
            timestamp: Date.now(),
            completed: true,
          });
          setMessageStreaming(currentSessionId, assistantMessageId, false);
          setIsLoading(false);
          es.close();
          if (eventSourceRef.current === es) {
            eventSourceRef.current = null;
          }
        };

        await apiSendMessage(sessionId, content, connectionId, mode, workspaceId || '', history, customerScope, customerScopeName);
      } catch (error) {
        requestFailed = true;
        if (eventSourceRef.current) {
          eventSourceRef.current.close();
          eventSourceRef.current = null;
        }
        const errorMessage = error instanceof Error ? error.message : 'Unknown error occurred';
        addStep(sessionId, assistantMessageId, {
          type: 'error',
          content: errorMessage,
          timestamp: Date.now(),
          completed: true,
        });
        setMessageStreaming(sessionId, assistantMessageId, false);
        setIsLoading(false);
      }
    },
    [createSession, addMessage, addStep, setInsightResult, setMessageStreaming, appendNarrativeChunk, workspaceId]
  );

  return {
    sendMessage,
    isLoading,
    sessions,
    activeSession,
    setActiveSession,
  };
}
