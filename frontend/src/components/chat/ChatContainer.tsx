import type { ChatSession } from '../../types/chat';
import MessageList from './MessageList';
import ChatInput from './ChatInput';

interface ChatContainerProps {
  session: ChatSession | undefined;
  isLoading: boolean;
  hasConnection: boolean;
  onSend: (message: string) => void;
  onFollowUp: (question: string) => void;
}

export default function ChatContainer({ session, isLoading, hasConnection, onSend, onFollowUp }: ChatContainerProps) {
  const messages = session?.messages || [];
  const showSuggestions = messages.length === 0 && hasConnection;

  return (
    <div className="flex-1 flex flex-col min-w-0 bg-surface-chat">
      <MessageList messages={messages} onFollowUp={onFollowUp} />
      <ChatInput
        onSend={onSend}
        isLoading={isLoading}
        disabled={!hasConnection}
        showSuggestions={showSuggestions}
        placeholder={hasConnection ? 'Ask about your data...' : 'Connect a database to start'}
      />
    </div>
  );
}
