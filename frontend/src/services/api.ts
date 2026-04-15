import type { ConnectionConfig, ConnectionInfo, ConnectorType, SchemaInfo } from '../types/connection';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

function getAuthHeaders(): Record<string, string> {
  try {
    const stored = localStorage.getItem('datalens-auth');
    if (stored) {
      const parsed = JSON.parse(stored);
      const token = parsed?.state?.token;
      if (token) return { Authorization: `Bearer ${token}` };
    }
  } catch { /* ignore */ }
  return {};
}

export interface HistoryMessage {
  role: 'user' | 'assistant';
  content: string;
}

export async function sendMessage(
  sessionId: string | null,
  message: string,
  connectionId: string,
  analysisMode: 'quick' | 'deep' = 'quick',
  workspaceId: string = '',
  history: HistoryMessage[] = []
): Promise<{ session_id: string; status: string }> {
  const response = await fetch(`${API_BASE}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      message,
      connection_id: connectionId,
      analysis_mode: analysisMode,
      workspace_id: workspaceId,
      history,
      user_id: (() => { try { const a = JSON.parse(localStorage.getItem('datalens-auth') || '{}'); return a?.state?.user?.id || ''; } catch { return ''; } })(),
    }),
  });
  if (!response.ok) {
    let errorMsg = `Request failed (${response.status})`;
    try {
      const errorBody = await response.json();
      if (errorBody.detail) {
        errorMsg = errorBody.detail;
      }
    } catch {
      const text = await response.text().catch(() => '');
      if (text) errorMsg = text;
    }
    throw new Error(errorMsg);
  }
  return response.json();
}

export function createEventSource(sessionId: string): EventSource {
  return new EventSource(`${API_BASE}/api/chat/stream/${sessionId}`);
}

/**
 * Re-run a user question through the backend pipeline and return fresh InsightResult.
 * Uses a temporary session so chat history is not polluted.
 */
export function refreshQuery(
  question: string,
  connectionId: string,
  mode: 'quick' | 'deep' = 'quick'
): Promise<import('../types/chat').InsightResult> {
  return new Promise(async (resolve, reject) => {
    const tempSessionId = `__refresh_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    let settled = false;

    const timeout = setTimeout(() => {
      if (!settled) {
        settled = true;
        reject(new Error('Refresh timed out'));
      }
    }, 120000);

    try {
      await sendMessage(tempSessionId, question, connectionId, mode);
      const es = createEventSource(tempSessionId);

      es.addEventListener('final_result', (event: MessageEvent) => {
        if (settled) return;
        try {
          const result = JSON.parse(event.data);
          settled = true;
          clearTimeout(timeout);
          resolve(result);
        } catch {
          settled = true;
          clearTimeout(timeout);
          reject(new Error('Failed to parse refresh result'));
        }
      });

      es.addEventListener('done', () => {
        es.close();
        if (!settled) {
          settled = true;
          clearTimeout(timeout);
          reject(new Error('Stream ended without result'));
        }
      });

      es.onerror = () => {
        es.close();
        if (!settled) {
          settled = true;
          clearTimeout(timeout);
          reject(new Error('Connection lost during refresh'));
        }
      };
    } catch (err) {
      if (!settled) {
        settled = true;
        clearTimeout(timeout);
        reject(err);
      }
    }
  });
}

export async function addConnection(config: ConnectionConfig): Promise<ConnectionInfo> {
  // For file uploads, use FormData
  if (config.connectorType === 'file' && config.fileSource.file) {
    const formData = new FormData();
    formData.append('file', config.fileSource.file);
    formData.append('name', config.name);
    formData.append('connectorType', 'file');
    formData.append('fileFormat', config.fileSource.fileFormat);

    const response = await fetch(`${API_BASE}/api/connections/upload`, {
      method: 'POST',
      body: formData,
    });
    if (!response.ok) {
      const errorBody = await response.text();
      throw new Error(`Upload failed: ${response.status} ${errorBody}`);
    }
    return response.json();
  }

  // For database connectors, send JSON
  const response = await fetch(`${API_BASE}/api/connections`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
  if (!response.ok) {
    const errorBody = await response.text();
    throw new Error(`Failed to add connection: ${response.status} ${errorBody}`);
  }
  return response.json();
}

export async function listConnections(): Promise<ConnectionInfo[]> {
  const response = await fetch(`${API_BASE}/api/connections`, {
    method: 'GET',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!response.ok) {
    const errorBody = await response.text();
    throw new Error(`Failed to list connections: ${response.status} ${errorBody}`);
  }
  return response.json();
}

export async function testConnection(id: string): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE}/api/connections/${id}/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!response.ok) {
    const errorBody = await response.text();
    throw new Error(`Failed to test connection: ${response.status} ${errorBody}`);
  }
  return response.json();
}

