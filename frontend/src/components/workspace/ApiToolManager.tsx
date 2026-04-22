import { useState, useEffect } from 'react';
import {
  Plus, Trash2, Save, X, ChevronDown, ChevronRight,
  Plug, Play, Loader2, Check, AlertCircle, ToggleLeft, ToggleRight, Pencil,
} from 'lucide-react';
import {
  listApiTools, addApiTool, updateApiTool, deleteApiTool, testApiTool,
  type ApiToolConfig, type ApiToolParam,
} from '../../services/api';

interface ApiToolManagerProps {
  workspaceId: string;
  onClose: () => void;
}

const EMPTY_PARAM: ApiToolParam = {
  name: '', type: 'string', required: true, description: '', default_value: '',
};

function emptyTool(): Partial<ApiToolConfig> {
  return {
    name: '', tool_name: '', description: '', endpoint_url: '', req_code: '',
    method: 'POST', auth_config: { apikey: '', token: '' },
    input_parameters: [], response_path: '', response_fields: [],
    enabled: true, timeout_seconds: 30,
    auth_mode: 'static',
    token_endpoint: '', token_response_path: 'AUTH_TOKEN',
    token_param_name: 'TOKEN', token_ttl_seconds: 1800,
    success_field: 'RESULT_CODE', success_value: 'PASS',
    retry_on_auth_failure: true,
  };
}

