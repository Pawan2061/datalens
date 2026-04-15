import { useState, useRef, useEffect } from 'react';
import {
  X, BarChart3, Users, Settings, Wallet, Database, FolderOpen,
  ArrowLeft, ArrowRight, Upload, FileText, Key, ChevronDown, ChevronRight,
  Check, Loader2, CheckCircle2, AlertCircle, Server, Globe, Layers,
  Brain, Sparkles,
} from 'lucide-react';
import type {
  ConnectionConfig, ConnectorType, SchemaInfo,
  SqlConnectionConfig, CosmosDbConnectionConfig, MongoDbConnectionConfig,
} from '../../types/connection';
import {
  addConnection, testConnection, getConnectionSchema,
  generateProfile, createProfileEventSource,
} from '../../services/api';

/* ─── Result type ─── */
export interface CreateWorkspaceResult {
  name: string;
  description: string;
  icon: string;
  connection?: {
    id: string;
    config: ConnectionConfig;
    selectedTables: string[];
    schema?: SchemaInfo;
  };
}

/* ─── Constants ─── */
type WizardStep =
  | 'workspace-info'
  | 'choose-type'
  | 'configure'
  | 'test'
  | 'schema'
  | 'select-tables'
  | 'profiling';

const WIZARD_STEPS: { key: WizardStep; label: string }[] = [
  { key: 'workspace-info', label: 'Workspace' },
  { key: 'choose-type', label: 'Source' },
  { key: 'configure', label: 'Configure' },
  { key: 'test', label: 'Test' },
  { key: 'schema', label: 'Schema' },
  { key: 'select-tables', label: 'Tables' },
  { key: 'profiling', label: 'Profiling' },
];

const WS_ICONS = [
  { id: 'bar-chart-3', icon: BarChart3, label: 'Analytics' },
  { id: 'users', icon: Users, label: 'Customers' },
  { id: 'settings', icon: Settings, label: 'Operations' },
  { id: 'wallet', icon: Wallet, label: 'Finance' },
  { id: 'database', icon: Database, label: 'Database' },
  { id: 'folder', icon: FolderOpen, label: 'General' },
];

const CONNECTOR_TYPES: { type: ConnectorType; label: string; desc: string; cssClass: string }[] = [
  { type: 'postgresql', label: 'PostgreSQL', desc: 'Relational database', cssClass: 'cd-type-icon--pg' },
  { type: 'mysql', label: 'MySQL', desc: 'Relational database', cssClass: 'cd-type-icon--mysql' },
  { type: 'sqlserver', label: 'SQL Server', desc: 'Microsoft SQL', cssClass: 'cd-type-icon--sqlserver' },
  { type: 'cosmosdb', label: 'Cosmos DB', desc: 'Azure NoSQL', cssClass: 'cd-type-icon--cosmos' },
  { type: 'mongodb', label: 'MongoDB', desc: 'Document database', cssClass: 'cd-type-icon--mongo' },
  { type: 'file', label: 'File Upload', desc: 'CSV, Excel, JSON', cssClass: 'cd-type-icon--file' },
];

const PORT_DEFAULTS: Record<string, number> = { postgresql: 5432, mysql: 3306, sqlserver: 1433 };

