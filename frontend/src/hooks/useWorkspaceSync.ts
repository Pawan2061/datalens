import { useEffect } from 'react';
import { useAuthStore } from '../store/authStore';
import { useWorkspaceStore } from '../store/workspaceStore';
import { useChatStore } from '../store/chatStore';
import { useCanvasStore } from '../store/canvasStore';

/**
 * Orchestrates loading workspace data (sessions + canvas) from the backend
 * when entering a workspace. Also loads workspaces list on first auth.
 */
export function useWorkspaceSync(workspaceId: string | undefined) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const loadWorkspacesFromBackend = useWorkspaceStore((s) => s.loadWorkspacesFromBackend);
  const loadSessionsFromBackend = useChatStore((s) => s.loadSessionsFromBackend);
  const loadCanvasFromBackend = useCanvasStore((s) => s.loadCanvasFromBackend);

  // Load workspaces list from backend once on auth
  useEffect(() => {
    if (isAuthenticated) {
      loadWorkspacesFromBackend();
    }
  }, [isAuthenticated, loadWorkspacesFromBackend]);

  // Load sessions + canvas for the current workspace
  useEffect(() => {
    if (!workspaceId || !isAuthenticated) return;

    loadSessionsFromBackend(workspaceId);
    loadCanvasFromBackend(workspaceId);
  }, [workspaceId, isAuthenticated, loadSessionsFromBackend, loadCanvasFromBackend]);
}
