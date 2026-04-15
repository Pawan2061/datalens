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
}

function CompactEmptyState() {
  return (
    <div className="chat-empty">
      <div className="chat-empty-icon">
        <Sparkles size={20} color="#0066cc" />
      </div>
      <h3>Ask a question</h3>
      <p>Type below to explore your data. Insights will appear on the canvas.</p>
    </div>
  );
}

function FullEmptyState() {
  return (
    <div className="chat-empty">
      <div className="chat-empty-icon chat-empty-icon--large">
        <Sparkles size={28} color="#0066cc" />
      </div>
      <h3 style={{ fontSize: 22 }}>What would you like to explore?</h3>
      <p style={{ maxWidth: 360 }}>Ask questions about your data in natural language. I'll analyze, visualize, and surface the key insights.</p>
    </div>
  );
}

export default function MessageList({ messages, onFollowUp, onPushToCanvas, onDeleteMessage, onFeedback, compact = false }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, messages.at(-1)?.steps.length, messages.at(-1)?.insightResult]);

  if (messages.length === 0) {
    return compact ? <CompactEmptyState /> : <FullEmptyState />;
  }

  return (
    <div className="chat-messages">
      <div className="chat-messages-inner" style={{ maxWidth: compact ? '100%' : 820, padding: compact ? '20px 16px' : '32px 24px' }}>
        {messages.map((msg) => (
          <MessageBubble
            key={msg.id}
            message={msg}
            onFollowUp={onFollowUp}
            onPushToCanvas={onPushToCanvas}
            onDeleteMessage={onDeleteMessage}
            onFeedback={onFeedback}
            compact={compact}
          />
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
