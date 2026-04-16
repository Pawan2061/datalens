import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Workspace, WorkspaceCreate, ScopeCustomer } from '../types/workspace';
import type { ConnectionInfo } from '../types/connection';
import {
  fetchWorkspaces,
  createWorkspaceOnBackend,
  updateWorkspaceOnBackend,
  deleteWorkspaceOnBackend,
} from '../services/api';

function generateId(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return Date.now().toString(36) + Math.random().toString(36).slice(2);
  }
}

const MOCK_WORKSPACES: Workspace[] = [];

const MOCK_IDS: string[] = [];

// ── Debounce helper ─────────────────────────────────────────────────
let _wsUpdateTimer: ReturnType<typeof setTimeout> | null = null;

function debouncedUpdateWorkspace(workspaceId: string) {
  if (_wsUpdateTimer) clearTimeout(_wsUpdateTimer);
  _wsUpdateTimer = setTimeout(() => {
    const state = useWorkspaceStore.getState();
    const ws = state.workspaces.find((w) => w.id === workspaceId);
    if (ws && state._backendSynced) {
      state.syncWorkspaceToBackend(ws);
    }
    _wsUpdateTimer = null;
  }, 1500);
}

interface WorkspaceState {
  workspaces: Workspace[];
  activeWorkspaceId: string | null;
  _backendSynced: boolean;

  setActiveWorkspace: (id: string) => void;
  getActiveWorkspace: () => Workspace | undefined;
  createWorkspace: (data: WorkspaceCreate) => Workspace;
  deleteWorkspace: (id: string) => void;
  addConnectionToWorkspace: (workspaceId: string, connection: ConnectionInfo) => void;
  removeConnectionFromWorkspace: (workspaceId: string, connectionId: string) => void;
  updateConnectionInWorkspace: (workspaceId: string, connectionId: string, updates: Partial<ConnectionInfo>) => void;
  setSelectedTables: (workspaceId: string, connectionId: string, tableNames: string[]) => void;
  setScopeCustomers: (workspaceId: string, customers: ScopeCustomer[]) => void;

  // Persistence sync
  loadWorkspacesFromBackend: () => Promise<void>;
  syncWorkspaceToBackend: (workspace: Workspace) => Promise<void>;
}