export async function deleteConnection(id: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/connections/${id}`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
  });
  if (!response.ok) {
    const errorBody = await response.text();
    throw new Error(`Failed to delete connection: ${response.status} ${errorBody}`);
  }
}

export async function getConnectionSchema(connectionId: string): Promise<SchemaInfo> {
  const response = await fetch(`${API_BASE}/api/connections/${connectionId}/schema`);
  if (!response.ok) {
    const errorBody = await response.text();
    throw new Error(`Failed to fetch schema: ${response.status} ${errorBody}`);
  }
  return response.json();
}

// ── Persistence API (Cosmos DB backed) ────────────────────────────────

// Workspaces
export async function fetchWorkspaces(): Promise<Record<string, unknown>[]> {
  const response = await fetch(`${API_BASE}/api/workspaces`, {
    headers: { ...getAuthHeaders() },
  });
  if (!response.ok) throw new Error('Failed to fetch workspaces');
  return response.json();
}

export async function createWorkspaceOnBackend(data: {
  name: string;
  description?: string;
  icon?: string;
  connections?: Record<string, unknown>[];
  connection_ids?: string[];
}): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE}/api/workspaces`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(data),
  });
  if (!response.ok) throw new Error('Failed to create workspace');
  return response.json();
}

export async function updateWorkspaceOnBackend(
  workspaceId: string,
  data: Record<string, unknown>
): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE}/api/workspaces/${workspaceId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(data),
  });
  if (!response.ok) throw new Error('Failed to update workspace');
  return response.json();
}

export async function deleteWorkspaceOnBackend(workspaceId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/workspaces/${workspaceId}`, {
    method: 'DELETE',
    headers: { ...getAuthHeaders() },
  });
  if (!response.ok && response.status !== 204) throw new Error('Failed to delete workspace');
}

// Sessions
export async function fetchSessionList(workspaceId: string): Promise<
  Array<{ id: string; title: string; created_at: string; updated_at: string }>
> {
  const response = await fetch(`${API_BASE}/api/workspaces/${workspaceId}/sessions`, {
    headers: { ...getAuthHeaders() },
  });
  if (!response.ok) throw new Error('Failed to fetch sessions');
  return response.json();
}

export async function fetchSession(
  sessionId: string,
  workspaceId: string
): Promise<Record<string, unknown>> {
  const response = await fetch(
    `${API_BASE}/api/sessions/${sessionId}?workspace_id=${encodeURIComponent(workspaceId)}`,
    { headers: { ...getAuthHeaders() } }
  );
  if (!response.ok) throw new Error('Failed to fetch session');
  return response.json();
}

export async function upsertSession(
  sessionId: string,
  data: { workspace_id: string; title: string; messages: Record<string, unknown>[] }
): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE}/api/sessions/${sessionId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(data),
  });
  if (!response.ok) throw new Error('Failed to upsert session');
  return response.json();
}

export async function deleteSessionOnBackend(
  sessionId: string,
  workspaceId: string
): Promise<void> {
  const response = await fetch(
    `${API_BASE}/api/sessions/${sessionId}?workspace_id=${encodeURIComponent(workspaceId)}`,
    { method: 'DELETE', headers: { ...getAuthHeaders() } }
  );
  if (!response.ok) throw new Error('Failed to delete session');
}

export async function clearAllSessionsOnBackend(workspaceId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/workspaces/${workspaceId}/sessions`, {
    method: 'DELETE',
    headers: { ...getAuthHeaders() },
  });
  if (!response.ok) throw new Error('Failed to clear sessions');
}