function getConnectorIcon(type: ConnectorType) {
  if (type === 'file') return <Upload size={22} />;
  if (type === 'cosmosdb') return <Globe size={22} />;
  if (type === 'mongodb') return <Layers size={22} />;
  return <Server size={22} />;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function detectFileFormat(fileName: string): 'csv' | 'excel' | 'json' {
  const ext = fileName.split('.').pop()?.toLowerCase();
  if (ext === 'json') return 'json';
  if (ext === 'xlsx' || ext === 'xls') return 'excel';
  return 'csv';
}

/* ─── Profiling step messages ─── */
const PROFILING_STEPS = [
  { icon: Database, text: 'Discovering schema...', color: '#3b82f6' },
  { icon: BarChart3, text: 'Sampling & profiling tables...', color: '#8b5cf6' },
  { icon: Brain, text: 'Detecting data nuances...', color: '#f59e0b' },
  { icon: Sparkles, text: 'Building directional analysis plan...', color: '#10b981' },
];

/* ─── Props ─── */
interface CreateWorkspaceDialogProps {
  isOpen: boolean;
  onClose: () => void;
  /** Creates workspace + connection. Returns the workspace ID. */
  onCreate: (data: CreateWorkspaceResult) => string | Promise<string>;
  /** Called when profiling completes (or is skipped) — parent should navigate. */
  onNavigate: (workspaceId: string) => void;
}

/* ─── Component ─── */
export default function CreateWorkspaceDialog({ isOpen, onClose, onCreate, onNavigate }: CreateWorkspaceDialogProps) {
  // Wizard step
  const [step, setStep] = useState<WizardStep>('workspace-info');

  // Step 1: Workspace info
  const [wsName, setWsName] = useState('');
  const [wsDescription, setWsDescription] = useState('');
  const [wsIcon, setWsIcon] = useState('bar-chart-3');

  // Step 2+: Connection type
  const [connectorType, setConnectorType] = useState<ConnectorType | null>(null);

  // SQL form fields
  const [connName, setConnName] = useState('');
  const [host, setHost] = useState('localhost');
  const [port, setPort] = useState(5432);
  const [database, setDatabase] = useState('');
  const [user, setUser] = useState('');
  const [password, setPassword] = useState('');
  const [ssl, setSsl] = useState(false);

  // CosmoDB
  const [endpoint, setEndpoint] = useState('');
  const [accountKey, setAccountKey] = useState('');
  const [container, setContainer] = useState('');

  // MongoDB
  const [connectionString, setConnectionString] = useState('');
  const [authSource, setAuthSource] = useState('');

  // File
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Test
  const [testStatus, setTestStatus] = useState<'idle' | 'testing' | 'success' | 'error'>('idle');
  const [testError, setTestError] = useState('');

  // Schema
  const [schema, setSchema] = useState<SchemaInfo | null>(null);
  const [expandedTable, setExpandedTable] = useState<string | null>(null);

  // Table selection
  const [selectedTables, setSelectedTables] = useState<Set<string>>(new Set());

  // Loading
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Connection ID created during test step
  const [testedConnectionId, setTestedConnectionId] = useState<string | null>(null);

  // Profiling state
  const [createdWorkspaceId, setCreatedWorkspaceId] = useState<string | null>(null);
  const [profilingStatus, setProfilingStatus] = useState<'idle' | 'running' | 'ready' | 'failed'>('idle');
  const [profilingMessage, setProfilingMessage] = useState('');
  const [profilingStepIndex, setProfilingStepIndex] = useState(0);
  const [profilingError, setProfilingError] = useState('');

  // Cleanup SSE on unmount
  const eventSourceRef = useRef<EventSource | null>(null);
  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
    };
  }, []);

  if (!isOpen) return null;

  /* ─── Reset ─── */
  const resetAll = () => {
    setStep('workspace-info');
    setWsName('');
    setWsDescription('');
    setWsIcon('bar-chart-3');
    setConnectorType(null);
    setConnName('');
    setHost('localhost');
    setPort(5432);
    setDatabase('');
    setUser('');
    setPassword('');
    setSsl(false);
    setEndpoint('');
    setAccountKey('');
    setContainer('');
    setConnectionString('');
    setAuthSource('');
    setUploadedFile(null);
    setDragActive(false);
    setTestStatus('idle');
    setTestError('');
    setSchema(null);
    setExpandedTable(null);
    setSelectedTables(new Set());
    setIsSubmitting(false);
    setTestedConnectionId(null);
    setCreatedWorkspaceId(null);
    setProfilingStatus('idle');
    setProfilingMessage('');
    setProfilingStepIndex(0);
    setProfilingError('');
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  };

  const handleClose = () => {
    resetAll();
    onClose();
  };

  /* ─── Type selection ─── */
  const handleSelectType = (type: ConnectorType) => {
    setConnectorType(type);
    if (['postgresql', 'mysql', 'sqlserver'].includes(type)) {
      setPort(PORT_DEFAULTS[type] || 5432);
    }
    setStep('configure');
  };

  /* ─── Build config ─── */
  const buildConfig = (): ConnectionConfig | null => {
    if (!connectorType) return null;

    if (connectorType === 'postgresql' || connectorType === 'mysql' || connectorType === 'sqlserver') {
      return {
        connectorType,
        name: connName || database,
        host,
        port,
        database,
        user,
        password,
        ssl,
      } as SqlConnectionConfig;
    }
    if (connectorType === 'cosmosdb') {
      return {
        connectorType: 'cosmosdb',
        name: connName || database,
        endpoint,
        accountKey,
        database,
        container: container || undefined,
      } as CosmosDbConnectionConfig;
    }
    if (connectorType === 'mongodb') {
      return {
        connectorType: 'mongodb',
        name: connName || database,
        connectionString,
        database,
        authSource: authSource || undefined,
      } as MongoDbConnectionConfig;
    }
    if (connectorType === 'file' && uploadedFile) {
      return {
        connectorType: 'file',
        name: connName || uploadedFile.name,
        fileSource: {
          fileName: uploadedFile.name,
          fileSize: uploadedFile.size,
          fileFormat: detectFileFormat(uploadedFile.name),
          file: uploadedFile,
        },
      };
    }
    return null;
  };

  const canProceedFromConfigure = (): boolean => {
    if (!connectorType) return false;
    if (['postgresql', 'mysql', 'sqlserver'].includes(connectorType)) {
      return !!database && !!user && !!password;
    }
    if (connectorType === 'cosmosdb') return !!endpoint && !!accountKey && !!database;
    if (connectorType === 'mongodb') return !!connectionString && !!database;
    if (connectorType === 'file') return !!uploadedFile;
    return false;
  };

  /* ─── Test ─── */
  const handleTest = async () => {
    setTestStatus('testing');
    setTestError('');

    try {
      // 1. Register connection with backend
      const config = buildConfig();
      if (!config) throw new Error('Invalid connection configuration');
      const rawInfo = await addConnection(config);
      setTestedConnectionId(rawInfo.id);

      // 2. Test the connection
      const testResult = await testConnection(rawInfo.id);
      if (testResult.status !== 'connected') {
        throw new Error('Database connection failed. Check your credentials and try again.');
      }

      setTestStatus('success');

      // 3. Fetch real schema
      const rawSchema = await getConnectionSchema(rawInfo.id);

      // Map backend snake_case fields to frontend camelCase
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const realSchema: SchemaInfo = {
        tables: (rawSchema.tables as any[]).map((t) => ({
          name: String(t.name ?? ''),
          rowCount: t.rowCount ?? t.row_count ?? 0,
          columns: ((t.columns ?? []) as any[]).map((c: any) => ({
            name: String(c.name ?? ''),
            type: String(c.type ?? ''),
            isPrimaryKey: Boolean(c.isPrimaryKey ?? c.is_primary_key ?? false),
          })),
        })),
      };

      setSchema(realSchema);
      setSelectedTables(new Set(realSchema.tables.map((t) => t.name)));
      setStep('schema');
    } catch (err) {
      setTestStatus('error');
      setTestError(err instanceof Error ? err.message : 'Connection failed');
    }
  };

  const handleRetryTest = () => {
    setTestStatus('idle');
    setTestError('');
    setStep('configure');
  };

  /* ─── Finish: Create workspace + start profiling ─── */
  const handleFinish = async () => {
    const config = buildConfig();
    if (!config || !testedConnectionId) return;
    setIsSubmitting(true);

    // 1. Create workspace (returns workspace ID)
    const wsId = await onCreate({
      name: wsName.trim(),
      description: wsDescription.trim(),
      icon: wsIcon,
      connection: {
        id: testedConnectionId,
        config,
        selectedTables: Array.from(selectedTables),
        schema: schema || undefined,
      },
    });

    setCreatedWorkspaceId(wsId);
    setIsSubmitting(false);

    // 2. Transition to profiling step
    setStep('profiling');
    setProfilingStatus('running');
    setProfilingStepIndex(0);
    setProfilingMessage('Starting data profiling...');

    // 3. Kick off profiling in the backend
    try {
      await generateProfile(wsId, testedConnectionId);

      // 4. Stream progress via SSE
      const es = createProfileEventSource(wsId, testedConnectionId);
      eventSourceRef.current = es;

      es.addEventListener('thinking', (event: MessageEvent) => {
        try {
          const data = JSON.parse(event.data);
          const content = data.content || '';
          setProfilingMessage(content);

          // Map step names to step indices for progress display
          if (data.step === 'discover') setProfilingStepIndex(0);
          else if (data.step === 'sampling') setProfilingStepIndex(1);
          else if (data.step === 'analyzing') {
            // Nuance detection vs plan building
            if (content.toLowerCase().includes('nuance')) setProfilingStepIndex(2);
            else setProfilingStepIndex(3);
          }
          else if (data.step === 'complete') setProfilingStepIndex(4);
        } catch { /* ignore parse errors */ }
      });

      es.addEventListener('error', (event: MessageEvent) => {
        try {
          const data = JSON.parse(event.data);
          setProfilingError(data.message || 'Profiling failed');
          setProfilingStatus('failed');
        } catch { /* ignore */ }
      });

      es.addEventListener('done', () => {
        es.close();
        eventSourceRef.current = null;
        setProfilingStatus('ready');
        setProfilingMessage('Intelligence profile ready!');
        setProfilingStepIndex(4);
      });

      es.onerror = () => {
        es.close();
        eventSourceRef.current = null;
        // If we haven't received a done event, mark as ready anyway
        // (the profile may have completed before SSE connected)
        setProfilingStatus((prev) => prev === 'running' ? 'ready' : prev);
        setProfilingMessage('Profile generation completed.');
        setProfilingStepIndex(4);
      };
    } catch (err) {
      setProfilingStatus('failed');
      setProfilingError(err instanceof Error ? err.message : 'Failed to start profiling');
    }
  };

  /* ─── Navigate to workspace (after profiling) ─── */
  const handleOpenWorkspace = () => {
    const wsId = createdWorkspaceId;
    resetAll();
    if (wsId) onNavigate(wsId);
  };

  /* ─── File handlers ─── */
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer.files?.[0];
    if (file) setUploadedFile(file);
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) setUploadedFile(file);
  };

  /* ─── Table helpers ─── */
  const toggleTable = (tableName: string) => {
    setSelectedTables((prev) => {
      const next = new Set(prev);
      if (next.has(tableName)) next.delete(tableName);
      else next.add(tableName);
      return next;
    });
  };

  const selectAllTables = () => {
    if (schema) setSelectedTables(new Set(schema.tables.map((t) => t.name)));
  };
  const deselectAllTables = () => setSelectedTables(new Set());

  /* ─── Stepper helpers ─── */
  const currentStepIndex = WIZARD_STEPS.findIndex((s) => s.key === step);

  const goBack = () => {
    if (step === 'choose-type') setStep('workspace-info');
    else if (step === 'configure') { setStep('choose-type'); setConnectorType(null); }
    else if (step === 'test') setStep('configure');
    else if (step === 'schema') setStep('test');
    else if (step === 'select-tables') setStep('schema');
    // No going back from profiling — workspace is already created
  };

  /* ─── Render ─── */
  return (
    <div className="cw-overlay">
      <div className="cw-dialog" style={{ maxWidth: 620 }}>
        {/* Header */}
        <div className="cw-header">
          <h2 className="cw-header-title">
            {step === 'workspace-info'
              ? 'Create Workspace'
              : step === 'profiling'
                ? 'Intelligence Profiling'
                : 'Connect Data Source'}
          </h2>
          {step !== 'profiling' && (
            <button onClick={handleClose} className="cw-close-btn">
              <X size={16} />
            </button>
          )}
        </div>

        {/* Stepper */}
        <div className="cd-stepper">
          {WIZARD_STEPS.map((s, i) => {
            const isActive = s.key === step;
            const isDone = currentStepIndex > i;
            return (
              <div key={s.key} style={{ display: 'flex', alignItems: 'center' }}>
                {i > 0 && <div className="cd-step-line" />}
                <div className={`cd-step ${isActive ? 'cd-step--active' : ''} ${isDone ? 'cd-step--done' : ''}`}>
                  <span className="cd-step-num">
                    {isDone ? <Check size={10} /> : i + 1}
                  </span>
                  <span>{s.label}</span>
                </div>
              </div>
            );
          })}
        </div>

        <div className="cd-body">
          {/* ─── Step 1: Workspace Info ─── */}
          {step === 'workspace-info' && (
            <div className="cw-form">
              <div>
                <label className="cw-label">Workspace Name</label>
                <input
                  type="text"
                  value={wsName}
                  onChange={(e) => setWsName(e.target.value)}
                  placeholder="e.g., Sales Analytics"
                  autoFocus
                  className="cw-input"
                />
              </div>

              <div>
                <label className="cw-label">Description</label>
                <textarea
                  value={wsDescription}
                  onChange={(e) => setWsDescription(e.target.value)}
                  placeholder="Brief description of this workspace..."
                  rows={2}
                  className="cw-textarea"
                />
              </div>

              <div>
                <label className="cw-label">Icon</label>
                <div className="cw-icon-grid">
                  {WS_ICONS.map(({ id, icon: Icon, label }) => (
                    <button
                      key={id}
                      type="button"
                      onClick={() => setWsIcon(id)}
                      title={label}
                      className={`cw-icon-btn ${wsIcon === id ? 'cw-icon-btn--selected' : ''}`}
                    >
                      <Icon size={20} />
                      <span className="cw-icon-label">{label}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* ─── Step 2: Choose Type ─── */}
          {step === 'choose-type' && (
            <>
              <p className="cd-section-label">Choose Data Source</p>
              <div className="cd-type-grid">
                {CONNECTOR_TYPES.map((ct) => (
                  <button key={ct.type} className="cd-type-card" onClick={() => handleSelectType(ct.type)}>
                    <div className={`cd-type-icon ${ct.cssClass}`}>
                      {getConnectorIcon(ct.type)}
                    </div>
                    <span className="cd-type-name">{ct.label}</span>
                    <span className="cd-type-desc">{ct.desc}</span>
                  </button>
                ))}
              </div>
            </>
          )}

          {/* ─── Step 3: Configure ─── */}
          {step === 'configure' && connectorType && (
            <>
              {/* SQL Connectors */}
              {['postgresql', 'mysql', 'sqlserver'].includes(connectorType) && (
                <div className="cd-form">
                  <div className="cd-form-row cd-form-row--2">
                    <div className="cd-field">
                      <label>Connection Name</label>
                      <input type="text" value={connName} onChange={(e) => setConnName(e.target.value)} placeholder="My Database" />
                    </div>
                    <div className="cd-field">
                      <label>Host</label>
                      <input type="text" value={host} onChange={(e) => setHost(e.target.value)} placeholder="localhost" />
                    </div>
                  </div>
                  <div className="cd-form-row cd-form-row--3">
                    <div className="cd-field">
                      <label>Port</label>
                      <input type="number" value={port} onChange={(e) => setPort(parseInt(e.target.value) || port)} />
                    </div>
                    <div className="cd-field" style={{ gridColumn: 'span 2' }}>
                      <label>Database</label>
                      <input type="text" value={database} onChange={(e) => setDatabase(e.target.value)} placeholder="mydb" />
                    </div>
                  </div>
                  <div className="cd-form-row cd-form-row--2">
                    <div className="cd-field">
                      <label>Username</label>
                      <input type="text" value={user} onChange={(e) => setUser(e.target.value)} placeholder="postgres" />
                    </div>
                    <div className="cd-field">
                      <label>Password</label>
                      <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" />
                    </div>
                  </div>
                  <div className="cd-ssl-row">
                    <span className="cd-ssl-label">Use SSL</span>
                    <button type="button" className={`cd-toggle ${ssl ? 'cd-toggle--on' : ''}`} onClick={() => setSsl(!ssl)}>
                      <span className="cd-toggle-knob" />
                    </button>
                  </div>
                </div>
              )}

              {/* Cosmos DB */}
              {connectorType === 'cosmosdb' && (
                <div className="cd-form">
                  <div className="cd-field">
                    <label>Connection Name</label>
                    <input type="text" value={connName} onChange={(e) => setConnName(e.target.value)} placeholder="My Cosmos DB" />
                  </div>
                  <div className="cd-field">
                    <label>Endpoint</label>
                    <input type="text" value={endpoint} onChange={(e) => setEndpoint(e.target.value)} placeholder="https://myaccount.documents.azure.com:443/" />
                  </div>
                  <div className="cd-field">
                    <label>Account Key</label>
                    <input type="password" value={accountKey} onChange={(e) => setAccountKey(e.target.value)} placeholder="Primary or secondary key" />
                  </div>
                  <div className="cd-form-row cd-form-row--2">
                    <div className="cd-field">
                      <label>Database</label>
                      <input type="text" value={database} onChange={(e) => setDatabase(e.target.value)} placeholder="mydb" />
                    </div>
                    <div className="cd-field">
                      <label>Container <span style={{ color: '#c4c9d2', fontWeight: 400 }}>(optional)</span></label>
                      <input type="text" value={container} onChange={(e) => setContainer(e.target.value)} placeholder="mycontainer" />
                    </div>
                  </div>
                </div>
              )}

              {/* MongoDB */}
              {connectorType === 'mongodb' && (
                <div className="cd-form">
                  <div className="cd-field">
                    <label>Connection Name</label>
                    <input type="text" value={connName} onChange={(e) => setConnName(e.target.value)} placeholder="My MongoDB" />
                  </div>
                  <div className="cd-field">
                    <label>Connection String</label>
                    <input type="text" value={connectionString} onChange={(e) => setConnectionString(e.target.value)} placeholder="mongodb+srv://user:pass@cluster.mongodb.net/" />
                  </div>
                  <div className="cd-form-row cd-form-row--2">
                    <div className="cd-field">
                      <label>Database</label>
                      <input type="text" value={database} onChange={(e) => setDatabase(e.target.value)} placeholder="mydb" />
                    </div>
                    <div className="cd-field">
                      <label>Auth Source <span style={{ color: '#c4c9d2', fontWeight: 400 }}>(optional)</span></label>
                      <input type="text" value={authSource} onChange={(e) => setAuthSource(e.target.value)} placeholder="admin" />
                    </div>
                  </div>
                </div>
              )}

              {/* File Upload */}
              {connectorType === 'file' && (
                <div className="cd-form">
                  <div className="cd-field">
                    <label>Connection Name</label>
                    <input type="text" value={connName} onChange={(e) => setConnName(e.target.value)} placeholder="My Dataset" />
                  </div>

                  {!uploadedFile ? (
                    <div
                      className={`cd-dropzone ${dragActive ? 'cd-dropzone--active' : ''}`}
                      onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
                      onDragLeave={() => setDragActive(false)}
                      onDrop={handleDrop}
                      onClick={() => fileInputRef.current?.click()}
                    >
                      <Upload size={28} />
                      <p className="cd-dropzone-text">Drag & drop your file here</p>
                      <p className="cd-dropzone-or">or</p>
                      <span className="cd-dropzone-browse">Browse Files</span>
                      <p className="cd-dropzone-hint">Supports CSV, Excel (.xlsx), JSON</p>
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept=".csv,.xlsx,.xls,.json"
                        onChange={handleFileSelect}
                        style={{ display: 'none' }}
                      />
                    </div>
                  ) : (
                    <div className="cd-file-badge">
                      <FileText size={20} color="#f59e0b" />
                      <div className="cd-file-info">
                        <div className="cd-file-name">{uploadedFile.name}</div>
                        <div className="cd-file-size">{formatBytes(uploadedFile.size)}</div>
                      </div>
                      <button className="cd-file-remove" onClick={() => setUploadedFile(null)}>
                        <X size={14} />
                      </button>
                    </div>
                  )}
                </div>
              )}
            </>
          )}

          {/* ─── Step 4: Test ─── */}
          {step === 'test' && (
            <div className="cd-test-status">
              {testStatus === 'testing' && (
                <>
                  <div className="cd-test-icon cd-test-icon--testing">
                    <Loader2 size={24} className="ts-spinner" />
                  </div>
                  <p className="cd-test-label">Testing connection...</p>
                  <p className="cd-test-detail">Verifying credentials and connectivity</p>
                </>
              )}
              {testStatus === 'success' && (
                <>
                  <div className="cd-test-icon cd-test-icon--success">
                    <CheckCircle2 size={24} />
                  </div>
                  <p className="cd-test-label">Connection successful!</p>
                  <p className="cd-test-detail">Loading schema...</p>
                </>
              )}
              {testStatus === 'error' && (
                <>
                  <div className="cd-test-icon cd-test-icon--error">
                    <AlertCircle size={24} />
                  </div>
                  <p className="cd-test-label">Connection failed</p>
                  <p className="cd-test-detail">{testError || 'Unable to connect. Check your credentials and try again.'}</p>
                </>
              )}
              {testStatus === 'idle' && (
                <div className="cd-summary" style={{ width: '100%', textAlign: 'left' }}>
                  {connectorType && connectorType !== 'file' && (
                    <>
                      <div className="cd-summary-row">
                        <span className="cd-summary-label">Type</span>
                        <span className="cd-summary-value">{CONNECTOR_TYPES.find((c) => c.type === connectorType)?.label}</span>
                      </div>
                      {host && (
                        <div className="cd-summary-row">
                          <span className="cd-summary-label">Host</span>
                          <span className="cd-summary-value">{host}:{port}</span>
                        </div>
                      )}
                      {endpoint && (
                        <div className="cd-summary-row">
                          <span className="cd-summary-label">Endpoint</span>
                          <span className="cd-summary-value" style={{ fontSize: 12, wordBreak: 'break-all' }}>{endpoint}</span>
                        </div>
                      )}
                      <div className="cd-summary-row">
                        <span className="cd-summary-label">Database</span>
                        <span className="cd-summary-value">{database}</span>
                      </div>
                    </>
                  )}
                  {connectorType === 'file' && uploadedFile && (
                    <div className="cd-summary-row">
                      <span className="cd-summary-label">File</span>
                      <span className="cd-summary-value">{uploadedFile.name} ({formatBytes(uploadedFile.size)})</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* ─── Step 5: Schema ─── */}
          {step === 'schema' && schema && (
            <>
              <p className="cd-section-label">{schema.tables.length} tables found</p>
              <div className="cd-schema">
                {schema.tables.map((table) => (
                  <div key={table.name} className="cd-schema-table">
                    <button
                      className="cd-schema-table-header"
                      onClick={() => setExpandedTable(expandedTable === table.name ? null : table.name)}
                    >
                      <span className="cd-schema-table-name">
                        {expandedTable === table.name ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        {table.name}
                        <span className="cd-schema-col-count">{table.columns.length} cols</span>
                      </span>
                      {table.rowCount != null && (
                        <span className="cd-schema-row-count">{table.rowCount.toLocaleString()} rows</span>
                      )}
                    </button>
                    {expandedTable === table.name && (
                      <div className="cd-schema-columns">
                        {table.columns.map((col) => (
                          <div key={col.name} className="cd-schema-col">
                            {col.isPrimaryKey && <Key size={11} className="cd-schema-col-pk" />}
                            <span className="cd-schema-col-name">{col.name}</span>
                            <span className="cd-schema-col-type">{col.type}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}

          {/* ─── Step 6: Select Tables ─── */}
          {step === 'select-tables' && schema && (
            <>
              <div className="cd-select-controls">
                <span className="cd-select-count">{selectedTables.size} of {schema.tables.length} selected</span>
                <button
                  className="cd-select-all-btn"
                  onClick={selectedTables.size === schema.tables.length ? deselectAllTables : selectAllTables}
                >
                  {selectedTables.size === schema.tables.length ? 'Deselect All' : 'Select All'}
                </button>
              </div>
              <div className="cd-select-list">
                {schema.tables.map((table) => {
                  const checked = selectedTables.has(table.name);
                  return (
                    <button
                      key={table.name}
                      className={`cd-select-item ${checked ? 'cd-select-item--checked' : ''}`}
                      onClick={() => toggleTable(table.name)}
                    >
                      <div className={`cd-checkbox ${checked ? 'cd-checkbox--checked' : ''}`}>
                        {checked && <Check size={12} />}
                      </div>
                      <div className="cd-select-table-info">
                        <div className="cd-select-table-name">{table.name}</div>
                        <div className="cd-select-table-meta">
                          {table.columns.length} columns{table.rowCount != null ? ` · ${table.rowCount.toLocaleString()} rows` : ''}
                        </div>
                      </div>
                    </button>
                  );
                })}
              </div>
            </>
          )}

          {/* ─── Step 7: Profiling ─── */}
          {step === 'profiling' && (
            <div className="cd-profiling">
              {/* Animated brain icon */}
              <div className={`cd-profiling-hero ${profilingStatus === 'ready' ? 'cd-profiling-hero--done' : ''}`}>
                {profilingStatus === 'ready' ? (
                  <CheckCircle2 size={40} color="#10b981" />
                ) : profilingStatus === 'failed' ? (
                  <AlertCircle size={40} color="#ef4444" />
                ) : (
                  <Brain size={40} className="cd-profiling-pulse" />
                )}
              </div>

              <h3 className="cd-profiling-title">
                {profilingStatus === 'ready'
                  ? 'Intelligence Profile Ready!'
                  : profilingStatus === 'failed'
                    ? 'Profiling Failed'
                    : 'Building Intelligence Profile'}
              </h3>

              <p className="cd-profiling-subtitle">
                {profilingStatus === 'ready'
                  ? 'Your AI assistant now understands your data structure and is ready to answer questions.'
                  : profilingStatus === 'failed'
                    ? profilingError || 'An error occurred during profiling. You can still use the workspace.'
                    : 'Analyzing your data to create a directional analysis plan...'}
              </p>

              {/* Progress steps */}
              {profilingStatus !== 'failed' && (
                <div className="cd-profiling-steps">
                  {PROFILING_STEPS.map((ps, i) => {
                    const Icon = ps.icon;
                    const isDone = profilingStepIndex > i;
                    const isCurrent = profilingStepIndex === i && profilingStatus === 'running';
                    return (
                      <div
                        key={i}
                        className={`cd-profiling-step ${isDone ? 'cd-profiling-step--done' : ''} ${isCurrent ? 'cd-profiling-step--active' : ''}`}
                      >
                        <div className="cd-profiling-step-icon" style={{ color: isDone || isCurrent ? ps.color : undefined }}>
                          {isDone ? (
                            <Check size={14} />
                          ) : isCurrent ? (
                            <Loader2 size={14} className="ts-spinner" />
                          ) : (
                            <Icon size={14} />
                          )}
                        </div>
                        <span className="cd-profiling-step-text">{ps.text}</span>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Live message */}
              {profilingStatus === 'running' && profilingMessage && (
                <p className="cd-profiling-live">{profilingMessage}</p>
              )}
            </div>
          )}
        </div>

        {/* ─── Footer ─── */}
        <div className="cd-footer">
          {step === 'workspace-info' ? (
            <>
              <button className="cd-back-btn" onClick={handleClose}>Cancel</button>
              <button
                className="cd-next-btn"
                disabled={!wsName.trim()}
                onClick={() => setStep('choose-type')}
              >
                Next: Connect Data <ArrowRight size={14} />
              </button>
            </>
          ) : step === 'profiling' ? (
            <>
              <div />
              {profilingStatus === 'ready' || profilingStatus === 'failed' ? (
                <button className="cd-next-btn" onClick={handleOpenWorkspace}>
                  <Sparkles size={14} /> Open Workspace <ArrowRight size={14} />
                </button>
              ) : (
                <button className="cd-next-btn" disabled>
                  <Loader2 size={14} className="ts-spinner" /> Profiling...
                </button>
              )}
            </>
          ) : (
            <>
              <button className="cd-back-btn" onClick={goBack}>
                <ArrowLeft size={14} /> Back
              </button>

              {step === 'configure' && (
                <button
                  className="cd-next-btn"
                  disabled={!canProceedFromConfigure()}
                  onClick={() => { setStep('test'); setTestStatus('idle'); }}
                >
                  Next <ArrowRight size={14} />
                </button>
              )}

              {step === 'test' && testStatus === 'idle' && (
                <button className="cd-next-btn" onClick={handleTest}>
                  <Database size={14} /> Test Connection
                </button>
              )}

              {step === 'test' && testStatus === 'error' && (
                <button className="cd-next-btn" onClick={handleRetryTest}>
                  Retry
                </button>
              )}

              {step === 'schema' && (
                <button className="cd-next-btn" onClick={() => setStep('select-tables')}>
                  Select Tables <ArrowRight size={14} />
                </button>
              )}

              {step === 'select-tables' && (
                <button
                  className="cd-next-btn"
                  disabled={selectedTables.size === 0 || isSubmitting}
                  onClick={handleFinish}
                >
                  {isSubmitting ? (
                    <><Loader2 size={14} className="ts-spinner" /> Creating...</>
                  ) : (
                    <><CheckCircle2 size={14} /> Create Workspace</>
                  )}
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
