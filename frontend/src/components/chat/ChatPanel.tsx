import { useCallback } from 'react';
import { AlertTriangle } from 'lucide-react';
import type { ChatSession, InsightResult } from '../../types/chat';
import type { ScopeCustomer } from '../../types/workspace';
import { useAuthStore } from '../../store/authStore';
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

  // Soft cost warning for privileged users (admin/manager/moderator) — these
  // roles are never blocked by the daily cap, so we only warn them once their
  // own same-day spend crosses the warn threshold ($2 by default).
  const user = useAuthStore((s) => s.user);
  const isPrivileged = useAuthStore((s) => s.isPrivileged);
  const isModerator = useAuthStore((s) => s.isModerator);
  const isCustomerScoped = useAuthStore((s) => s.isCustomerScoped);
  const warnThreshold = user?.cost_warn_threshold_usd ?? 2;
  const todaySpend = user?.today_cost_usd ?? 0;
  const showCostWarning =
    (isPrivileged || isModerator) && warnThreshold > 0 && todaySpend >= warnThreshold;

  const handleFollowUp = useCallback(
    (question: string) => {
      onFollowUp(question);
    },
    [onFollowUp]
  );

  const handleRecommendation = useCallback(
    (question: string) => {
      onSend(question, 'quick');
    },
    [onSend]
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

      {showCostWarning && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            margin: '8px 12px 0',
            padding: '10px 14px',
            background: '#fffbeb',
            border: '1px solid #fcd34d',
            borderRadius: 8,
            color: '#92400e',
            fontSize: 13,
          }}
        >
          <AlertTriangle size={16} color="#d97706" />
          <span>
            You've used <strong>${todaySpend.toFixed(2)}</strong> today. This is a
            heads-up only — your access is not limited.
          </span>
        </div>
      )}

      <MessageList
        messages={messages}
        onFollowUp={handleFollowUp}
        onPushToCanvas={onPushToCanvas}
        onDeleteMessage={onDeleteMessage}
        onFeedback={onFeedback}
        compact={compact}
        showRecommendations={isCustomerScoped}
        onRecommendation={handleRecommendation}
      />
      <ChatInput
        onSend={onSend}
        isLoading={isLoading}
        disabled={!hasConnection}
        showSuggestions={showSuggestions && !compact && !isCustomerScoped}
        placeholder={hasConnection ? 'Ask about your data...' : 'Connect a database to start'}
      />
    </div>
  );
}