export const useWorkspaceStore = create<WorkspaceState>()(
  persist(
    (set, get) => ({
      workspaces: MOCK_WORKSPACES,
      activeWorkspaceId: null,
      _backendSynced: false,

      setActiveWorkspace: (id: string) => {
        set({ activeWorkspaceId: id });
        set((state) => ({
          workspaces: state.workspaces.map((ws) =>
            ws.id === id ? { ...ws, lastActiveAt: Date.now() } : ws
          ),
        }));
      },

      getActiveWorkspace: () => {
        const { workspaces, activeWorkspaceId } = get();
        return workspaces.find((ws) => ws.id === activeWorkspaceId);
      },

      createWorkspace: (data: WorkspaceCreate) => {
        // If a backendId is provided (workspace already created on backend),
        // use it and skip the backend creation call to avoid duplicates.
        const backendId = (data as WorkspaceCreate & { backendId?: string }).backendId;
        const newWorkspace: Workspace = {
          id: backendId || `ws-${generateId()}`,
          name: data.name,
          description: data.description,
          icon: data.icon,
          connectionIds: [],
          connections: [],
          scopeCustomers: [],
          createdAt: Date.now(),
          updatedAt: Date.now(),
          lastActiveAt: Date.now(),
        };
        set((state) => ({
          workspaces: [...state.workspaces, newWorkspace],
        }));

        // Only create on backend if no backendId was provided
        if (!backendId && get()._backendSynced) {
          createWorkspaceOnBackend({
            name: data.name,
            description: data.description,
            icon: data.icon,
          }).then((doc) => {
            if (doc.id && doc.id !== newWorkspace.id) {
              set((state) => ({
                workspaces: state.workspaces.map((ws) =>
                  ws.id === newWorkspace.id ? { ...ws, id: doc.id as string } : ws
                ),
                activeWorkspaceId: state.activeWorkspaceId === newWorkspace.id
                  ? (doc.id as string)
                  : state.activeWorkspaceId,
              }));
            }
          }).catch(() => {});
        }

        return newWorkspace;
      },

      deleteWorkspace: (id: string) => {
        set((state) => ({
          workspaces: state.workspaces.filter((ws) => ws.id !== id),
          activeWorkspaceId: state.activeWorkspaceId === id ? null : state.activeWorkspaceId,
        }));
        if (get()._backendSynced) {
          deleteWorkspaceOnBackend(id).catch(() => {});
        }
      },

      addConnectionToWorkspace: (workspaceId: string, connection: ConnectionInfo) => {
        set((state) => ({
          workspaces: state.workspaces.map((ws) => {
            if (ws.id !== workspaceId) return ws;
            if (ws.connections.some((c) => c.id === connection.id)) return ws;
            return {
              ...ws,
              connections: [...ws.connections, connection],
              connectionIds: [...ws.connectionIds, connection.id],
              updatedAt: Date.now(),
            };
          }),
        }));
        // Connection changes are critical — sync IMMEDIATELY, bypass debounce
        const ws = get().workspaces.find((w) => w.id === workspaceId);
        if (ws && !MOCK_IDS.includes(ws.id)) {
          get().syncWorkspaceToBackend(ws);
        }
      },

      removeConnectionFromWorkspace: (workspaceId: string, connectionId: string) => {
        set((state) => ({
          workspaces: state.workspaces.map((ws) => {
            if (ws.id !== workspaceId) return ws;
            return {
              ...ws,
              connections: ws.connections.filter((c) => c.id !== connectionId),
              connectionIds: ws.connectionIds.filter((id) => id !== connectionId),
              updatedAt: Date.now(),
            };
          }),
        }));
        // Connection changes are critical — sync immediately
        const ws = get().workspaces.find((w) => w.id === workspaceId);
        if (ws && !MOCK_IDS.includes(ws.id)) {
          get().syncWorkspaceToBackend(ws);
        }
      },

      updateConnectionInWorkspace: (workspaceId: string, connectionId: string, updates: Partial<ConnectionInfo>) => {
        set((state) => ({
          workspaces: state.workspaces.map((ws) => {
            if (ws.id !== workspaceId) return ws;
            return {
              ...ws,
              connections: ws.connections.map((c) =>
                c.id === connectionId ? { ...c, ...updates } : c
              ),
              updatedAt: Date.now(),
            };
          }),
        }));
        debouncedUpdateWorkspace(workspaceId);
      },

      setSelectedTables: (workspaceId: string, connectionId: string, tableNames: string[]) => {
        get().updateConnectionInWorkspace(workspaceId, connectionId, { selectedTableNames: tableNames });
      },

      setScopeCustomers: (workspaceId: string, customers: ScopeCustomer[]) => {
        set((state) => ({
          workspaces: state.workspaces.map((ws) =>
            ws.id === workspaceId
              ? { ...ws, scopeCustomers: customers, updatedAt: Date.now() }
              : ws
          ),
        }));
        // Persist to backend immediately so it survives page reloads
        const ws = get().workspaces.find((w) => w.id === workspaceId);
        if (ws && !MOCK_IDS.includes(ws.id)) {
          get().syncWorkspaceToBackend(ws);
        }
      },

      // ── Persistence sync ──────────────────────────────────────────

      loadWorkspacesFromBackend: async () => {
        try {
          const docs = await fetchWorkspaces();
          if (!docs || docs.length === 0) {
            set({ _backendSynced: true });
            return;
          }

          const backendWorkspaces: Workspace[] = docs.map((doc) => ({
            id: doc.id as string,
            name: (doc.name as string) || '',
            description: (doc.description as string) || '',
            icon: (doc.icon as string) || 'bar-chart-3',
            connectionIds: (doc.connection_ids as string[]) || [],
            connections: (doc.connections as ConnectionInfo[]) || [],
            scopeCustomers: (doc.scope_customers as ScopeCustomer[]) || [],
            createdAt: doc.created_at ? new Date(doc.created_at as string).getTime() : Date.now(),
            updatedAt: doc.updated_at ? new Date(doc.updated_at as string).getTime() : Date.now(),
            lastActiveAt: doc.last_active_at ? new Date(doc.last_active_at as string).getTime() : Date.now(),
          }));

          set((state) => {
            // Merge strategy: combine backend and local, preserving the richest data
            const merged: Workspace[] = [];

            // Keep all mock workspaces
            for (const w of state.workspaces) {
              if (MOCK_IDS.includes(w.id)) merged.push(w);
            }

            // For each backend workspace, merge with local if both exist
            for (const bw of backendWorkspaces) {
              const local = state.workspaces.find((lw) => lw.id === bw.id);
              if (local) {
                // Merge connections: keep the union of both local and backend connections
                const allConns = [...(local.connections || [])];
                for (const bc of (bw.connections || [])) {
                  if (!allConns.some((c) => c.id === bc.id)) {
                    allConns.push(bc);
                  }
                }
                const allConnIds = [...new Set([
                  ...(local.connectionIds || []),
                  ...(bw.connectionIds || []),
                ])];
                // Prefer backend scope_customers if present, else fall back to local
                const scopeCustomers = (bw.scopeCustomers?.length ? bw.scopeCustomers : local.scopeCustomers) || [];
                merged.push({
                  ...bw,
                  connections: allConns,
                  connectionIds: allConnIds,
                  scopeCustomers,
                  // Use the most recent timestamps
                  updatedAt: Math.max(local.updatedAt, bw.updatedAt),
                  lastActiveAt: Math.max(local.lastActiveAt || 0, bw.lastActiveAt || 0),
                });
              } else {
                merged.push(bw);
              }
            }

            // NOTE: Do NOT keep local-only workspaces — they may belong to a
            // different user who was previously logged in on this browser.

            return {
              workspaces: merged,
              _backendSynced: true,
            };
          });
        } catch {
          set({ _backendSynced: true });
        }
      },

      syncWorkspaceToBackend: async (workspace: Workspace) => {
        if (MOCK_IDS.includes(workspace.id)) return;
        try {
          await updateWorkspaceOnBackend(workspace.id, {
            name: workspace.name,
            description: workspace.description,
            icon: workspace.icon,
            connections: workspace.connections as unknown as Record<string, unknown>[],
            connection_ids: workspace.connectionIds,
            scope_customers: workspace.scopeCustomers,
          });
        } catch {
          // Update failed (maybe workspace doesn't exist on backend yet) — try create
          try {
            const doc = await createWorkspaceOnBackend({
              name: workspace.name,
              description: workspace.description,
              icon: workspace.icon,
              connections: workspace.connections as unknown as Record<string, unknown>[],
              connection_ids: workspace.connectionIds,
              scope_customers: workspace.scopeCustomers,
            } as Parameters<typeof createWorkspaceOnBackend>[0]);
            // If backend assigned a different ID, update local store
            if (doc.id && doc.id !== workspace.id) {
              set((state) => ({
                workspaces: state.workspaces.map((ws) =>
                  ws.id === workspace.id ? { ...ws, id: doc.id as string } : ws
                ),
                activeWorkspaceId: state.activeWorkspaceId === workspace.id
                  ? (doc.id as string)
                  : state.activeWorkspaceId,
              }));
            }
          } catch {
            // Both update and create failed — nothing we can do
          }
        }
      },
    }),
    {
      name: 'datalens-workspaces',
      partialize: (state) => ({
        workspaces: state.workspaces,
        activeWorkspaceId: state.activeWorkspaceId,
      }),
      merge: (persisted, current) => {
        const persistedState = persisted as Partial<WorkspaceState>;
        const persistedWorkspaces = (persistedState.workspaces || []).map((w) => ({
          ...w,
          connections: w.connections || [],
          scopeCustomers: w.scopeCustomers || [],
        }));
        const userCreated = persistedWorkspaces.filter((w) => !MOCK_IDS.includes(w.id));
        return {
          ...current,
          workspaces: [...MOCK_WORKSPACES, ...userCreated],
          activeWorkspaceId: persistedState.activeWorkspaceId ?? current.activeWorkspaceId,
        };
      },
    }
  )
);
