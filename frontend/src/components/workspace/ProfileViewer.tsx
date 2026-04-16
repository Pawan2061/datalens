import { useState, useEffect } from 'react';
import {
  X,
  Brain,
  Database,
  Table2,
  Columns3,
  Lightbulb,
  Link2,
  ChevronDown,
  ChevronRight,
  Hash,
  Type,
  Clock,
  FileText,
  GitBranch,
  BookOpen,
  Pencil,
  Plus,
  Trash2,
  Save,
  Loader2,
  Check,
} from 'lucide-react';
import { getProfileStatus, updateProfile } from '../../services/api';

interface ProfileViewerProps {
  isOpen: boolean;
  onClose: () => void;
  workspaceId: string;
  connectionId: string;
  connectionName: string;
}

interface ColumnProfile {
  name: string;
  type: string;
  distinct_count: number;
  null_pct: number;
  top_values: string[];
  min_val: number | null;
  max_val: number | null;
  avg_val: number | null;
}

interface TableProfile {
  name: string;
  row_count: number;
  columns: ColumnProfile[];
  sample_rows: Record<string, unknown>[];
  business_summary: string;
  analysis_angles: string[];
}

interface EditableTableInsight {
  name: string;
  business_summary: string;
  analysis_angles: string[];
}

interface PlaybookEntry {
  title: string;
  question: string;
  narrative: string;
  query_template: string;
  tables: string[];
  key_columns: string[];
}

interface RawProfile {
  executive_summary: string;
  data_architecture: string;
  tables: TableProfile[];
  cross_table_insights: string[];
  suggested_questions: string[];
  directional_plan: PlaybookEntry[];
}

function isNumericType(type: string): boolean {
  const t = type.toLowerCase();
  return (
    t.includes('int') ||
    t.includes('numeric') ||
    t.includes('decimal') ||
    t.includes('float') ||
    t.includes('double') ||
    t.includes('real') ||
    t.includes('money') ||
    t.includes('bigint') ||
    t.includes('smallint')
  );
}

function getTypeIcon(type: string) {
  const t = type.toLowerCase();
  if (isNumericType(t)) return <Hash size={12} className="pv-col-type-icon pv-col-type-icon--num" />;
  if (t.includes('date') || t.includes('time') || t.includes('timestamp'))
    return <Clock size={12} className="pv-col-type-icon pv-col-type-icon--date" />;
  return <Type size={12} className="pv-col-type-icon pv-col-type-icon--text" />;
}

