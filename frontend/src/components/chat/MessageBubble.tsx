import { useState } from 'react';
import { Sparkles, LayoutGrid, Check, Trash2, ThumbsUp, ThumbsDown, Zap } from 'lucide-react';
import type { ChatMessage, InsightResult } from '../../types/chat';
import ThinkingSteps from './ThinkingSteps';
import InsightCard from '../insights/InsightCard';

/** Renders simple markdown bold (**text**) as <strong> tags */
function renderBoldText(text: string) {
  const parts = text.split(/\*\*(.+?)\*\*/g);
  return parts.map((part, i) =>
    i % 2 === 1 ? <strong key={i}>{part}</strong> : part
  );
}

interface MessageBubbleProps {
  message: ChatMessage;
  onFollowUp?: (question: string) => void;
  onPushToCanvas?: (insight: InsightResult, messageId: string) => void;
  onDeleteMessage?: (messageId: string) => void;
  onFeedback?: (messageId: string, feedback: 'positive' | 'negative' | null) => void;
  compact?: boolean;
}

export default function MessageBubble({ message, onFollowUp, onPushToCanvas, onDeleteMessage, onFeedback, compact = false }: MessageBubbleProps) {
  const isUser = message.role === 'user';

  if (isUser) {
    return (
      <div className="chat-msg chat-msg--user">
        <div className="chat-msg-actions-wrap">
          {onDeleteMessage && (
            <button
              className="chat-msg-delete-btn"
              onClick={() => onDeleteMessage(message.id)}
              title="Delete message"
            >
              <Trash2 size={13} />
            </button>
          )}
          <div className="chat-bubble-user">
            <p>{message.content}</p>
          </div>
        </div>
      </div>
    );
  }

  const isDeep = message.analysisMode === 'deep';
  const isDone = !message.isStreaming;

  return (
    <div className="chat-msg chat-msg--assistant">
      {/* Hover delete button */}
      {onDeleteMessage && isDone && (
        <button
          className="chat-msg-delete-btn chat-msg-delete-btn--assistant"
          onClick={() => onDeleteMessage(message.id)}
          title="Delete message"
        >
          <Trash2 size={13} />
        </button>
      )}

      <div style={{ maxWidth: compact ? '100%' : 720 }}>
        {/* Assistant header */}
        <div className="chat-assistant-header">
          <div className="chat-assistant-icon">
            <Sparkles size={12} color="#fff" />
          </div>
          <span>DataLens</span>
          {message.analysisMode && message.insightResult && (message.insightResult.charts?.length > 0 || message.insightResult.tables?.length > 0) && (
            <span className={`chat-mode-badge ${isDeep ? 'chat-mode-badge--deep' : ''}`}>
              {isDeep ? 'Deep Analysis' : 'Quick Insight'}
            </span>
          )}
          {message.insightResult?.execution_metadata?.cached && (
            <span className="chat-cached-badge">
              <Zap size={10} />
              Cached
            </span>
          )}
        </div>

        {/* Thinking steps */}
        {(message.steps.length > 0 || message.isStreaming) && (
          <ThinkingSteps steps={message.steps} isStreaming={!!message.isStreaming && !message.insightResult} />
        )}

        {/* Insight result */}
        {message.insightResult && (() => {
          const hasVisuals = (message.insightResult.charts?.length ?? 0) > 0 || (message.insightResult.tables?.length ?? 0) > 0;
          // Use compact preview only when there are charts/tables to summarize
          // Otherwise show full InsightCard (for conversational or 0-row results)
          return compact && hasVisuals ? (
            <CompactInsightPreview
              insight={message.insightResult}
              messageId={message.id}
              isDeep={isDeep}
              onPushToCanvas={onPushToCanvas}
              onFollowUp={onFollowUp}
            />
          ) : (
            <InsightCard
              insight={message.insightResult}
              onFollowUp={onFollowUp}
              onPushToCanvas={onPushToCanvas && hasVisuals ? () => onPushToCanvas(message.insightResult!, message.id) : undefined}
            />
          );
        })()}

        {/* Pure streaming state */}
        {message.isStreaming && !message.insightResult && message.steps.length === 0 && (
          <div className="chat-typing">
            <span className="typing-dot" />
            <span className="typing-dot" />
            <span className="typing-dot" />
            <span className="chat-typing-text">Analyzing your question...</span>
          </div>
        )}

        {/* Feedback buttons */}
        {isDone && message.insightResult && onFeedback && (
          <div className="chat-feedback">
            <button
              className={`chat-feedback-btn ${message.feedback === 'positive' ? 'chat-feedback-btn--active-positive' : ''}`}
              onClick={() => onFeedback(message.id, 'positive')}
              title="Helpful"
            >
              <ThumbsUp size={13} />
            </button>
            <button
              className={`chat-feedback-btn ${message.feedback === 'negative' ? 'chat-feedback-btn--active-negative' : ''}`}
              onClick={() => onFeedback(message.id, 'negative')}
              title="Not helpful"
            >
              <ThumbsDown size={13} />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function CompactInsightPreview({
  insight,
  messageId,
  isDeep,
  onPushToCanvas,
  onFollowUp,
}: {
  insight: InsightResult;
  messageId: string;
  isDeep: boolean;
  onPushToCanvas?: (insight: InsightResult, messageId: string) => void;
  onFollowUp?: (question: string) => void;
}) {
  const [pushed, setPushed] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const { summary, charts, tables } = insight;
  const chartCount = charts?.length || 0;
  const tableCount = tables?.length || 0;

  // Extract a clean narrative — skip raw JSON if backend returned it
  let narrativeText = summary.narrative || '';
  if (narrativeText.trimStart().startsWith('{')) {
    try {
      const parsed = JSON.parse(narrativeText);
      if (parsed.narrative) narrativeText = parsed.narrative;
    } catch { /* use as-is */ }
  }

  // First sentence or first 200 chars as the collapsed snippet
  const firstSentence = narrativeText.split(/(?<=[.!?])\s/)[0] || '';
  const snippet = firstSentence.length > 200 ? firstSentence.slice(0, 200) + '...' : firstSentence;
  const hasMore = narrativeText.length > snippet.length;

  const handlePush = () => {
    if (onPushToCanvas && !pushed) {
      onPushToCanvas(insight, messageId);
      setPushed(true);
    }
  };

  return (
    <div className="chat-compact-preview">
      <h4>{summary.title}</h4>
      <p>{renderBoldText(expanded ? narrativeText : snippet)}</p>
      {hasMore && (
        <button className="chat-compact-expand-btn" onClick={() => setExpanded(!expanded)}>
          {expanded ? 'Show less' : 'Read more'}
        </button>
      )}

      {(chartCount > 0 || tableCount > 0) && (
        <div className="chat-compact-footer">
          <div className="chat-compact-meta">
            {chartCount > 0 && <span>{chartCount} chart{chartCount > 1 ? 's' : ''}</span>}
            {tableCount > 0 && <span>{tableCount} table{tableCount > 1 ? 's' : ''}</span>}
          </div>

          {!isDeep && onPushToCanvas && (
            <button
              onClick={handlePush}
              disabled={pushed}
              className={`chat-push-btn ${pushed ? 'chat-push-btn--done' : ''}`}
            >
              {pushed ? <Check size={12} /> : <LayoutGrid size={12} />}
              {pushed ? 'On Canvas' : 'Push to Canvas'}
            </button>
          )}

          {isDeep && (
            <span className="chat-auto-pushed">
              <LayoutGrid size={12} />
              Auto-added to Canvas
            </span>
          )}
        </div>
      )}

      {/* Follow-up suggestions — only show when expanded */}
      {expanded && summary.follow_up_questions && summary.follow_up_questions.length > 0 && onFollowUp && (
        <div className="chat-compact-followups">
          {summary.follow_up_questions.slice(0, 3).map((q, i) => (
            <button key={i} onClick={() => onFollowUp(q)} className="chat-compact-followup-btn">
              {q}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
