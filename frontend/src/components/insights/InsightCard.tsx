import { useState } from 'react';
import { Clock, Database, Layers, LayoutGrid, Check } from 'lucide-react';
import type { InsightResult } from '../../types/chat';
import TextSummary from './TextSummary';
import ChartRenderer from './ChartRenderer';

interface InsightCardProps {
  insight: InsightResult;
  onFollowUp?: (question: string) => void;
  onPushToCanvas?: () => void;
}

export default function InsightCard({ insight, onFollowUp, onPushToCanvas }: InsightCardProps) {
  const [pushed, setPushed] = useState(false);
  const { summary, charts, tables, execution_metadata } = insight;

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

      {/* No standalone tables — data is accessed via "Data" button on each chart */}

      {/* Execution metadata — only for actual analysis with queries */}
      {execution_metadata && execution_metadata.sub_query_count > 0 && (
        <div className="ic-meta">
          <span className="ic-meta-item">
            <Clock size={12} />
            {execution_metadata.total_duration_ms < 1000
              ? `${Math.round(execution_metadata.total_duration_ms)}ms`
              : `${(execution_metadata.total_duration_ms / 1000).toFixed(1)}s`}
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
      )}
    </div>
  );
}