export default function ApiToolManager({ workspaceId, onClose }: ApiToolManagerProps) {
  const [tools, setTools] = useState<ApiToolConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [editTool, setEditTool] = useState<Partial<ApiToolConfig> | null>(null);
  const [editId, setEditId] = useState<string | null>(null); // null = adding new
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ id: string; data: unknown; error?: string } | null>(null);
  const [testParams, setTestParams] = useState<Record<string, string>>({});
  const [expandedTool, setExpandedTool] = useState<string | null>(null);
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' } | null>(null);

  const showToast = (msg: string, type: 'success' | 'error' = 'success') => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 3000);
  };

  useEffect(() => {
    loadTools();
  }, [workspaceId]);

  const loadTools = async () => {
    setLoading(true);
    try {
      const list = await listApiTools(workspaceId);
      setTools(list);
    } catch {
      showToast('Failed to load API tools', 'error');
    }
    setLoading(false);
  };

  const startAdd = () => {
    setEditTool(emptyTool());
    setEditId(null);
  };

  const startEdit = (tool: ApiToolConfig) => {
    setEditTool({ ...tool });
    setEditId(tool.id);
  };

  const cancelEdit = () => {
    setEditTool(null);
    setEditId(null);
  };

  const saveTool = async () => {
    if (!editTool || !editTool.name || !editTool.endpoint_url) {
      showToast('Name and Endpoint URL are required', 'error');
      return;
    }
    setSaving(true);
    try {
      if (editId) {
        await updateApiTool(workspaceId, editId, editTool);
        showToast('API tool updated');
      } else {
        await addApiTool(workspaceId, editTool);
        showToast('API tool added');
      }
      setEditTool(null);
      setEditId(null);
      await loadTools();
    } catch (e: any) {
      showToast(e.message || 'Failed to save', 'error');
    }
    setSaving(false);
  };

  const removeTool = async (id: string) => {
    try {
      await deleteApiTool(workspaceId, id);
      showToast('API tool deleted');
      await loadTools();
    } catch {
      showToast('Failed to delete', 'error');
    }
  };

  const runTest = async (tool: ApiToolConfig) => {
    setTesting(tool.id);
    setTestResult(null);
    try {
      const res = await testApiTool(workspaceId, tool.id, testParams);
      setTestResult({ id: tool.id, data: res });
      showToast(`Test passed (${res.duration_ms}ms)`);
      await loadTools(); // Refresh test_status
    } catch (e: any) {
      setTestResult({ id: tool.id, data: null, error: e.message });
      showToast('Test failed', 'error');
      await loadTools();
    }
    setTesting(null);
  };

  const updateParam = (idx: number, field: keyof ApiToolParam, value: string | boolean) => {
    if (!editTool) return;
    const params = [...(editTool.input_parameters || [])];
    params[idx] = { ...params[idx], [field]: value };
    setEditTool({ ...editTool, input_parameters: params });
  };

  const addParam = () => {
    if (!editTool) return;
    setEditTool({
      ...editTool,
      input_parameters: [...(editTool.input_parameters || []), { ...EMPTY_PARAM }],
    });
  };

  const removeParam = (idx: number) => {
    if (!editTool) return;
    const params = [...(editTool.input_parameters || [])];
    params.splice(idx, 1);
    setEditTool({ ...editTool, input_parameters: params });
  };

  // ── Render ──────────────────────────────────────────────────────
  return (
    <div className="atm-overlay" onClick={onClose}>
      <div className="atm-panel" onClick={(e) => e.stopPropagation()}>
        <div className="atm-header">
          <div className="atm-header-left">
            <Plug size={18} />
            <h2>External API Tools</h2>
          </div>
          <button className="atm-close" onClick={onClose}><X size={18} /></button>
        </div>

        <p className="atm-desc">
          Configure external APIs as tools. The AI agent will decide when to call them based on the user's question.
        </p>

        {loading ? (
          <div className="atm-loading"><Loader2 size={20} className="ts-spinner" /> Loading...</div>
        ) : (
          <>
            {/* Tool list */}
            <div className="atm-list">
              {tools.length === 0 && !editTool && (
                <div className="atm-empty">No API tools configured yet.</div>
              )}
              {tools.map((tool) => {
                const isExpanded = expandedTool === tool.id;
                return (
                  <div key={tool.id} className="atm-card">
                    <div
                      className="atm-card-header"
                      onClick={() => setExpandedTool(isExpanded ? null : tool.id)}
                    >
                      {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                      <span className="atm-card-name">{tool.name}</span>
                      <span className={`atm-status-badge atm-status-badge--${tool.test_status}`}>
                        {tool.test_status === 'success' ? <Check size={10} /> : tool.test_status === 'failed' ? <AlertCircle size={10} /> : null}
                        {tool.test_status}
                      </span>
                      {tool.enabled ? (
                        <span className="atm-enabled-badge">Active</span>
                      ) : (
                        <span className="atm-disabled-badge">Disabled</span>
                      )}
                    </div>
                    {isExpanded && (
                      <div className="atm-card-body">
                        <div className="atm-detail"><strong>Description:</strong> {tool.description}</div>
                        <div className="atm-detail"><strong>Endpoint:</strong> <code>{tool.endpoint_url}</code></div>
                        {tool.req_code && <div className="atm-detail"><strong>reqCode:</strong> <code>{tool.req_code}</code></div>}
                        <div className="atm-detail"><strong>Method:</strong> {tool.method}</div>
                        <div className="atm-detail"><strong>Response path:</strong> <code>{tool.response_path || '(root)'}</code></div>
                        {tool.input_parameters.length > 0 && (
                          <div className="atm-detail">
                            <strong>Input Parameters:</strong>
                            <div className="atm-params-list">
                              {tool.input_parameters.map((p, i) => (
                                <div key={i} className="atm-param-row">
                                  <code>{p.name}</code>
                                  <span className={`atm-param-badge ${p.required ? 'atm-param-badge--req' : ''}`}>
                                    {p.required ? 'required' : 'optional'}
                                  </span>
                                  <span>{p.description}</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        {/* Test section */}
                        <div className="atm-test-section">
                          <strong>Test API:</strong>
                          {tool.input_parameters.filter(p => p.required).map((p) => (
                            <div key={p.name} className="atm-test-input">
                              <label>{p.name}:</label>
                              <input
                                type="text"
                                placeholder={p.description || p.name}
                                value={testParams[p.name] || ''}
                                onChange={(e) => setTestParams({ ...testParams, [p.name]: e.target.value })}
                              />
                            </div>
                          ))}
                          <button
                            className="atm-btn atm-btn--test"
                            onClick={() => runTest(tool)}
                            disabled={testing === tool.id}
                          >
                            {testing === tool.id ? <Loader2 size={12} className="ts-spinner" /> : <Play size={12} />}
                            {testing === tool.id ? 'Testing...' : 'Run Test'}
                          </button>
                          {testResult && testResult.id === tool.id && (
                            <div className={`atm-test-result ${testResult.error ? 'atm-test-result--error' : 'atm-test-result--ok'}`}>
                              {testResult.error ? (
                                <span>Error: {testResult.error}</span>
                              ) : (
                                <pre>{JSON.stringify(testResult.data, null, 2).slice(0, 500)}</pre>
                              )}
                            </div>
                          )}
                        </div>

                        <div className="atm-card-actions">
                          <button className="atm-btn atm-btn--edit" onClick={() => startEdit(tool)}>
                            <Pencil size={12} /> Edit
                          </button>
                          <button className="atm-btn atm-btn--delete" onClick={() => removeTool(tool.id)}>
                            <Trash2 size={12} /> Delete
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Add button */}
            {!editTool && (
              <button className="atm-add-btn" onClick={startAdd}>
                <Plus size={14} /> Add API Tool
              </button>
            )}

            {/* Edit/Add form */}
            {editTool && (
              <div className="atm-form">
                <h3>{editId ? 'Edit API Tool' : 'Add API Tool'}</h3>

                <div className="atm-form-row">
                  <label>Name *</label>
                  <input
                    value={editTool.name || ''}
                    onChange={(e) => setEditTool({ ...editTool, name: e.target.value })}
                    placeholder="e.g. SKU Stock Info"
                  />
                </div>

                <div className="atm-form-row">
                  <label>Description *</label>
                  <textarea
                    value={editTool.description || ''}
                    onChange={(e) => setEditTool({ ...editTool, description: e.target.value })}
                    placeholder="What does this API do? The AI reads this to decide when to use it."
                    rows={2}
                  />
                </div>

                <div className="atm-form-row">
                  <label>Endpoint URL *</label>
                  <input
                    value={editTool.endpoint_url || ''}
                    onChange={(e) => setEditTool({ ...editTool, endpoint_url: e.target.value })}
                    placeholder="https://app.example.com/ediApiAction.do"
                  />
                </div>

                <div className="atm-form-grid">
                  <div className="atm-form-row">
                    <label>reqCode</label>
                    <input
                      value={editTool.req_code || ''}
                      onChange={(e) => setEditTool({ ...editTool, req_code: e.target.value })}
                      placeholder="e.g. getSKUWiseStockInfo"
                    />
                  </div>
                  <div className="atm-form-row">
                    <label>Method</label>
                    <select
                      value={editTool.method || 'POST'}
                      onChange={(e) => setEditTool({ ...editTool, method: e.target.value })}
                    >
                      <option value="POST">POST</option>
                      <option value="GET">GET</option>
                    </select>
                  </div>
                </div>

                <div className="atm-form-grid">
                  <div className="atm-form-row">
                    <label>API Key</label>
                    <input
                      type="password"
                      value={editTool.auth_config?.apikey || ''}
                      onChange={(e) => setEditTool({
                        ...editTool,
                        auth_config: { ...(editTool.auth_config || {}), apikey: e.target.value },
                      })}
                      placeholder="APIKEY value"
                    />
                  </div>
                  <div className="atm-form-row">
                    <label>Token (static mode only)</label>
                    <input
                      type="password"
                      value={editTool.auth_config?.token || ''}
                      onChange={(e) => setEditTool({
                        ...editTool,
                        auth_config: { ...(editTool.auth_config || {}), token: e.target.value },
                      })}
                      placeholder="TOKEN value"
                      disabled={editTool.auth_mode === 'two_step_token'}
                    />
                  </div>
                </div>

                <div className="atm-form-row">
                  <label>Auth Mode</label>
                  <select
                    value={editTool.auth_mode || 'static'}
                    onChange={(e) => setEditTool({
                      ...editTool,
                      auth_mode: e.target.value as 'static' | 'two_step_token',
                    })}
                  >
                    <option value="static">Static (API key / token in request)</option>
                    <option value="two_step_token">Two-step token (fetch token, then call)</option>
                  </select>
                </div>

                {editTool.auth_mode === 'two_step_token' && (
                  <div className="atm-form-section">
                    <label style={{ fontWeight: 600 }}>Two-step token settings</label>

                    <div className="atm-form-row">
                      <label>Token Endpoint *</label>
                      <input
                        value={editTool.token_endpoint || ''}
                        onChange={(e) => setEditTool({ ...editTool, token_endpoint: e.target.value })}
                        placeholder="https://app.example.com/ediApiAction.do?reqCode=getAuthToken&APIKEY=..."
                      />
                    </div>

                    <div className="atm-form-grid">
                      <div className="atm-form-row">
                        <label>Token Response Path</label>
                        <input
                          value={editTool.token_response_path || ''}
                          onChange={(e) => setEditTool({ ...editTool, token_response_path: e.target.value })}
                          placeholder="AUTH_TOKEN"
                        />
                      </div>
                      <div className="atm-form-row">
                        <label>Token Param Name</label>
                        <input
                          value={editTool.token_param_name || ''}
                          onChange={(e) => setEditTool({ ...editTool, token_param_name: e.target.value })}
                          placeholder="TOKEN"
                        />
                      </div>
                    </div>

                    <div className="atm-form-grid">
                      <div className="atm-form-row">
                        <label>Token TTL (seconds)</label>
                        <input
                          type="number"
                          value={editTool.token_ttl_seconds ?? 1800}
                          onChange={(e) => setEditTool({
                            ...editTool,
                            token_ttl_seconds: Number(e.target.value) || 1800,
                          })}
                          min={60}
                        />
                      </div>
                      <div className="atm-form-row">
                        <label className="atm-toggle-label">
                          <input
                            type="checkbox"
                            checked={editTool.retry_on_auth_failure ?? true}
                            onChange={(e) => setEditTool({
                              ...editTool,
                              retry_on_auth_failure: e.target.checked,
                            })}
                          />
                          Retry once on auth failure
                        </label>
                      </div>
                    </div>

                    <div className="atm-form-grid">
                      <div className="atm-form-row">
                        <label>Success Field</label>
                        <input
                          value={editTool.success_field || ''}
                          onChange={(e) => setEditTool({ ...editTool, success_field: e.target.value })}
                          placeholder="RESULT_CODE"
                        />
                      </div>
                      <div className="atm-form-row">
                        <label>Success Value</label>
                        <input
                          value={editTool.success_value || ''}
                          onChange={(e) => setEditTool({ ...editTool, success_value: e.target.value })}
                          placeholder="PASS"
                        />
                      </div>
                    </div>
                  </div>
                )}

                <div className="atm-form-row">
                  <label>Response Data Path</label>
                  <input
                    value={editTool.response_path || ''}
                    onChange={(e) => setEditTool({ ...editTool, response_path: e.target.value })}
                    placeholder="e.g. PIECE_DETAILS or STOCK_DETAILS.STOCK_ARRAY"
                  />
                </div>

                <div className="atm-form-row">
                  <label>Response Fields (comma-separated)</label>
                  <input
                    value={(editTool.response_fields || []).join(', ')}
                    onChange={(e) => setEditTool({
                      ...editTool,
                      response_fields: e.target.value.split(',').map(s => s.trim()).filter(Boolean),
                    })}
                    placeholder="e.g. PIECE_NO, PIECE_VALUE, WAREHOUSE_NAME"
                  />
                </div>

                {/* Input Parameters */}
                <div className="atm-form-section">
                  <label>Input Parameters (what the AI must provide)</label>
                  {(editTool.input_parameters || []).map((p, i) => (
                    <div key={i} className="atm-param-edit-row">
                      <input
                        placeholder="Name (e.g. ITEM_ID)"
                        value={p.name}
                        onChange={(e) => updateParam(i, 'name', e.target.value)}
                      />
                      <input
                        placeholder="Description"
                        value={p.description}
                        onChange={(e) => updateParam(i, 'description', e.target.value)}
                        style={{ flex: 2 }}
                      />
                      <input
                        placeholder="Default"
                        value={p.default_value}
                        onChange={(e) => updateParam(i, 'default_value', e.target.value)}
                        style={{ flex: 1 }}
                        title="Injected when the LLM omits this parameter. Leave blank to require LLM to provide."
                      />
                      <label className="atm-param-req-label">
                        <input
                          type="checkbox"
                          checked={p.required}
                          onChange={(e) => updateParam(i, 'required', e.target.checked)}
                        />
                        Req
                      </label>
                      <button className="atm-param-del" onClick={() => removeParam(i)}>
                        <X size={12} />
                      </button>
                    </div>
                  ))}
                  <button className="atm-param-add" onClick={addParam}>
                    <Plus size={12} /> Add Parameter
                  </button>
                </div>

                <div className="atm-form-row">
                  <label className="atm-toggle-label">
                    {editTool.enabled ? <ToggleRight size={18} color="#22c55e" /> : <ToggleLeft size={18} color="#94a3b8" />}
                    <span onClick={() => setEditTool({ ...editTool, enabled: !editTool.enabled })}>
                      {editTool.enabled ? 'Enabled' : 'Disabled'}
                    </span>
                  </label>
                </div>

                <div className="atm-form-actions">
                  <button className="atm-btn atm-btn--cancel" onClick={cancelEdit}>Cancel</button>
                  <button className="atm-btn atm-btn--save" onClick={saveTool} disabled={saving}>
                    {saving ? <Loader2 size={12} className="ts-spinner" /> : <Save size={12} />}
                    {saving ? 'Saving...' : 'Save'}
                  </button>
                </div>
              </div>
            )}
          </>
        )}

        {toast && (
          <div className={`atm-toast atm-toast--${toast.type}`}>{toast.msg}</div>
        )}
      </div>
    </div>
  );
}
