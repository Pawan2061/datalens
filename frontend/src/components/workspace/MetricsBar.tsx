import { useMemo } from 'react';
import { Activity, MessageSquare, Coins, Zap, Clock, DatabaseZap } from 'lucide-react';
import type { ChatSession } from '../../types/chat';

interface MetricsBarProps {
  sessions: ChatSession[];
}

export default function MetricsBar({ sessions }: MetricsBarProps) {
  const metrics = useMemo(() => {
    let totalQuestions = 0;
    let totalInputTokens = 0;
    let totalOutputTokens = 0;
    let totalCost = 0;
    let totalDuration = 0;
    let modelName = '';
    let cacheHits = 0;

    for (const session of sessions) {
      for (const msg of session.messages) {
        if (msg.role === 'user') totalQuestions++;
        if (msg.insightResult?.execution_metadata) {
          const meta = msg.insightResult.execution_metadata;
          totalInputTokens += meta.input_tokens || 0;
          totalOutputTokens += meta.output_tokens || 0;
          totalCost += meta.estimated_cost_usd || 0;
          totalDuration += meta.total_duration_ms || 0;
          if (meta.model_name && !modelName) modelName = meta.model_name;
          if (meta.cached) cacheHits++;
        }
      }
    }

    return {
      totalQuestions,
      totalInputTokens,
      totalOutputTokens,
      totalTokens: totalInputTokens + totalOutputTokens,
      totalCost,
      avgDuration: totalQuestions > 0 ? totalDuration / totalQuestions : 0,
      modelName,
      cacheHits,
    };
  }, [sessions]);

  const formatTokens = (n: number) => {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
    return n.toString();
  };

  return (
    <div className="metrics-bar">
      <div className="metrics-bar-item">
        <MessageSquare size={13} />
        <span className="metrics-bar-value">{metrics.totalQuestions}</span>
        <span className="metrics-bar-label">questions</span>
      </div>
      <div className="metrics-bar-divider" />
      <div className="metrics-bar-item">
        <Zap size={13} />
        <span className="metrics-bar-value">{formatTokens(metrics.totalTokens)}</span>
        <span className="metrics-bar-label">tokens</span>
      </div>
      <div className="metrics-bar-divider" />
      <div className="metrics-bar-item">
        <Coins size={13} />
        <span className="metrics-bar-value">${metrics.totalCost.toFixed(4)}</span>
        <span className="metrics-bar-label">cost</span>
      </div>
      <div className="metrics-bar-divider" />
      <div className="metrics-bar-item">
        <DatabaseZap size={13} />
        <span className="metrics-bar-value">{metrics.cacheHits}</span>
        <span className="metrics-bar-label">cached</span>
      </div>
      <div className="metrics-bar-divider" />
      <div className="metrics-bar-item">
        <Clock size={13} />
        <span className="metrics-bar-value">{(metrics.avgDuration / 1000).toFixed(1)}s</span>
        <span className="metrics-bar-label">avg time</span>
      </div>
      {metrics.modelName && (
        <>
          <div className="metrics-bar-divider" />
          <div className="metrics-bar-item metrics-bar-model">
            <Activity size={13} />
            <span className="metrics-bar-value">{metrics.modelName}</span>
          </div>
        </>
      )}
    </div>
  );
}
