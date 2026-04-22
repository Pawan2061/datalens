import { useMemo } from 'react';
import { Activity, MessageSquare, Coins, ArrowDownToLine, ArrowUpFromLine, Clock, DatabaseZap, Layers } from 'lucide-react';
import type { ChatSession } from '../../types/chat';

interface MetricsBarProps {
  sessions: ChatSession[];
}

export default function MetricsBar({ sessions }: MetricsBarProps) {
  const metrics = useMemo(() => {
    let totalQuestions = 0;
    let totalInputTokens = 0;
    let totalOutputTokens = 0;
    let totalCacheReadTokens = 0;
    let totalCacheCreationTokens = 0;
    let totalCost = 0;
    let totalDuration = 0;
    let modelName = '';
    let responseCacheHits = 0;

    for (const session of sessions) {
      for (const msg of session.messages) {
        if (msg.role === 'user') totalQuestions++;
        if (msg.insightResult?.execution_metadata) {
          const meta = msg.insightResult.execution_metadata;
          totalInputTokens += meta.input_tokens || 0;
          totalOutputTokens += meta.output_tokens || 0;
          totalCacheReadTokens += meta.cache_read_tokens || 0;
          totalCacheCreationTokens += meta.cache_creation_tokens || 0;
          totalCost += meta.estimated_cost_usd || 0;
          totalDuration += meta.total_duration_ms || 0;
          if (meta.model_name && !modelName) modelName = meta.model_name;
          if (meta.cached) responseCacheHits++;
        }
      }
    }

    return {
      totalQuestions,
      totalInputTokens,
      totalOutputTokens,
      totalCacheReadTokens,
      totalCacheCreationTokens,
      totalCost,
      avgDuration: totalQuestions > 0 ? totalDuration / totalQuestions : 0,
      modelName,
      responseCacheHits,
    };
  }, [sessions]);

  const formatTokens = (n: number) => {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
    return n.toString();
  };

  const cacheTotal = metrics.totalCacheReadTokens + metrics.totalCacheCreationTokens;
  const cacheTooltip =
    cacheTotal > 0
      ? `Read ${metrics.totalCacheReadTokens.toLocaleString()} • Written ${metrics.totalCacheCreationTokens.toLocaleString()}`
      : 'No prompt cache usage yet';

  return (
    <div className="metrics-bar">
      <div className="metrics-bar-item">
        <MessageSquare size={13} />
        <span className="metrics-bar-value">{metrics.totalQuestions}</span>
        <span className="metrics-bar-label">questions</span>
      </div>
      <div className="metrics-bar-divider" />
      <div className="metrics-bar-item" title="Fresh input tokens (non-cached)">
        <ArrowUpFromLine size={13} />
        <span className="metrics-bar-value">{formatTokens(metrics.totalInputTokens)}</span>
        <span className="metrics-bar-label">input</span>
      </div>
      <div className="metrics-bar-divider" />
      <div className="metrics-bar-item" title="Output tokens (assistant response)">
        <ArrowDownToLine size={13} />
        <span className="metrics-bar-value">{formatTokens(metrics.totalOutputTokens)}</span>
        <span className="metrics-bar-label">output</span>
      </div>
      <div className="metrics-bar-divider" />
      <div className="metrics-bar-item" title={cacheTooltip}>
        <Layers size={13} />
        <span className="metrics-bar-value">{formatTokens(cacheTotal)}</span>
        <span className="metrics-bar-label">cache</span>
      </div>
      <div className="metrics-bar-divider" />
      <div className="metrics-bar-item">
        <Coins size={13} />
        <span className="metrics-bar-value">${metrics.totalCost.toFixed(4)}</span>
        <span className="metrics-bar-label">cost</span>
      </div>
      <div className="metrics-bar-divider" />
      <div
        className="metrics-bar-item"
        title="Response-cache hits (full answer reused from a prior identical question)"
      >
        <DatabaseZap size={13} />
        <span className="metrics-bar-value">{metrics.responseCacheHits}</span>
        <span className="metrics-bar-label">reused</span>
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
