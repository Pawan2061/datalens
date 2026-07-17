import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlarmClock,
  CheckCircle2,
  Loader2,
  Mail,
  Play,
  Plus,
  RefreshCw,
  Trash2,
  XCircle,
} from 'lucide-react';
import { useWorkspaceStore } from '../store/workspaceStore';
import {
  createScheduledPrompt,
  deleteScheduledPrompt,
  fetchScheduledPromptExecutions,
  fetchScheduledPrompts,
  runScheduledPromptsNow,
  updateScheduledPrompt,
  type ScheduledPrompt,
  type ScheduledPromptExecution,
} from '../services/api';

const DAYS = [
  { value: 'mon', label: 'Mon' },
  { value: 'tue', label: 'Tue' },
  { value: 'wed', label: 'Wed' },
  { value: 'thu', label: 'Thu' },
  { value: 'fri', label: 'Fri' },
  { value: 'sat', label: 'Sat' },
  { value: 'sun', label: 'Sun' },
];

const DEFAULT_PROMPT = 'Send me the sales activity of today on pandeypawan2061@gmail.com';

function formatDate(value: string): string {
  if (!value) return 'Not scheduled';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function splitEmails(value: string): string[] {
  return value
    .split(',')
    .map((email) => email.trim())
    .filter(Boolean);
}

export default function ScheduledPromptsPage() {
  const navigate = useNavigate();
  const workspaces = useWorkspaceStore((s) => s.workspaces);
  const loadWorkspacesFromBackend = useWorkspaceStore((s) => s.loadWorkspacesFromBackend);
  const [items, setItems] = useState<ScheduledPrompt[]>([]);
  const [selectedId, setSelectedId] = useState<string>('');
  const [executions, setExecutions] = useState<ScheduledPromptExecution[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const [name, setName] = useState('Daily sales activity');
  const [workspaceId, setWorkspaceId] = useState('');
  const [connectionId, setConnectionId] = useState('');
  const [promptText, setPromptText] = useState(DEFAULT_PROMPT);
  const [time, setTime] = useState('22:00');
  const [timezone, setTimezone] = useState('Asia/Kolkata');
  const [mode, setMode] = useState<'quick' | 'deep'>('quick');
  const [emailRecipients, setEmailRecipients] = useState('');
  const [emailSubject, setEmailSubject] = useState('');
  const [days, setDays] = useState<string[]>(DAYS.map((d) => d.value));

  const selectedWorkspace = useMemo(
    () => workspaces.find((workspace) => workspace.id === workspaceId),
    [workspaceId, workspaces],
  );
  const selectedPrompt = useMemo(
    () => items.find((item) => item.id === selectedId),
    [items, selectedId],
  );

  const load = async () => {
    setError('');
    setLoading(true);
    try {
      await loadWorkspacesFromBackend();
      const prompts = await fetchScheduledPrompts();
      setItems(prompts);
      setSelectedId((current) => current || prompts[0]?.id || '');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load scheduled prompts');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (!workspaceId && workspaces[0]) {
      setWorkspaceId(workspaces[0].id);
      setConnectionId(workspaces[0].connections[0]?.id || workspaces[0].connectionIds[0] || '');
    }
  }, [workspaceId, workspaces]);

  useEffect(() => {
    if (!selectedId) {
      setExecutions([]);
      return;
    }
    fetchScheduledPromptExecutions(selectedId)
      .then(setExecutions)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load executions'));
  }, [selectedId]);

  const submit = async () => {
    setError('');
    setNotice('');
    if (!workspaceId || !connectionId) {
      setError('Select a workspace and connection before creating a schedule.');
      return;
    }
    setSaving(true);
    try {
      const created = await createScheduledPrompt({
        name,
        prompt_text: promptText,
        workspace_id: workspaceId,
        connection_id: connectionId,
        analysis_mode: mode,
        email_recipients: splitEmails(emailRecipients),
        email_subject: emailSubject,
        schedule_time: time,
        schedule_timezone: timezone,
        schedule_days: days,
      });
      setItems((current) => [created, ...current]);
      setSelectedId(created.id);
      setNotice('Schedule created.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create schedule');
    } finally {
      setSaving(false);
    }
  };

  const toggleActive = async (prompt: ScheduledPrompt) => {
    setError('');
    try {
      const updated = await updateScheduledPrompt(prompt.id, { is_active: !prompt.is_active });
      setItems((current) => current.map((item) => (item.id === prompt.id ? updated : item)));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update schedule');
    }
  };

  const remove = async (prompt: ScheduledPrompt) => {
    setError('');
    try {
      await deleteScheduledPrompt(prompt.id);
      setItems((current) => current.filter((item) => item.id !== prompt.id));
      if (selectedId === prompt.id) setSelectedId('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete schedule');
    }
  };

  const runDueNow = async () => {
    setError('');
    setNotice('');
    setRunning(true);
    try {
      const result = await runScheduledPromptsNow();
      setNotice(result.skipped ? `Skipped: ${result.reason}` : `Executed ${result.executed} due schedule(s).`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to run schedules');
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="sched-page">
      <header className="sched-header">
        <div>
          <button className="sched-link-btn" onClick={() => navigate('/admin')}>Back to admin</button>
          <h1>Scheduled Prompts</h1>
        </div>
        <div className="sched-header-actions">
          <button className="adm-btn adm-btn--secondary" onClick={load} disabled={loading}>
            <RefreshCw size={15} /> Refresh
          </button>
          <button className="adm-btn adm-btn--primary" onClick={runDueNow} disabled={running}>
            {running ? <Loader2 size={15} className="ts-spinner" /> : <Play size={15} />} Run due
          </button>
        </div>
      </header>

      {error && <div className="sched-alert sched-alert--error">{error}</div>}
      {notice && <div className="sched-alert sched-alert--success">{notice}</div>}

      <main className="sched-grid">
        <section className="sched-panel">
          <div className="sched-panel-title">
            <Plus size={18} />
            <span>Create schedule</span>
          </div>
          <div className="sched-form">
            <label>
              Name
              <input value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label>
              Workspace
              <select
                value={workspaceId}
                onChange={(e) => {
                  const nextWorkspace = workspaces.find((workspace) => workspace.id === e.target.value);
                  setWorkspaceId(e.target.value);
                  setConnectionId(nextWorkspace?.connections[0]?.id || nextWorkspace?.connectionIds[0] || '');
                }}
              >
                {workspaces.map((workspace) => (
                  <option key={workspace.id} value={workspace.id}>{workspace.name}</option>
                ))}
              </select>
            </label>
            <label>
              Connection
              <select value={connectionId} onChange={(e) => setConnectionId(e.target.value)}>
                {(selectedWorkspace?.connections || []).map((connection) => (
                  <option key={connection.id} value={connection.id}>{connection.name || connection.id}</option>
                ))}
              </select>
            </label>
            <label>
              Prompt
              <textarea value={promptText} onChange={(e) => setPromptText(e.target.value)} rows={6} />
            </label>
            <div className="sched-two">
              <label>
                Time
                <input type="time" value={time} onChange={(e) => setTime(e.target.value)} />
              </label>
              <label>
                Timezone
                <input value={timezone} onChange={(e) => setTimezone(e.target.value)} />
              </label>
            </div>
            <div className="sched-two">
              <label>
                Mode
                <select value={mode} onChange={(e) => setMode(e.target.value as 'quick' | 'deep')}>
                  <option value="quick">Quick</option>
                  <option value="deep">Deep</option>
                </select>
              </label>
              <label>
                Subject
                <input value={emailSubject} onChange={(e) => setEmailSubject(e.target.value)} placeholder="Optional" />
              </label>
            </div>
            <label>
              Fallback recipients
              <input value={emailRecipients} onChange={(e) => setEmailRecipients(e.target.value)} placeholder="name@example.com, team@example.com" />
            </label>
            <div className="sched-day-row">
              {DAYS.map((day) => (
                <button
                  key={day.value}
                  type="button"
                  className={days.includes(day.value) ? 'sched-day sched-day--active' : 'sched-day'}
                  onClick={() => {
                    setDays((current) => (
                      current.includes(day.value)
                        ? current.filter((item) => item !== day.value)
                        : [...current, day.value]
                    ));
                  }}
                >
                  {day.label}
                </button>
              ))}
            </div>
            <button className="adm-btn adm-btn--primary sched-submit" onClick={submit} disabled={saving || loading}>
              {saving ? <Loader2 size={15} className="ts-spinner" /> : <AlarmClock size={15} />} Schedule prompt
            </button>
          </div>
        </section>

        <section className="sched-panel sched-panel--list">
          <div className="sched-panel-title">
            <AlarmClock size={18} />
            <span>Schedules</span>
          </div>
          {loading ? (
            <div className="sched-empty"><Loader2 className="ts-spinner" size={18} /> Loading schedules...</div>
          ) : items.length === 0 ? (
            <div className="sched-empty">No scheduled prompts yet.</div>
          ) : (
            <div className="sched-list">
              {items.map((item) => (
                <article
                  key={item.id}
                  className={selectedId === item.id ? 'sched-card sched-card--active' : 'sched-card'}
                  onClick={() => setSelectedId(item.id)}
                >
                  <div className="sched-card-main">
                    <div>
                      <h3>{item.name}</h3>
                      <p>{item.prompt_text}</p>
                    </div>
                    <span className={item.is_active ? 'sched-status sched-status--active' : 'sched-status'}>
                      {item.is_active ? 'Active' : 'Paused'}
                    </span>
                  </div>
                  <div className="sched-meta">
                    <span><AlarmClock size={14} /> {item.schedule_time} {item.schedule_timezone}</span>
                    <span><Mail size={14} /> Next: {formatDate(item.next_execution_at)}</span>
                  </div>
                  <div className="sched-card-actions">
                    <button onClick={(event) => { event.stopPropagation(); void toggleActive(item); }}>
                      {item.is_active ? 'Pause' : 'Resume'}
                    </button>
                    <button onClick={(event) => { event.stopPropagation(); void remove(item); }}>
                      <Trash2 size={14} /> Delete
                    </button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>

        <section className="sched-panel sched-panel--executions">
          <div className="sched-panel-title">
            <CheckCircle2 size={18} />
            <span>Recent executions</span>
          </div>
          {!selectedPrompt ? (
            <div className="sched-empty">Select a schedule to inspect runs.</div>
          ) : executions.length === 0 ? (
            <div className="sched-empty">No execution history for this schedule.</div>
          ) : (
            <div className="sched-exec-list">
              {executions.map((execution) => (
                <div key={execution.id} className="sched-exec">
                  <div className="sched-exec-head">
                    <span className={execution.status === 'success' ? 'sched-run-ok' : 'sched-run-fail'}>
                      {execution.status === 'success' ? <CheckCircle2 size={15} /> : <XCircle size={15} />}
                      {execution.status}
                    </span>
                    <span>{formatDate(execution.created_at)}</span>
                  </div>
                  <p>{execution.error_message || execution.email_error || execution.response || 'Completed'}</p>
                  <span className="sched-exec-foot">{Math.round(execution.execution_time_ms)} ms</span>
                </div>
              ))}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
