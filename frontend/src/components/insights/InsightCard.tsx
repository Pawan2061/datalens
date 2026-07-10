import { Fragment, useState } from 'react';
import { Clock, Database, Layers, LayoutGrid, Check, ChevronDown, ChevronRight, Table2 } from 'lucide-react';
import type { InsightResult, TableData } from '../../types/chat';
import TextSummary from './TextSummary';
import ChartRenderer from './ChartRenderer';

function StandaloneTable({ title, columns, data }: TableData) {
  const [expanded, setExpanded] = useState(false);
  const displayData = expanded ? data : data.slice(0, 25);
  const hasMore = data.length > 25;
  if (!data.length || !columns.length) return null;

  return (
    <div className="ic-table-block">
      {title && (
        <div className="ic-table-header">
          <Table2 size={14} />
          <span>{title}</span>
          <span className="ic-table-count">{data.length.toLocaleString()} rows</span>
        </div>
      )}
      <div className="cr-datatable">
        <div className="cr-datatable-scroll">
          <table className="cr-datatable-table">
            <thead>
              <tr>
                {columns.map(col => (
                  <th key={col} className="cr-datatable-th">{col.replace(/_/g, ' ')}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {displayData.map((row, i) => (
                <tr key={i} className="cr-datatable-row">
                  {columns.map(col => (
                    <td key={col} className="cr-datatable-td">
                      {String(row[col] ?? '—')}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {hasMore && (
          <button className="cr-datatable-more" onClick={() => setExpanded(!expanded)}>
            {expanded ? 'Show less' : `Show all ${data.length} rows`}
          </button>
        )}
      </div>
    </div>
  );
}

const STEP_LABELS: Record<string, string> = {
  quick_response_check: 'Quick response check',
  cache_lookup: 'Cache lookup',
  conversational_path: 'Conversational reply',
  schema_profile_load: 'Schema / profile load',
  pre_plan: 'Pre-planning',
  agent_loop: 'Agent reasoning + queries',
  synthesis: 'Synthesis (narrative)',
  build_result: 'Build final result',
  response_guard: 'Response guard',
};

function formatSeconds(ms: number): string {
  return `${(ms / 1000).toFixed(2)} s`;
}

interface InsightCardProps {
  insight: InsightResult;
  onFollowUp?: (question: string) => void;
  onPushToCanvas?: () => void;
  showRecommendations?: boolean;
}

export default function InsightCard({ insight, onFollowUp, onPushToCanvas, showRecommendations = false }: InsightCardProps) {
  const [pushed, setPushed] = useState(false);
  const [showTimings, setShowTimings] = useState(false);
  const { summary, charts, tables, execution_metadata } = insight;
  const stepTimings = execution_metadata?.step_timings;
  const timingEntries = stepTimings
    ? Object.entries(stepTimings).filter(([, v]) => typeof v === 'number' && v > 0)
    : [];

  const handlePush = () => {
    if (onPushToCanvas && !pushed) {
      onPushToCanvas();
      setPushed(true);
    }
  };

  return (
    <div className="ic-wrap">
      {/* Push to canvas action — only when there's data to push */}
      {onPushToCanvas && ((charts && charts.length > 0) || (tables && tables.length > 0)) && (
        <button
          onClick={handlePush}
          disabled={pushed}
          className={`ic-push-btn ${pushed ? 'ic-push-btn--done' : ''}`}
        >
          {pushed ? <Check size={14} /> : <LayoutGrid size={14} />}
          {pushed ? 'Added to Canvas' : 'Push to Canvas'}
        </button>
      )}

      {/* Summary */}
      <TextSummary
        summary={summary}
        onFollowUp={onFollowUp}
        isConversational={execution_metadata?.sub_query_count === 0}
        showRecommendations={showRecommendations}
      />

      {/* Charts — responsive grid layout (each chart has its own Data toggle) */}
      {charts && charts.length > 0 && (() => {
        const kpiCharts = charts.filter(c => c.chart_type === 'kpi');
        const vizCharts = charts.filter(c => c.chart_type !== 'kpi');
        return (
          <>
            {kpiCharts.length > 0 && (
              <div className="ic-section">
                {kpiCharts.map((chart, i) => (
                  <ChartRenderer key={`kpi-${i}`} chart={chart} />
                ))}
              </div>
            )}
            {vizCharts.length > 0 && (
              <div className={`ic-chart-grid ic-chart-grid--${Math.min(vizCharts.length, 3)}`}>
                {vizCharts.map((chart, i) => (
                  <ChartRenderer key={`viz-${i}`} chart={chart} />
                ))}
              </div>
            )}
          </>
        );
      })()}

      {/* Standalone data tables — shown when data isn't already charted */}
      {tables && tables.length > 0 && (
        <div className="ic-tables">
          {tables.map((tbl, ti) => (
            <StandaloneTable key={ti} title={tbl.title} columns={tbl.columns} data={tbl.data} />
          ))}
        </div>
      )}

      {/* Execution metadata — only for actual analysis with queries */}
      {execution_metadata && execution_metadata.sub_query_count > 0 && (
        <>
          <div className="ic-meta">
            <span className="ic-meta-item">
              <Clock size={12} />
              {formatSeconds(execution_metadata.total_duration_ms)}
            </span>
            <span className="ic-meta-item">
              <Layers size={12} />
              {execution_metadata.sub_query_count} queries
            </span>
            <span className="ic-meta-item">
              <Database size={12} />
              {execution_metadata.total_rows.toLocaleString()} rows
            </span>
          </div>
          {timingEntries.length > 0 && (
            <div className="ic-timings">
              <button
                type="button"
                className="ic-timings-toggle"
                onClick={() => setShowTimings(v => !v)}
                aria-expanded={showTimings}
              >
                {showTimings ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                Timing breakdown ({timingEntries.length} steps)
              </button>
              {showTimings && (
                <div className="ic-timings-list">
                  {timingEntries
                    .sort((a, b) => b[1] - a[1])
                    .map(([step, ms]) => (
                      <Fragment key={step}>
                        <span className="ic-timings-step">
                          {STEP_LABELS[step] || step}
                        </span>
                        <span className="ic-timings-value">{formatSeconds(ms)}</span>
                      </Fragment>
                    ))}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
