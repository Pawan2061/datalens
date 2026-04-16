import { useCallback } from 'react';
import type { ChatSession, InsightResult } from '../../types/chat';
import type { ScopeCustomer } from '../../types/workspace';
import MessageList from './MessageList';
import ChatInput from './ChatInput';
import CustomerScopeSelector from '../workspace/CustomerScopeSelector';

interface ChatPanelProps {
  session: ChatSession | undefined;
  isLoading: boolean;
  hasConnection: boolean;
  scopeCustomers?: ScopeCustomer[];
  customerScope?: string;
  customerScopeName?: string;
  onScopeChange?: (id: string, name: string) => void;
  onSend: (message: string, mode: 'quick' | 'deep') => void;
  onFollowUp: (question: string) => void;
  onPushToCanvas?: (insight: InsightResult, messageId: string) => void;
  onDeleteMessage?: (messageId: string) => void;
  onFeedback?: (messageId: string, feedback: 'positive' | 'negative' | null) => void;
  compact?: boolean;
}

export default function ChatPanel({
  session,
  isLoading,
  hasConnection,
  scopeCustomers = [],
  customerScope = '',
  customerScopeName = '',
  onScopeChange,
  onSend,
  onFollowUp,
  onPushToCanvas,
  onDeleteMessage,
  onFeedback,
  compact = false,
}: ChatPanelProps) {
  const messages = session?.messages || [];
  const showSuggestions = messages.length === 0 && hasConnection;

  const handleFollowUp = useCallback(
    (question: string) => {
      onFollowUp(question);
    },
    [onFollowUp]
  );

  return (
    <div className="wv-chat-area">
      {/* Scope selector — always visible when connected */}
      {hasConnection && onScopeChange && (
        <div className="chat-scope-bar">
          <span>Viewing as:</span>
          <CustomerScopeSelector
            customers={scopeCustomers}
            selectedScope={customerScope}
            selectedName={customerScopeName}
            onScopeChange={onScopeChange}
          />
        </div>
      )}

      <MessageList
        messages={messages}
        onFollowUp={handleFollowUp}
        onPushToCanvas={onPushToCanvas}
        onDeleteMessage={onDeleteMessage}
        onFeedback={onFeedback}
        compact={compact}
      />
      <ChatInput
        onSend={onSend}
        isLoading={isLoading}
        disabled={!hasConnection}
        showSuggestions={showSuggestions && !compact}
        placeholder={hasConnection ? 'Ask about your data...' : 'Connect a database to start'}
      />
    </div>
  );
}
