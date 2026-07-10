import { useEffect, useRef } from 'react';
import { Sparkles } from 'lucide-react';
import type { ChatMessage, InsightResult } from '../../types/chat';
import MessageBubble from './MessageBubble';

interface MessageListProps {
  messages: ChatMessage[];
  onFollowUp?: (question: string) => void;
  onPushToCanvas?: (insight: InsightResult, messageId: string) => void;
  onDeleteMessage?: (messageId: string) => void;
  onFeedback?: (messageId: string, feedback: 'positive' | 'negative' | null) => void;
  compact?: boolean;
  showRecommendations?: boolean;
  onRecommendation?: (question: string) => void;
}

const CUSTOMER_RECOMMENDATIONS = [
  'Show my month in a week analysis for July 2026',
  'What is my month wise sales?',
  'Mera Feb 2026 ka sales dedo',
  'What is my outstanding amount?',
  'Show my order status',
  'Show my recent invoices',
];

function RecommendationChips({ onRecommendation }: { onRecommendation?: (question: string) => void }) {
  if (!onRecommendation) return null;
  return (
    <div className="chat-empty-recommendations">
      <div className="chat-empty-recommendations-label">Recommended queries</div>
      <div className="chat-empty-recommendations-grid">
        {CUSTOMER_RECOMMENDATIONS.map((query) => (
          <button key={query} type="button" onClick={() => onRecommendation(query)}>
            {query}
          </button>
        ))}
      </div>
    </div>
  );
}

function CompactEmptyState({ showRecommendations, onRecommendation }: { showRecommendations?: boolean; onRecommendation?: (question: string) => void }) {
  return (
    <div className="chat-empty">
      <div className="chat-empty-icon">
        <Sparkles size={20} color="#0066cc" />
      </div>
      <h3>Ask a question</h3>
      <p>Type below to explore your data. Insights will appear on the canvas.</p>
      {showRecommendations && <RecommendationChips onRecommendation={onRecommendation} />}
    </div>
  );
}

function FullEmptyState({ showRecommendations, onRecommendation }: { showRecommendations?: boolean; onRecommendation?: (question: string) => void }) {
  return (
    <div className="chat-empty">
      <div className="chat-empty-icon chat-empty-icon--large">
        <Sparkles size={28} color="#0066cc" />
      </div>
      <h3 style={{ fontSize: 22 }}>What would you like to explore?</h3>
      <p style={{ maxWidth: 360 }}>Ask questions about your data in natural language. I'll analyze, visualize, and surface the key insights.</p>
      {showRecommendations && <RecommendationChips onRecommendation={onRecommendation} />}
    </div>
  );
}

export default function MessageList({ messages, onFollowUp, onPushToCanvas, onDeleteMessage, onFeedback, compact = false, showRecommendations = false, onRecommendation }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, messages.at(-1)?.steps.length, messages.at(-1)?.insightResult]);

  if (messages.length === 0) {
    return compact
      ? <CompactEmptyState showRecommendations={showRecommendations} onRecommendation={onRecommendation} />
      : <FullEmptyState showRecommendations={showRecommendations} onRecommendation={onRecommendation} />;
  }

  return (
    <div className="chat-messages">
      <div className="chat-messages-inner" style={{ maxWidth: 820, padding: compact ? '36px 28px' : '40px 28px' }}>
        {messages.map((msg) => (
          <MessageBubble
            key={msg.id}
            message={msg}
            onFollowUp={onFollowUp}
            onPushToCanvas={onPushToCanvas}
            onDeleteMessage={onDeleteMessage}
            onFeedback={onFeedback}
            compact={compact}
            showRecommendations={showRecommendations}
          />
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
