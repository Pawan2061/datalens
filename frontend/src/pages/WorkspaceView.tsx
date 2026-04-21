import { useState, useCallback, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useChat } from '../hooks/useChat';
import { useChatStore } from '../store/chatStore';
import { useWorkspaceStore } from '../store/workspaceStore';
import { useCanvasStore } from '../store/canvasStore';
import { useWorkspaceSync } from '../hooks/useWorkspaceSync';
import WorkspaceHeader from '../components/layout/WorkspaceHeader';
import WorkspaceSidebar from '../components/layout/WorkspaceSidebar';
import AppSidebar from '../components/layout/AppSidebar';
import SplitPanel from '../components/layout/SplitPanel';
import ChatPanel from '../components/chat/ChatPanel';
import CanvasPanel from '../components/canvas/CanvasPanel';
import ConnectionDialog from '../components/connections/ConnectionDialog';
import ConfirmDialog from '../components/common/ConfirmDialog';
import MetricsBar from '../components/workspace/MetricsBar';
import type { ConnectionInfo } from '../types/connection';
import type { InsightResult } from '../types/chat';
import { refreshQuery, fetchCustomers } from '../services/api';

export default function WorkspaceView() {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const navigate = useNavigate();
  const workspace = useWorkspaceStore((s) => s.workspaces.find((w) => w.id === workspaceId));
  const setActiveWorkspace = useWorkspaceStore((s) => s.setActiveWorkspace);
  const addConnectionToWorkspace = useWorkspaceStore((s) => s.addConnectionToWorkspace);
  const setScopeCustomers = useWorkspaceStore((s) => s.setScopeCustomers);
  const addBlocksFromInsight = useCanvasStore((s) => s.addBlocksFromInsight);
  const replaceBlocksByMessageId = useCanvasStore((s) => s.replaceBlocksByMessageId);
  const renameSession = useChatStore((s) => s.renameSession);
  const deleteSession = useChatStore((s) => s.deleteSession);
  const deleteMessage = useChatStore((s) => s.deleteMessage);
  const setMessageFeedback = useChatStore((s) => s.setMessageFeedback);
  const clearAllSessions = useChatStore((s) => s.clearAllSessions);

  // Sync workspace data from Cosmos DB
  useWorkspaceSync(workspaceId);

  const { sendMessage, isLoading, sessions: allSessions, activeSession, setActiveSession } = useChat(workspaceId);

  // Filter sessions to only show ones for this workspace
  const sessions = allSessions.filter(
    (s) => s.workspaceId === workspaceId || !s.workspaceId
  );

  const [connections, setConnections] = useState<ConnectionInfo[]>([]);
  const [activeConnectionId, setActiveConnectionId] = useState<string | null>(null);
  const [showConnectionDialog, setShowConnectionDialog] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [showClearConfirm, setShowClearConfirm] = useState(false);
  const [customerScope, setCustomerScope] = useState('');
  const [customerScopeName, setCustomerScopeName] = useState('');

  useEffect(() => {
    if (workspaceId) setActiveWorkspace(workspaceId);
  }, [workspaceId, setActiveWorkspace]);

  useEffect(() => {
    if (!workspace) navigate('/');
  }, [workspace, navigate]);

  // Bootstrap: if workspace has a connection but no scope customers yet, fetch once
  useEffect(() => {
    if (!workspaceId || !activeConnectionId) return;
    if (workspace?.scopeCustomers?.length) {
      console.log('[scope] customers already loaded from store:', workspace.scopeCustomers.length);
      return;
    }
    console.log('[scope] fetching customers for connection:', activeConnectionId);
    fetchCustomers(activeConnectionId)
      .then((res) => {
        console.log('[scope] fetch result:', res);
        if (res.customers.length > 0) {
          setScopeCustomers(workspaceId, res.customers);
          console.log('[scope] saved', res.customers.length, 'customers to workspace');
        } else {
          console.warn('[scope] fetch returned 0 customers. error:', res.error);
        }
      })
      .catch((err) => console.error('[scope] fetch error:', err));
  }, [workspaceId, activeConnectionId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-restore saved connections on workspace load + validate with backend
  useEffect(() => {
    if (!workspace) return;
    const saved = workspace.connections;
    if (saved.length > 0 && !activeConnectionId) {
      // Workspace has saved connections — restore the first one
      setActiveConnectionId(saved[0].id);

      // Validate connection still exists on backend (non-blocking)
      import('../services/api').then(({ testConnection }) => {
        testConnection(saved[0].id).catch(() => {
          // Connection no longer exists on backend — keep showing it but mark disconnected
          console.warn(`Connection ${saved[0].id} not found on backend`);
        });
      });
    }
  }, [workspace?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Build active connection: prefer workspace-stored connections, then local state
  const activeConnection: ConnectionInfo | null = (() => {
    if (activeConnectionId) {
      const wsConn = workspace?.connections.find((c) => c.id === activeConnectionId);
      if (wsConn) return wsConn;
      return connections.find((c) => c.id === activeConnectionId) || null;
    }
    return null;
  })();

  const hasConnection = activeConnectionId !== null;

  const handleScopeChange = useCallback((id: string, name: string) => {
    setCustomerScope(id);
    setCustomerScopeName(name);
  }, []);

  const handleSend = useCallback(
    (message: string, mode: 'quick' | 'deep' = 'quick') => {
      const connId = activeConnectionId || '';
      sendMessage(message, connId, mode, customerScope, customerScopeName);
    },
    [sendMessage, activeConnectionId, customerScope]
  );

  const handleFollowUp = useCallback(
    (question: string) => {
      handleSend(question, 'quick');
    },
    [handleSend]
  );

  // Manual push to canvas (for Quick Insight mode)
  const handlePushToCanvas = useCallback(
    (insight: InsightResult, messageId: string) => {
      if (!workspaceId) return;
      const existingBlocks = useCanvasStore.getState().getBlocks(workspaceId);
      const alreadyHasBlocks = existingBlocks.some((b) => b.sourceMessageId === messageId);
      if (!alreadyHasBlocks) {
        // Find user query from chat session
        let userQuery = '';
        if (activeSession) {
          const msgIdx = activeSession.messages.findIndex((m) => m.id === messageId);
          if (msgIdx > 0 && activeSession.messages[msgIdx - 1].role === 'user') {
            userQuery = activeSession.messages[msgIdx - 1].content;
          }
        }
        addBlocksFromInsight(workspaceId, insight, messageId, {
          skipNarrative: true,
          analysisMode: 'quick',
          sourceQuery: userQuery,
          sessionId: activeSession?.id,
        });
      }
    },
    [workspaceId, addBlocksFromInsight, activeSession]
  );

  // Delete a message (and its paired response)
  const handleDeleteMessage = useCallback(
    (messageId: string) => {
      const sessionId = activeSession?.id;
      if (!sessionId) return;
      deleteMessage(sessionId, messageId);
    },
    [activeSession?.id, deleteMessage]
  );

  // Feedback on AI response
  const handleFeedback = useCallback(
    (messageId: string, feedback: 'positive' | 'negative' | null) => {
      const sessionId = activeSession?.id;
      if (!sessionId) return;
      setMessageFeedback(sessionId, messageId, feedback);
    },
    [activeSession?.id, setMessageFeedback]
  );

  // Refresh all canvas queries — re-runs SQL against the real database (or demo simulator for mock)
  const handleRefreshCanvas = useCallback(async () => {
    if (!workspaceId || isRefreshing) return;
    setIsRefreshing(true);

    const blocks = useCanvasStore.getState().getBlocks(workspaceId);
    // Only refresh blocks belonging to the active session
    const sessionBlocks = activeSession
      ? blocks.filter((b) => b.sessionId === activeSession.id || !b.sessionId)
      : blocks;
    const uniqueMessageIds = [...new Set(sessionBlocks.map((b) => b.sourceMessageId))];

    const chatState = useChatStore.getState();
    const allSessions = chatState.sessions;
    const connId = activeConnectionId || '';

    for (const msgId of uniqueMessageIds) {
      let userContent = '';
      let mode: 'quick' | 'deep' = 'quick';

      for (const session of allSessions) {
        const msgIdx = session.messages.findIndex((m) => m.id === msgId);
        if (msgIdx !== -1) {
          const assistantMsg = session.messages[msgIdx];
          mode = assistantMsg.analysisMode || 'quick';
          if (msgIdx > 0 && session.messages[msgIdx - 1].role === 'user') {
            userContent = session.messages[msgIdx - 1].content;
          }
          break;
        }
      }

      if (!userContent || !connId) continue;

      try {
        const result = await refreshQuery(userContent, connId, mode);

        const tempId = `__refresh_${msgId}`;
        const store = useCanvasStore.getState();
        store.addBlocksFromInsight(tempId, result, msgId, {
          skipNarrative: mode === 'quick',
          analysisMode: mode,
          sourceQuery: userContent,
          sessionId: activeSession?.id,
        });
        const newBlocks = useCanvasStore.getState().getBlocks(tempId);
        store.clearCanvas(tempId);
        replaceBlocksByMessageId(workspaceId, msgId, newBlocks);
      } catch (err) {
        console.error(`Failed to refresh canvas block for message ${msgId}:`, err);
      }
    }

    setIsRefreshing(false);
  }, [workspaceId, isRefreshing, replaceBlocksByMessageId, activeConnectionId, activeSession]);

  const handleConnect = useCallback((connection: ConnectionInfo) => {
    if (workspaceId) {
      addConnectionToWorkspace(workspaceId, connection);
      // Fetch and persist customer list for this workspace (one-time per connection setup)
      if (!workspace?.scopeCustomers?.length) {
        fetchCustomers(connection.id)
          .then((res) => {
            if (res.customers.length > 0 && workspaceId) {
              setScopeCustomers(workspaceId, res.customers);
            }
          })
          .catch(() => {});
      }
    }
    setConnections((prev) => [...prev, connection]);
    setActiveConnectionId(connection.id);
  }, [workspaceId, addConnectionToWorkspace, setScopeCustomers, workspace?.scopeCustomers?.length]);

  const handleSelectConnection = useCallback((id: string) => {
    setActiveConnectionId(id);
  }, []);

  const handleNewChat = useCallback(() => {
    setActiveSession('');
  }, [setActiveSession]);

  const handleRenameSession = useCallback(
    (sessionId: string, title: string) => {
      renameSession(sessionId, title);
    },
    [renameSession]
  );

  const handleDeleteSession = useCallback(
    (sessionId: string) => {
      deleteSession(sessionId);
    },
    [deleteSession]
  );

  const handleClearAllSessions = useCallback(() => {
    setShowClearConfirm(true);
  }, []);

  const confirmClearAll = useCallback(() => {
    if (workspaceId) {
      clearAllSessions(workspaceId);
    } else {
      sessions.forEach((s) => deleteSession(s.id));
    }
    setShowClearConfirm(false);
  }, [workspaceId, sessions, deleteSession, clearAllSessions]);

  // Auto-push insights to canvas ONLY for Deep Analysis mode
  useEffect(() => {
    if (!activeSession || !workspaceId) return;
    const lastMessage = activeSession.messages.at(-1);
    if (
      lastMessage?.role === 'assistant' &&
      lastMessage.insightResult &&
      !lastMessage.isStreaming &&
      lastMessage.analysisMode === 'deep'
    ) {
      const existingBlocks = useCanvasStore.getState().getBlocks(workspaceId);
      const alreadyHasBlocks = existingBlocks.some((b) => b.sourceMessageId === lastMessage.id);
      if (!alreadyHasBlocks) {
        // Find user query from the message before the assistant response
        const msgIdx = activeSession.messages.findIndex((m) => m.id === lastMessage.id);
        let userQuery = '';
        if (msgIdx > 0 && activeSession.messages[msgIdx - 1].role === 'user') {
          userQuery = activeSession.messages[msgIdx - 1].content;
        }
        addBlocksFromInsight(workspaceId, lastMessage.insightResult, lastMessage.id, {
          analysisMode: 'deep',
          sourceQuery: userQuery,
          sessionId: activeSession.id,
        });
      }
    }
  }, [activeSession?.messages, workspaceId, addBlocksFromInsight]);

  if (!workspace) return null;

  const canvasTitle = activeSession?.title || undefined;

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'row' }}>
      <AppSidebar activePage="workspace" />

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, height: '100%', overflow: 'hidden' }}>
        <WorkspaceHeader
          workspace={workspace}
          activeConnection={activeConnection}
          onOpenConnectionDialog={() => setShowConnectionDialog(true)}
        />
        <MetricsBar sessions={sessions} />

        <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0, position: 'relative' }}>
          <WorkspaceSidebar
            sessions={sessions}
            activeSessionId={activeSession?.id || null}
            onSelectSession={setActiveSession}
            onNewChat={handleNewChat}
            onRenameSession={handleRenameSession}
            onDeleteSession={handleDeleteSession}
            onClearAllSessions={handleClearAllSessions}
          />

          <SplitPanel
            left={
              <ChatPanel
                session={activeSession}
                isLoading={isLoading}
                hasConnection={hasConnection}
                scopeCustomers={workspace?.scopeCustomers || []}
                customerScope={customerScope}
                customerScopeName={customerScopeName}
                onScopeChange={handleScopeChange}
                onSend={handleSend}
                onFollowUp={handleFollowUp}
                onPushToCanvas={handlePushToCanvas}
                onDeleteMessage={handleDeleteMessage}
                onFeedback={handleFeedback}
                compact={true}
              />
            }
            right={
              <CanvasPanel
                workspaceId={workspaceId!}
                activeSessionId={activeSession?.id || null}
                onFollowUp={handleFollowUp}
                canvasTitle={canvasTitle}
                onRefreshCanvas={handleRefreshCanvas}
                isRefreshing={isRefreshing}
              />
            }
            defaultLeftWidth={540}
            minLeftWidth={360}
            minRightWidth={340}
          />
        </div>
      </div>

      <ConnectionDialog
        isOpen={showConnectionDialog}
        onClose={() => setShowConnectionDialog(false)}
        onConnect={handleConnect}
        connections={[...(workspace?.connections || []), ...connections.filter((c) => !workspace?.connections.some((wc) => wc.id === c.id))]}
        activeConnectionId={activeConnectionId}
        onSelectConnection={handleSelectConnection}
      />

      <ConfirmDialog
        isOpen={showClearConfirm}
        title="Clear all chat history"
        message="This will permanently delete all conversations in this workspace. This action cannot be undone."
        confirmLabel="Clear All"
        variant="danger"
        onConfirm={confirmClearAll}
        onCancel={() => setShowClearConfirm(false)}
      />
    </div>
  );
}