export default function ProfileViewer({
  isOpen,
  onClose,
  workspaceId,
  connectionId,
  connectionName,
}: ProfileViewerProps) {
  const [loading, setLoading] = useState(true);
  const [profile, setProfile] = useState<RawProfile | null>(null);
  const [generatedAt, setGeneratedAt] = useState('');
  const [durationMs, setDurationMs] = useState(0);
  const [expandedTables, setExpandedTables] = useState<Set<string>>(new Set());

  // Edit mode state
  const [editMode, setEditMode] = useState(false);
  const [editPlan, setEditPlan] = useState<PlaybookEntry[]>([]);
  const [editQuestions, setEditQuestions] = useState<string[]>([]);
  const [editExecutiveSummary, setEditExecutiveSummary] = useState('');
  const [editDataArchitecture, setEditDataArchitecture] = useState('');
  const [editCrossTableInsights, setEditCrossTableInsights] = useState<string[]>([]);
  const [editTables, setEditTables] = useState<EditableTableInsight[]>([]);
  const [saving, setSaving] = useState(false);
  const [saveToast, setSaveToast] = useState<string | null>(null);
  const [expandedEdit, setExpandedEdit] = useState<number | null>(null);

  useEffect(() => {
    if (!isOpen || !workspaceId || !connectionId) return;

    setLoading(true);
    getProfileStatus(workspaceId, connectionId)
      .then((res: Record<string, unknown>) => {
        if (res.raw_profile) {
          setProfile(res.raw_profile as unknown as RawProfile);
          // Expand first table by default
          const tables = (res.raw_profile as unknown as RawProfile).tables;
          if (tables.length > 0) {
            setExpandedTables(new Set([tables[0].name]));
          }
        }
        if (res.generated_at) setGeneratedAt(res.generated_at as string);
        if (res.generation_duration_ms) setDurationMs(res.generation_duration_ms as number);
      })
      .catch(() => {
        setProfile(null);
      })
      .finally(() => setLoading(false));
  }, [isOpen, workspaceId, connectionId]);

  if (!isOpen) return null;

  const toggleTable = (name: string) => {
    setExpandedTables((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const startEdit = () => {
    if (!profile) return;
    setEditExecutiveSummary(profile.executive_summary || '');
    setEditDataArchitecture(profile.data_architecture || '');
    setEditCrossTableInsights([...(profile.cross_table_insights || [])]);
    setEditTables(
      profile.tables.map((table) => ({
        name: table.name,
        business_summary: table.business_summary || '',
        analysis_angles: [...table.analysis_angles],
      }))
    );
    setEditPlan(profile.directional_plan.map((e) => ({ ...e, tables: [...e.tables], key_columns: [...e.key_columns] })));
    setEditQuestions([...profile.suggested_questions]);
    setEditMode(true);
    setExpandedEdit(null);
  };

  const cancelEdit = () => {
    setEditMode(false);
    setEditPlan([]);
    setEditQuestions([]);
    setEditExecutiveSummary('');
    setEditDataArchitecture('');
    setEditCrossTableInsights([]);
    setEditTables([]);
    setExpandedEdit(null);
  };

  const updateEntry = (idx: number, field: keyof PlaybookEntry, value: string | string[]) => {
    setEditPlan((prev) => prev.map((e, i) => i === idx ? { ...e, [field]: value } : e));
  };

  const updateTableInsight = (
    tableName: string,
    field: keyof EditableTableInsight,
    value: string | string[],
  ) => {
    setEditTables((prev) => prev.map((table) => (
      table.name === tableName ? { ...table, [field]: value } : table
    )));
  };

  const addEntry = () => {
    const newEntry: PlaybookEntry = {
      title: '', question: '', narrative: '', query_template: '',
      tables: [], key_columns: [],
    };
    setEditPlan((prev) => [...prev, newEntry]);
    setExpandedEdit(editPlan.length);
  };

  const removeEntry = (idx: number) => {
    setEditPlan((prev) => prev.filter((_, i) => i !== idx));
    setExpandedEdit(null);
  };

  const moveEntry = (idx: number, dir: -1 | 1) => {
    const newIdx = idx + dir;
    if (newIdx < 0 || newIdx >= editPlan.length) return;
    setEditPlan((prev) => {
      const arr = [...prev];
      [arr[idx], arr[newIdx]] = [arr[newIdx], arr[idx]];
      return arr;
    });
    setExpandedEdit(newIdx);
  };

  const saveEdits = async () => {
    setSaving(true);
    try {
      await updateProfile(workspaceId, connectionId, {
        executive_summary: editExecutiveSummary,
        data_architecture: editDataArchitecture,
        cross_table_insights: editCrossTableInsights,
        suggested_questions: editQuestions,
        directional_plan: editPlan,
        tables: editTables,
      });
      // Update local profile
      if (profile) {
        setProfile({
          ...profile,
          executive_summary: editExecutiveSummary,
          data_architecture: editDataArchitecture,
          cross_table_insights: editCrossTableInsights,
          suggested_questions: editQuestions,
          directional_plan: editPlan,
          tables: profile.tables.map((table) => {
            const editTable = editTables.find((entry) => entry.name === table.name);
            return editTable
              ? {
                  ...table,
                  business_summary: editTable.business_summary,
                  analysis_angles: editTable.analysis_angles,
                }
              : table;
          }),
        });
      }
      setEditMode(false);
      setSaveToast('Profile insights saved successfully');
      setTimeout(() => setSaveToast(null), 3000);
    } catch (e: any) {
      setSaveToast(`Error: ${e.message}`);
      setTimeout(() => setSaveToast(null), 4000);
    }
    setSaving(false);
  };

  const totalRows = profile?.tables.reduce((sum, t) => sum + t.row_count, 0) || 0;
  const totalColumns = profile?.tables.reduce((sum, t) => sum + t.columns.length, 0) || 0;

  const formattedDate = generatedAt
    ? new Date(generatedAt).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    : '';

  return (
    <div className="pv-overlay" onClick={onClose}>
      <div className="pv-dialog" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="pv-header">
          <div className="pv-header-left">
            <Brain size={20} className="pv-header-icon" />
            <div>
              <h2 className="pv-title">Data Intelligence Profile</h2>
              <p className="pv-subtitle">{connectionName}</p>
            </div>
          </div>
          <div className="pv-header-actions">
            {!loading && profile && (
              !editMode ? (
                <button className="pv-edit-btn" onClick={startEdit}>
                  <Pencil size={13} /> Edit Insights
                </button>
              ) : (
                <>
                  <button className="pv-edit-btn pv-edit-btn--cancel" onClick={cancelEdit}>Cancel</button>
                  <button className="pv-edit-btn pv-edit-btn--save" onClick={saveEdits} disabled={saving}>
                    {saving ? <Loader2 size={13} className="ts-spinner" /> : <Save size={13} />}
                    {saving ? 'Saving...' : 'Save Changes'}
                  </button>
                </>
              )
            )}
          <button className="pv-close-btn" onClick={onClose}>
            <X size={18} />
          </button>
          </div>
        </div>

        {/* Body */}
        <div className="pv-body">
          {loading ? (
            <div className="pv-loading">Loading profile...</div>
          ) : !profile ? (
            <div className="pv-loading">No profile data available</div>
          ) : (
            <>
              {/* Summary strip */}
              <div className="pv-summary-strip">
                <div className="pv-stat">
                  <Database size={14} />
                  <span>{profile.tables.length} tables</span>
                </div>
                <div className="pv-stat">
                  <Columns3 size={14} />
                  <span>{totalColumns} columns</span>
                </div>
                <div className="pv-stat">
                  <Table2 size={14} />
                  <span>{totalRows.toLocaleString()} rows</span>
                </div>
                {durationMs > 0 && (
                  <div className="pv-stat pv-stat--muted">
                    <Clock size={14} />
                    <span>Profiled in {(durationMs / 1000).toFixed(1)}s</span>
                  </div>
                )}
                {formattedDate && (
                  <div className="pv-stat pv-stat--muted">
                    <span>{formattedDate}</span>
                  </div>
                )}
              </div>

              {/* Executive Summary */}
              {(editMode || profile.executive_summary) && (
                <div className="pv-section">
                  <h3 className="pv-section-title">
                    <FileText size={15} />
                    Executive Summary
                  </h3>
                  {editMode ? (
                    <textarea
                      className="pv-edit-textarea"
                      rows={5}
                      value={editExecutiveSummary}
                      onChange={(e) => setEditExecutiveSummary(e.target.value)}
                      placeholder="Summarize the most important characteristics of this dataset."
                    />
                  ) : (
                    <p className="pv-narrative">{profile.executive_summary}</p>
                  )}
                </div>
              )}

              {/* Data Architecture */}
              {(editMode || profile.data_architecture) && (
                <div className="pv-section">
                  <h3 className="pv-section-title">
                    <GitBranch size={15} />
                    Data Architecture &amp; Relationships
                  </h3>
                  {editMode ? (
                    <textarea
                      className="pv-edit-textarea"
                      rows={5}
                      value={editDataArchitecture}
                      onChange={(e) => setEditDataArchitecture(e.target.value)}
                      placeholder="Describe key joins, dimensions, and how the tables relate."
                    />
                  ) : (
                    <p className="pv-narrative">{profile.data_architecture}</p>
                  )}
                </div>
              )}

              {/* Tables */}
              <div className="pv-section">
                <h3 className="pv-section-title">
                  <Database size={15} />
                  Table Intelligence
                </h3>

                {profile.tables.map((table) => {
                  const isExpanded = expandedTables.has(table.name);
                  return (
                    <div key={table.name} className="pv-table-card">
                      <button
                        className="pv-table-header"
                        onClick={() => toggleTable(table.name)}
                      >
                        {isExpanded ? (
                          <ChevronDown size={16} />
                        ) : (
                          <ChevronRight size={16} />
                        )}
                        <span className="pv-table-name">{table.name}</span>
                        <span className="pv-table-rows">
                          {table.row_count.toLocaleString()} rows
                        </span>
                      </button>

                      {isExpanded && (
                        <div className="pv-table-body">
                          {editMode ? (
                            <div className="pv-edit-table-section">
                              <label className="pv-edit-label">
                                Table summary
                                <textarea
                                  className="pv-edit-textarea"
                                  rows={3}
                                  value={editTables.find((entry) => entry.name === table.name)?.business_summary || ''}
                                  onChange={(e) => updateTableInsight(table.name, 'business_summary', e.target.value)}
                                  placeholder="Explain what this table represents and how it should be used."
                                />
                              </label>
                              <label className="pv-edit-label">
                                Analysis angles <span style={{ fontSize: 11, color: '#9ca3af' }}>(one per line)</span>
                                <textarea
                                  className="pv-edit-textarea"
                                  rows={4}
                                  value={(editTables.find((entry) => entry.name === table.name)?.analysis_angles || []).join('\n')}
                                  onChange={(e) => updateTableInsight(
                                    table.name,
                                    'analysis_angles',
                                    e.target.value.split('\n').map((value) => value.trim()).filter(Boolean),
                                  )}
                                  placeholder={'Revenue trend by month\nTop entities by value\nMissing-data review'}
                                />
                              </label>
                            </div>
                          ) : (
                            table.business_summary && (
                              <p className="pv-table-summary">{table.business_summary}</p>
                            )
                          )}

                          {/* Columns */}
                          <div className="pv-columns-grid">
                            {table.columns
                              .filter((c) => !c.name.startsWith('_'))
                              .map((col) => (
                                <div key={col.name} className="pv-col-card">
                                  <div className="pv-col-header">
                                    {getTypeIcon(col.type)}
                                    <span className="pv-col-name">{col.name}</span>
                                    <span className="pv-col-type">{col.type}</span>
                                  </div>
                                  <div className="pv-col-stats">
                                    {col.top_values.length > 0 && (
                                      <div className="pv-col-detail">
                                        <span className="pv-col-label">Values:</span>
                                        <span className="pv-col-values">
                                          {col.top_values.slice(0, 5).join(', ')}
                                          {col.distinct_count > 5 && (
                                            <span className="pv-col-more">
                                              {' '}+{col.distinct_count - 5} more
                                            </span>
                                          )}
                                        </span>
                                      </div>
                                    )}
                                    {col.min_val !== null && (
                                      <div className="pv-col-detail">
                                        <span className="pv-col-label">Range:</span>
                                        <span>{col.min_val} – {col.max_val}</span>
                                        {col.avg_val !== null && (
                                          <span className="pv-col-avg">(avg: {col.avg_val})</span>
                                        )}
                                      </div>
                                    )}
                                    {col.null_pct > 0 && (
                                      <div className="pv-col-detail">
                                        <span className="pv-col-label">Null:</span>
                                        <span className={col.null_pct > 10 ? 'pv-col-warn' : ''}>
                                          {col.null_pct}%
                                        </span>
                                      </div>
                                    )}
                                  </div>
                                </div>
                              ))}
                          </div>

                          {/* Sample rows */}
                          {table.sample_rows.length > 0 && (
                            <div className="pv-sample">
                              <span className="pv-sample-label">Sample record:</span>
                              <pre className="pv-sample-json">
                                {JSON.stringify(table.sample_rows[0], null, 2)}
                              </pre>
                            </div>
                          )}

                          {/* Analysis angles */}
                          {!editMode && table.analysis_angles.length > 0 && (
                            <div className="pv-angles">
                              <span className="pv-angles-label">
                                <Lightbulb size={13} />
                                Analysis angles
                              </span>
                              <ul className="pv-angles-list">
                                {table.analysis_angles.map((angle, i) => (
                                  <li key={i}>{angle}</li>
                                ))}
                              </ul>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>

              {/* Cross-table insights */}
              {(editMode || profile.cross_table_insights.length > 0) && (
                <div className="pv-section">
                  <h3 className="pv-section-title">
                    <Link2 size={15} />
                    Cross-Table Relationships
                  </h3>
                  {editMode ? (
                    <label className="pv-edit-label">
                      Insight bullets <span style={{ fontSize: 11, color: '#9ca3af' }}>(one per line)</span>
                      <textarea
                        className="pv-edit-textarea"
                        rows={5}
                        value={editCrossTableInsights.join('\n')}
                        onChange={(e) => setEditCrossTableInsights(
                          e.target.value.split('\n').map((value) => value.trim()).filter(Boolean),
                        )}
                        placeholder={'Customer joins invoice via customer_id\nInvoice lines roll up to invoice header'}
                      />
                    </label>
                  ) : (
                    <ul className="pv-insight-list">
                      {profile.cross_table_insights.map((insight, i) => (
                        <li key={i}>{insight}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              {/* Intelligence Playbook */}
              <div className="pv-section">
                <div className="pv-section-header">
                  <h3 className="pv-section-title">
                    <BookOpen size={15} />
                    Intelligence Playbook
                    <span style={{ fontSize: 12, fontWeight: 400, color: '#9ca3af', marginLeft: 8 }}>
                      ({editMode ? editPlan.length : (profile.directional_plan?.length || 0)} questions)
                    </span>
                  </h3>
                </div>

                {editMode ? (
                  /* ── EDIT MODE ── */
                  <div className="pv-edit-list">
                    {editPlan.map((entry, i) => {
                      const isExpanded = expandedEdit === i;
                      return (
                        <div key={i} className={`pv-edit-card ${isExpanded ? 'pv-edit-card--open' : ''}`}>
                          <div className="pv-edit-card-header" onClick={() => setExpandedEdit(isExpanded ? null : i)}>
                            <span className="pv-playbook-num">{i + 1}</span>
                            <div style={{ flex: 1, minWidth: 0 }}>
                              <div style={{ fontSize: 14, fontWeight: 600, color: '#1f2937' }}>
                                {entry.title || <span style={{ color: '#d1d5db', fontStyle: 'italic' }}>Untitled question...</span>}
                              </div>
                              <div style={{ fontSize: 12, color: '#6b7280', marginTop: 2 }}>{entry.question || 'No question text'}</div>
                            </div>
                            <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                              <button className="pv-edit-icon-btn" title="Move up" onClick={(e) => { e.stopPropagation(); moveEntry(i, -1); }} disabled={i === 0}>&#9650;</button>
                              <button className="pv-edit-icon-btn" title="Move down" onClick={(e) => { e.stopPropagation(); moveEntry(i, 1); }} disabled={i === editPlan.length - 1}>&#9660;</button>
                              <button className="pv-edit-icon-btn pv-edit-icon-btn--danger" title="Remove" onClick={(e) => { e.stopPropagation(); removeEntry(i); }}>
                                <Trash2 size={13} />
                              </button>
                              <ChevronDown size={16} style={{ color: '#9ca3af', transform: isExpanded ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }} />
                            </div>
                          </div>

                          {isExpanded && (
                            <div className="pv-edit-card-body">
                              <label className="pv-edit-label">
                                Title
                                <input type="text" className="pv-edit-input" value={entry.title} placeholder="e.g. Top 10 Customers by Invoice Amount"
                                  onChange={(e) => updateEntry(i, 'title', e.target.value)} />
                              </label>
                              <label className="pv-edit-label">
                                Question
                                <input type="text" className="pv-edit-input" value={entry.question} placeholder="e.g. Which are our top 10 customers by total invoice amount?"
                                  onChange={(e) => updateEntry(i, 'question', e.target.value)} />
                              </label>
                              <label className="pv-edit-label">
                                Description / Narrative
                                <textarea className="pv-edit-textarea" rows={3} value={entry.narrative}
                                  placeholder="Describe what this query does, data caveats, and how to interpret results..."
                                  onChange={(e) => updateEntry(i, 'narrative', e.target.value)} />
                              </label>
                              <label className="pv-edit-label">
                                SQL Query Template
                                <textarea className="pv-edit-textarea pv-edit-textarea--code" rows={6} value={entry.query_template}
                                  placeholder={"SELECT\n  cm.customer_name,\n  SUM(i.inv_amount) AS total\nFROM invoice i\nJOIN customer_master cm ON i.customer_id = cm.customer_id\nGROUP BY cm.customer_name\nORDER BY total DESC\nLIMIT 10;"}
                                  onChange={(e) => updateEntry(i, 'query_template', e.target.value)} />
                              </label>
                              <div style={{ display: 'flex', gap: 12 }}>
                                <label className="pv-edit-label" style={{ flex: 1 }}>
                                  Tables <span style={{ fontSize: 11, color: '#9ca3af' }}>(comma-separated)</span>
                                  <input type="text" className="pv-edit-input" value={entry.tables.join(', ')}
                                    placeholder="invoice, customer_master"
                                    onChange={(e) => updateEntry(i, 'tables', e.target.value.split(',').map(s => s.trim()).filter(Boolean))} />
                                </label>
                                <label className="pv-edit-label" style={{ flex: 1 }}>
                                  Key Columns <span style={{ fontSize: 11, color: '#9ca3af' }}>(comma-separated)</span>
                                  <input type="text" className="pv-edit-input" value={entry.key_columns.join(', ')}
                                    placeholder="customer_id, inv_amount"
                                    onChange={(e) => updateEntry(i, 'key_columns', e.target.value.split(',').map(s => s.trim()).filter(Boolean))} />
                                </label>
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}

                    <button className="pv-add-question-btn" onClick={addEntry}>
                      <Plus size={16} /> Add New Question
                    </button>
                  </div>
                ) : (
                  /* ── VIEW MODE ── */
                  profile.directional_plan && profile.directional_plan.length > 0 ? (
                    <div className="pv-playbook">
                      {profile.directional_plan.map((entry, i) => (
                        <div key={i} className="pv-playbook-entry">
                          <div className="pv-playbook-header">
                            <span className="pv-playbook-num">{i + 1}</span>
                            <div>
                              <h4 className="pv-playbook-title">{entry.title || `Analysis ${i + 1}`}</h4>
                              <p className="pv-playbook-question">{entry.question}</p>
                            </div>
                          </div>
                          {entry.narrative && (
                            <p className="pv-playbook-narrative">{entry.narrative}</p>
                          )}
                          {entry.query_template && (
                            <div className="pv-playbook-query">
                              <span className="pv-playbook-query-label">Query template:</span>
                              <pre className="pv-playbook-query-code">{entry.query_template}</pre>
                            </div>
                          )}
                          {(entry.tables.length > 0 || entry.key_columns.length > 0) && (
                            <div className="pv-playbook-meta">
                              {entry.tables.length > 0 && (
                                <span className="pv-playbook-tag">
                                  <Database size={11} />
                                  {entry.tables.join(', ')}
                                </span>
                              )}
                              {entry.key_columns.length > 0 && (
                                <span className="pv-playbook-tag">
                                  <Columns3 size={11} />
                                  {entry.key_columns.join(', ')}
                                </span>
                              )}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p style={{ color: '#9ca3af', fontSize: 13 }}>No playbook entries yet. Switch to edit mode to add them.</p>
                  )
                )}
              </div>

              <div className="pv-section">
                <h3 className="pv-section-title">
                  <Lightbulb size={15} />
                  Suggested Questions
                </h3>
                {editMode ? (
                  <label className="pv-edit-label">
                    Questions <span style={{ fontSize: 11, color: '#9ca3af' }}>(one per line)</span>
                    <textarea
                      className="pv-edit-textarea"
                      rows={5}
                      value={editQuestions.join('\n')}
                      onChange={(e) => setEditQuestions(
                        e.target.value.split('\n').map((value) => value.trim()).filter(Boolean),
                      )}
                      placeholder={'What drives late payments?\nWhich customers contribute most revenue?'}
                    />
                  </label>
                ) : profile.suggested_questions.length > 0 ? (
                  <div className="pv-questions-grid">
                    {profile.suggested_questions.map((q, i) => (
                      <div key={i} className="pv-question-card">{q}</div>
                    ))}
                  </div>
                ) : (
                  <p style={{ color: '#9ca3af', fontSize: 13 }}>No suggested questions yet.</p>
                )}
              </div>

              {/* Save toast */}
              {saveToast && (
                <div className={`pv-toast ${saveToast.startsWith('Error') ? 'pv-toast--error' : 'pv-toast--success'}`}>
                  {saveToast.startsWith('Error') ? <X size={14} /> : <Check size={14} />}
                  {saveToast}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