// Canvas
export async function fetchCanvasState(
  workspaceId: string
): Promise<{ blocks: Record<string, unknown>[]; updated_at: string | null }> {
  const response = await fetch(`${API_BASE}/api/workspaces/${workspaceId}/canvas`, {
    headers: { ...getAuthHeaders() },
  });
  if (!response.ok) throw new Error('Failed to fetch canvas');
  return response.json();
}

export async function saveCanvasState(
  workspaceId: string,
  blocks: Record<string, unknown>[]
): Promise<void> {
  const response = await fetch(`${API_BASE}/api/workspaces/${workspaceId}/canvas`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({ blocks }),
  });
  if (!response.ok) throw new Error('Failed to save canvas');
}

// ── Workspace Intelligence Profile ──────────────────────────────────

export async function generateProfile(
  workspaceId: string,
  connectionId: string
): Promise<{ status: string }> {
  const response = await fetch(
    `${API_BASE}/api/workspaces/${workspaceId}/profile/generate`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      body: JSON.stringify({ connection_id: connectionId }),
    }
  );
  if (!response.ok) throw new Error('Failed to start profile generation');
  return response.json();
}

export function createProfileEventSource(
  workspaceId: string,
  connectionId: string
): EventSource {
  return new EventSource(
    `${API_BASE}/api/workspaces/${workspaceId}/profile/stream/${connectionId}`
  );
}

export async function getProfileStatus(
  workspaceId: string,
  connectionId: string
): Promise<{ status: string; generated_at?: string; error_message?: string }> {
  const response = await fetch(
    `${API_BASE}/api/workspaces/${workspaceId}/profile?connection_id=${encodeURIComponent(connectionId)}`,
    { headers: { ...getAuthHeaders() } }
  );
  if (!response.ok) return { status: 'none' };
  return response.json();
}

export async function updateProfileQuestions(
  workspaceId: string,
  connectionId: string,
  directionalPlan: Array<{
    title: string;
    question: string;
    narrative: string;
    query_template: string;
    tables: string[];
    key_columns: string[];
  }>,
  suggestedQuestions: string[] = [],
): Promise<{ status: string; questions_count: number }> {
  const response = await fetch(
    `${API_BASE}/api/workspaces/${workspaceId}/profile/questions`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
      body: JSON.stringify({
        connection_id: connectionId,
        directional_plan: directionalPlan,
        suggested_questions: suggestedQuestions,
      }),
    }
  );
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Failed to update' }));
    throw new Error(err.detail || 'Failed to update profile questions');
  }
  return response.json();
}

export async function deleteProfile(
  workspaceId: string,
  connectionId: string
): Promise<void> {
  await fetch(
    `${API_BASE}/api/workspaces/${workspaceId}/profile?connection_id=${encodeURIComponent(connectionId)}`,
    { method: 'DELETE', headers: { ...getAuthHeaders() } }
  );
}

// ── Workspace API Tools ──────────────────────────────────────────

export interface ApiToolParam {
  name: string;
  type: string;
  required: boolean;
  description: string;
  default_value: string;
}

export interface ApiToolConfig {
  id: string;
  name: string;
  tool_name: string;
  description: string;
  endpoint_url: string;
  req_code: string;
  method: string;
  headers: Record<string, string>;
  query_params: Record<string, string>;
  body_template: string;
  auth_config: Record<string, string>;
  input_parameters: ApiToolParam[];
  response_path: string;
  response_fields: string[];
  enabled: boolean;
  test_status: string;
  timeout_seconds: number;
  created_at: string;
  created_by: string;
}

export async function listApiTools(workspaceId: string): Promise<ApiToolConfig[]> {
  const response = await fetch(`${API_BASE}/api/workspaces/${workspaceId}/api-tools`, {
    headers: { ...getAuthHeaders() },
  });
  if (!response.ok) throw new Error('Failed to list API tools');
  return response.json();
}

