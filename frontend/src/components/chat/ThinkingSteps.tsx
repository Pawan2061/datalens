import { useState } from 'react';
import { ChevronDown, ChevronRight, Check, Loader2, AlertCircle, Brain, Database, BarChart3, Sparkles, Code2, MessageSquare, Globe } from 'lucide-react';
import type { AgentStep } from '../../types/chat';

interface ThinkingStepsProps {
  steps: AgentStep[];
  isStreaming: boolean;
}

/** Try to JSON-parse step content, return null on failure. */
function tryParse(s: AgentStep): Record<string, unknown> | null {
  try { return JSON.parse(s.content); } catch { return null; }
}

/** Check if a thinking step contains agent reasoning (longer text). */
function isReasoning(step: AgentStep): boolean {
  if (step.type !== 'thinking') return false;
  const p = tryParse(step);
  return p?.step === 'reasoning';
}

/** Format an elapsed-millisecond value as seconds (2 decimals). */
function formatStepMs(ms: number): string {
  return `${(ms / 1000).toFixed(2)}s`;
}

const STEP_CONFIG: Record<string, { icon: typeof Brain; getLabel: (s: AgentStep) => string }> = {
  thinking: {
    icon: Brain,
    getLabel: (s) => {
      const p = tryParse(s);
      const text = (p?.content as string) || s.content || 'Analyzing...';
      // Truncate long reasoning for the label; full text shown in expandable
      return text.length > 140 ? text.slice(0, 137) + '...' : text;
    },
  },
  plan: {
    icon: Sparkles,
    getLabel: (s) => {
      const p = tryParse(s);
      return p ? `Planned ${(p.sub_queries as unknown[])?.length || '?'} sub-queries` : 'Created analysis plan';
    },
  },
  sub_query_start: {
    icon: Database,
    getLabel: (s) => {
      const p = tryParse(s);
      const desc = (p?.description as string) || s.content || '';
      return desc || 'Executing query...';
    },
  },
  sub_query_result: {
    icon: Database,
    getLabel: (s) => {
      const p = tryParse(s);
      if (!p) return s.content || 'Results received';
      if (p.error) return String(p.error);
      return `${p.row_count ?? '?'} rows returned (${formatStepMs(Number(p.duration_ms) || 0)})`;
    },
  },
  api_call_start: {
    icon: Globe,
    getLabel: (s) => {
      const p = tryParse(s);
      return (p?.content as string) || s.content || 'Calling external API...';
    },
  },
  api_call_result: {
    icon: Globe,
    getLabel: (s) => {
      const p = tryParse(s);
      if (!p) return s.content || 'API response received';
      if (p.error) return `API error: ${p.error}`;
      return `API: ${p.api_name || 'External'} — ${p.row_count ?? '?'} records (${formatStepMs(Number(p.duration_ms) || 0)})`;
    },
  },
  consolidating: {
    icon: Brain,
    getLabel: (s) => s.content || 'Synthesizing insights...',
  },
  chart_selected: {
    icon: BarChart3,
    getLabel: (s) => {
      const p = tryParse(s);
      return p ? `${p.chart_type || 'Chart'} visualization selected` : s.content || 'Visualization ready';
    },
  },
  clarification: {
    icon: MessageSquare,
    getLabel: (s) => s.content || 'Asking for clarification...',
  },
  error: {
    icon: AlertCircle,
    getLabel: (s) => {
      const p = tryParse(s);
      // Show friendly message; detail available on expand
      return (p?.message as string) || s.content || 'Something went wrong';
    },
  },
};

