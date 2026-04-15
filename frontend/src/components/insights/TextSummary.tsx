import Markdown from 'react-markdown';
import { Lightbulb, Sparkles, ArrowRight } from 'lucide-react';
import type { InsightSummary } from '../../types/chat';

interface TextSummaryProps {
  summary: InsightSummary;
  onFollowUp?: (question: string) => void;
  isConversational?: boolean;
}

const SIG_COLORS: Record<string, { border: string; bg: string; badgeBg: string; badgeColor: string }> = {
  high:   { border: '#0066cc', bg: 'rgba(0,102,204,0.06)', badgeBg: '#e0f0ff', badgeColor: '#0052a3' },
  medium: { border: '#f59e0b', bg: 'rgba(245,158,11,0.06)', badgeBg: '#fef3c7', badgeColor: '#b45309' },
  low:    { border: '#94a3b8', bg: 'rgba(148,163,184,0.06)', badgeBg: '#f1f5f9', badgeColor: '#64748b' },
};

export default function TextSummary({ summary, onFollowUp, isConversational }: TextSummaryProps) {
  // Auto-detect conversational mode when there's no analysis metadata
  const isWelcome = isConversational ?? (
    summary.key_findings?.length > 0 &&
    summary.follow_up_questions?.length > 0 &&
    !summary.title?.toLowerCase().includes('analysis')
  );

  return (
    <div className="txs-wrap">
      {/* Title */}
      {summary.title && <h3 className="txs-title">{summary.title}</h3>}

      {/* Narrative */}
      <div className="txs-narrative">
        <Markdown>{summary.narrative}</Markdown>
      </div>

      {/* Key Findings / Insight Topics */}
      {summary.key_findings && summary.key_findings.length > 0 && (
        <div className="txs-findings">
          <div className="txs-findings-header">
            {isWelcome
              ? <><Sparkles size={16} color="#0066cc" /><h4>What I Can Help With</h4></>
              : <><Lightbulb size={16} color="#f59e0b" /><h4>Key Findings</h4></>
            }
          </div>
          <div className="txs-findings-list">
            {summary.key_findings.map((finding, i) => {
              const colors = SIG_COLORS[finding.significance] || SIG_COLORS.low;
              return (
                <div
                  key={i}
                  className="txs-finding"
                  style={{
                    borderLeftColor: colors.border,
                    background: colors.bg,
                    animationDelay: `${i * 60}ms`,
                  }}
                >
                  <div className="txs-finding-body">
                    <div>
                      <p className="txs-finding-headline">{finding.headline}</p>
                      {finding.detail && (
                        <p className="txs-finding-detail">{finding.detail}</p>
                      )}
                    </div>
                    {!isWelcome && (
                      <span
                        className="txs-finding-badge"
                        style={{ background: colors.badgeBg, color: colors.badgeColor }}
                      >
                        {finding.significance}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Follow-up Questions */}
      {summary.follow_up_questions && summary.follow_up_questions.length > 0 && onFollowUp && (
        <div className="txs-followup">
          <h4 className="txs-followup-header">
            {isWelcome ? 'Try asking' : 'Explore further'}
          </h4>
          <div className="txs-followup-list">
            {summary.follow_up_questions.map((q, i) => (
              <button key={i} onClick={() => onFollowUp(q)} className="txs-followup-btn">
                <ArrowRight size={12} />
                {q}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