export async function addApiTool(
  workspaceId: string,
  tool: Partial<ApiToolConfig>
): Promise<ApiToolConfig> {
  const response = await fetch(`${API_BASE}/api/workspaces/${workspaceId}/api-tools`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(tool),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Failed' }));
    throw new Error(err.detail || 'Failed to add API tool');
  }
  return response.json();
}

export async function updateApiTool(
  workspaceId: string,
  toolId: string,
  tool: Partial<ApiToolConfig>
): Promise<ApiToolConfig> {
  const response = await fetch(`${API_BASE}/api/workspaces/${workspaceId}/api-tools/${toolId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(tool),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Failed' }));
    throw new Error(err.detail || 'Failed to update API tool');
  }
  return response.json();
}

export async function deleteApiTool(workspaceId: string, toolId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/api/workspaces/${workspaceId}/api-tools/${toolId}`, {
    method: 'DELETE',
    headers: { ...getAuthHeaders() },
  });
  if (!response.ok) throw new Error('Failed to delete API tool');
}

export async function testApiTool(
  workspaceId: string,
  toolId: string,
  testParams: Record<string, string>
): Promise<{ status: string; duration_ms: number; response: unknown }> {
  const response = await fetch(`${API_BASE}/api/workspaces/${workspaceId}/api-tools/${toolId}/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({ test_params: testParams }),
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Test failed' }));
    throw new Error(err.detail || 'API test failed');
  }
  return response.json();
}

/**
 * Returns mock schema for frontend-only development.
 * Used when backend is not available or connector type not yet supported.
 */
export function getMockSchema(_connectorType: ConnectorType): SchemaInfo {
  return {
    tables: [
      {
        name: 'customers',
        rowCount: 12480,
        columns: [
          { name: 'id', type: 'integer', isPrimaryKey: true },
          { name: 'name', type: 'varchar(100)', isPrimaryKey: false },
          { name: 'email', type: 'varchar(255)', isPrimaryKey: false },
          { name: 'segment', type: 'varchar(50)', isPrimaryKey: false },
          { name: 'region', type: 'varchar(50)', isPrimaryKey: false },
          { name: 'created_at', type: 'timestamp', isPrimaryKey: false },
        ],
      },
      {
        name: 'orders',
        rowCount: 87350,
        columns: [
          { name: 'id', type: 'integer', isPrimaryKey: true },
          { name: 'customer_id', type: 'integer', isPrimaryKey: false },
          { name: 'total', type: 'numeric(10,2)', isPrimaryKey: false },
          { name: 'status', type: 'varchar(20)', isPrimaryKey: false },
          { name: 'order_date', type: 'date', isPrimaryKey: false },
        ],
      },
      {
        name: 'products',
        rowCount: 2340,
        columns: [
          { name: 'id', type: 'integer', isPrimaryKey: true },
          { name: 'name', type: 'varchar(100)', isPrimaryKey: false },
          { name: 'category', type: 'varchar(50)', isPrimaryKey: false },
          { name: 'price', type: 'numeric(10,2)', isPrimaryKey: false },
          { name: 'stock', type: 'integer', isPrimaryKey: false },
        ],
      },
      {
        name: 'order_items',
        rowCount: 214800,
        columns: [
          { name: 'id', type: 'integer', isPrimaryKey: true },
          { name: 'order_id', type: 'integer', isPrimaryKey: false },
          { name: 'product_id', type: 'integer', isPrimaryKey: false },
          { name: 'quantity', type: 'integer', isPrimaryKey: false },
          { name: 'unit_price', type: 'numeric(10,2)', isPrimaryKey: false },
        ],
      },
      {
        name: 'revenue_monthly',
        rowCount: 48,
        columns: [
          { name: 'month', type: 'date', isPrimaryKey: true },
          { name: 'revenue', type: 'numeric(12,2)', isPrimaryKey: false },
          { name: 'expenses', type: 'numeric(12,2)', isPrimaryKey: false },
          { name: 'profit', type: 'numeric(12,2)', isPrimaryKey: false },
        ],
      },
    ],
  };
}