export default function ThinkingSteps({ steps, isStreaming }: ThinkingStepsProps) {
  const [expanded, setExpanded] = useState(true);
  const [expandedDetail, setExpandedDetail] = useState<number | null>(null);
  const [showTechnicalDetails, setShowTechnicalDetails] = useState(false);

  const hasAnySql = steps.some((step) => !!step.sql);

  if (steps.length === 0 && !isStreaming) return null;

  return (
    <div className="ts-container">
      {/* Toggle */}
      <button onClick={() => setExpanded(!expanded)} className="ts-toggle">
        <div className="ts-toggle-icon">
          {expanded
            ? <ChevronDown size={12} color="#0066cc" />
            : <ChevronRight size={12} color="#0066cc" />}
        </div>
        <span>Analysis steps</span>
        <span className="ts-toggle-count">&middot; {steps.length} completed</span>
        {isStreaming && <Loader2 size={12} color="#0066cc" className="ts-spinner" />}
      </button>

      {expanded && (
        <div className="ts-steps">
          {hasAnySql && (
            <div className="ts-tech-row">
              <button
                onClick={() => {
                  setShowTechnicalDetails((prev) => {
                    const next = !prev;
                    if (!next) {
                      setExpandedDetail(null);
                    }
                    return next;
                  });
                }}
                className="ts-tech-toggle"
              >
                <Code2 size={12} />
                {showTechnicalDetails ? 'Hide technical details' : 'Show technical details'}
              </button>
            </div>
          )}
          {steps.map((step, i) => {
            const cfg = STEP_CONFIG[step.type] || STEP_CONFIG.thinking;
            const isLast = i === steps.length - 1 && !isStreaming;
            let isError = step.type === 'error';
            // Also detect errors in sub_query_result
            if (step.type === 'sub_query_result' && step.content) {
              const p = tryParse(step);
              if (p?.error) isError = true;
            }

            // Time the prior phase took: wall-clock gap between this SSE
            // event and the previous one. Server-measured durations are
            // already rendered inside specific labels (sub_query_result,
            // api_call_result), so this pill always shows the gap.
            const prevTs = i > 0 ? steps[i - 1].timestamp : null;
            const stepMs = prevTs !== null ? step.timestamp - prevTs : null;

            // Determine if this step has expandable detail
            const hasReasoning = isReasoning(step) && step.content.length > 140;
            const hasSql = !!step.sql;
            const parsed = tryParse(step);
            const errorDetail = (parsed?.error_detail as string) || '';
            const hasExpandable = hasReasoning || (showTechnicalDetails && hasSql) || (isError && errorDetail);

            return (
              <div key={i} className={`ts-step ${isReasoning(step) ? 'ts-step--reasoning' : ''}`}>
                {/* Connector line */}
                {!isLast && <div className="ts-connector" />}

                {/* Status dot */}
                <div className={`ts-dot ${isError ? 'ts-dot--error' : step.completed ? 'ts-dot--done' : 'ts-dot--active'}`}>
                  {!step.completed ? (
                    <Loader2 size={10} color="#0066cc" className="ts-spinner" />
                  ) : isError ? (
                    <AlertCircle size={10} color="#ef4444" />
                  ) : (
                    <Check size={10} color="#10b981" strokeWidth={3} />
                  )}
                </div>

                {/* Content */}
                <div className="ts-content">
                  <p className={`ts-label ${isError ? 'ts-label--error' : ''} ${isReasoning(step) ? 'ts-label--reasoning' : ''}`}>
                    <span className="ts-label-text">{cfg.getLabel(step)}</span>
                    {stepMs !== null && stepMs >= 0 && (
                      <span className="ts-step-time" title="Time since previous step">
                        {formatStepMs(stepMs)}
                      </span>
                    )}
                  </p>

                  {/* Expandable section: SQL, full reasoning, or error detail */}
                  {hasExpandable && (
                    <div className="ts-sql-section">
                      <button
                        onClick={() => setExpandedDetail(expandedDetail === i ? null : i)}
                        className="ts-sql-toggle"
                      >
                        <Code2 size={12} />
                        {expandedDetail === i
                          ? 'Hide details'
                          : showTechnicalDetails && hasSql ? 'View SQL' : hasReasoning ? 'Full reasoning' : 'Technical detail'}
                      </button>
                      {expandedDetail === i && (
                        <>
                          {hasReasoning && (
                            <div className="ts-reasoning-text">
                              {(tryParse(step)?.content as string) || step.content}
                            </div>
                          )}
                          {hasSql && (
                            <pre className="ts-sql-code">
                              {step.sql}
                            </pre>
                          )}
                          {isError && errorDetail && (
                            <pre className="ts-sql-code ts-error-detail">
                              {errorDetail}
                            </pre>
                          )}
                        </>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })}

          {isStreaming && (
            <div className="ts-step ts-step--processing">
              <div className="ts-dot ts-dot--active">
                <Loader2 size={10} color="#0066cc" className="ts-spinner" />
              </div>
              <p className="ts-label ts-label--muted">Processing...</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
