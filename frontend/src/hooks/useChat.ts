import { useState, useCallback, useRef } from 'react';
import { useChatStore } from '../store/chatStore';
import { sendMessage as apiSendMessage, createEventSource, type HistoryMessage } from '../services/api';
import type { ChatMessage, AgentStep, InsightResult } from '../types/chat';

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
    async (content: string, connectionId: string, mode: 'quick' | 'deep' = 'quick', customerScope: string = '') => {
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

        await apiSendMessage(sessionId, content, connectionId, mode, workspaceId || '', history, customerScope);
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
