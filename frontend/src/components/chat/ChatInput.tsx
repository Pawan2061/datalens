import { useState, useRef, useEffect } from 'react';
import { ArrowUp, Zap, Brain, Play, X, Sparkles } from 'lucide-react';

interface ChatInputProps {
  onSend: (message: string, mode: 'quick' | 'deep') => void;
  isLoading: boolean;
  disabled: boolean;
  placeholder?: string;
  showSuggestions?: boolean;
}

export default function ChatInput({ onSend, isLoading, disabled, placeholder, showSuggestions }: ChatInputProps) {
  const [input, setInput] = useState('');
  const [analysisMode, setAnalysisMode] = useState<'quick' | 'deep'>('quick');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Deep brief state
  const [deepObjective, setDeepObjective] = useState('');
  const [deepScope, setDeepScope] = useState('');
  const [deepMetrics, setDeepMetrics] = useState('');
  const objectiveRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (analysisMode === 'quick' && textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 160) + 'px';
    }
  }, [input, analysisMode]);

  // Auto-resize objective textarea
  useEffect(() => {
    if (objectiveRef.current) {
      objectiveRef.current.style.height = 'auto';
      objectiveRef.current.style.height = Math.min(objectiveRef.current.scrollHeight, 140) + 'px';
    }
  }, [deepObjective]);

  // Focus objective when switching to deep mode
  useEffect(() => {
    if (analysisMode === 'deep') {
      if (input.trim() && !deepObjective) {
        setDeepObjective(input.trim());
        setInput('');
      }
      setTimeout(() => objectiveRef.current?.focus(), 50);
    }
  }, [analysisMode]);

  const handleQuickSubmit = () => {
    const trimmed = input.trim();
    if (!trimmed || isLoading || disabled) return;
    onSend(trimmed, 'quick');
    setInput('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
  };

  const handleDeepSubmit = () => {
    const objective = deepObjective.trim();
    if (!objective || isLoading || disabled) return;

    let message = objective;
    const scope = deepScope.trim();
    const metrics = deepMetrics.trim();

    if (scope || metrics) {
      message += '\n\n';
      if (scope) message += `Scope: ${scope}\n`;
      if (metrics) message += `Key Metrics: ${metrics}`;
    }

    onSend(message.trim(), 'deep');
    setDeepObjective('');
    setDeepScope('');
    setDeepMetrics('');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleQuickSubmit();
    }
  };

  const handleDeepKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && e.ctrlKey) {
      e.preventDefault();
      handleDeepSubmit();
    }
  };

  const handleCancelDeep = () => {
    setAnalysisMode('quick');
    if (deepObjective.trim() && !deepScope.trim() && !deepMetrics.trim()) {
      setInput(deepObjective.trim());
    }
    setDeepObjective('');
    setDeepScope('');
    setDeepMetrics('');
  };

  const canSendQuick = input.trim().length > 0 && !isLoading && !disabled;
  const canSendDeep = deepObjective.trim().length > 0 && !isLoading && !disabled;

  const placeholderText = placeholder || 'Ask about your data...';

  return (
    <div className="chat-input-area">
      {/* Suggestion chips */}
      {showSuggestions && analysisMode === 'quick' && (
        <div className="chat-suggestions">
          {[
            { icon: '\u{1F4CA}', text: 'Show me revenue by product category' },
            { icon: '\u{1F465}', text: 'What are the customer acquisition trends?' },
            { icon: '\u{1F4C8}', text: 'How has growth trended over time?' },
            { icon: '\u{1F3AF}', text: 'Give me a business overview' },
          ].map((s) => (
            <button
              key={s.text}
              onClick={() => onSend(s.text, 'quick')}
              disabled={isLoading || disabled}
              className="chat-suggestion-chip"
            >
              <span className="chat-suggestion-icon">{s.icon}</span>
              <span>{s.text}</span>
            </button>
          ))}
        </div>
      )}

      {/* Deep Analysis Brief — floating card above input */}
      {analysisMode === 'deep' && (
        <div className="deep-brief-card">
          <div className="deep-brief-header">
            <div className="deep-brief-header-left">
              <div className="deep-brief-icon">
                <Sparkles size={14} color="#fff" />
              </div>
              <span className="deep-brief-title">Deep Analysis Brief</span>
            </div>
            <button onClick={handleCancelDeep} className="deep-brief-close" disabled={isLoading}>
              <X size={14} />
            </button>
          </div>

          <div className="deep-brief-body">
            <div className="deep-brief-field">
              <label className="deep-brief-label">What do you want to analyze?</label>
              <textarea
                ref={objectiveRef}
                value={deepObjective}
                onChange={(e) => setDeepObjective(e.target.value)}
                onKeyDown={handleDeepKeyDown}
                placeholder="e.g. I want to understand why revenue dropped in Q3 and identify the top contributing factors across product categories and regions..."
                disabled={isLoading || disabled}
                rows={3}
                className="deep-brief-textarea"
              />
            </div>

            <div className="deep-brief-extras">
              <div className="deep-brief-field">
                <label className="deep-brief-label">Scope <span className="deep-brief-optional">optional</span></label>
                <input
                  value={deepScope}
                  onChange={(e) => setDeepScope(e.target.value)}
                  onKeyDown={handleDeepKeyDown}
                  placeholder="e.g. Q1-Q4 2024, North America"
                  disabled={isLoading || disabled}
                  className="deep-brief-input"
                />
              </div>
              <div className="deep-brief-field">
                <label className="deep-brief-label">Key Metrics <span className="deep-brief-optional">optional</span></label>
                <input
                  value={deepMetrics}
                  onChange={(e) => setDeepMetrics(e.target.value)}
                  onKeyDown={handleDeepKeyDown}
                  placeholder="e.g. Revenue, AOV, Churn rate"
                  disabled={isLoading || disabled}
                  className="deep-brief-input"
                />
              </div>
            </div>
          </div>

          <div className="deep-brief-footer">
            <span className="deep-brief-hint">Ctrl+Enter to run</span>
            <button
              onClick={handleDeepSubmit}
              disabled={!canSendDeep}
              className={`deep-brief-run ${canSendDeep ? 'deep-brief-run--active' : ''}`}
            >
              {isLoading ? (
                <div className="deep-brief-run-loading">
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                  <span>Running...</span>
                </div>
              ) : (
                <>
                  <Play size={13} />
                  Run Deep Analysis
                </>
              )}
            </button>
          </div>
        </div>
      )}

      {/* Input bar */}
      <div className="chat-input-wrapper">
        <div className="chat-input-box">
          {/* Mode toggle */}
          <div className="chat-mode-toggle">
            <button
              onClick={() => setAnalysisMode('quick')}
              className={`chat-mode-btn ${analysisMode === 'quick' ? 'chat-mode-btn--active-quick' : ''}`}
            >
              <Zap size={12} />
              Quick Insight
            </button>
            <button
              onClick={() => setAnalysisMode('deep')}
              className={`chat-mode-btn ${analysisMode === 'deep' ? 'chat-mode-btn--active-deep' : ''}`}
            >
              <Brain size={12} />
              Deep Analysis
            </button>
          </div>

          {analysisMode === 'quick' && (
            <>
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={placeholderText}
                disabled={isLoading || disabled}
                rows={1}
                className="chat-textarea"
              />

              <div className="chat-send-wrap">
                <button
                  onClick={handleQuickSubmit}
                  disabled={!canSendQuick}
                  className={`chat-send-btn ${canSendQuick ? 'chat-send-btn--active' : ''}`}
                >
                  {isLoading ? (
                    <div style={{ display: 'flex', gap: 3 }}>
                      <span className="typing-dot" style={{ width: 4, height: 4 }} />
                      <span className="typing-dot" style={{ width: 4, height: 4 }} />
                      <span className="typing-dot" style={{ width: 4, height: 4 }} />
                    </div>
                  ) : (
                    <ArrowUp size={16} strokeWidth={2.5} />
                  )}
                </button>
              </div>
            </>
          )}
        </div>

        <p className="chat-input-footer">
          AI-powered data analysis &middot; DataLens Analytics
        </p>
      </div>
    </div>
  );
}
