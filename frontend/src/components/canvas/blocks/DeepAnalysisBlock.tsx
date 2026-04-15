import { useState } from 'react';
import { ChevronDown, ChevronRight, Lightbulb, Target } from 'lucide-react';
import Markdown from 'react-markdown';
import type { DeepAnalysisBlockData } from '../../../types/canvas';

interface DeepAnalysisBlockProps {
  data: DeepAnalysisBlockData;
}

const SIG_COLORS: Record<string, { border: string; bg: string; badgeBg: string; badgeColor: string }> = {
  high:   { border: '#0066cc', bg: 'rgba(0,102,204,0.06)', badgeBg: '#e0f0ff', badgeColor: '#0052a3' },
  medium: { border: '#f59e0b', bg: 'rgba(245,158,11,0.06)', badgeBg: '#fef3c7', badgeColor: '#b45309' },
  low:    { border: '#94a3b8', bg: 'rgba(148,163,184,0.06)', badgeBg: '#f1f5f9', badgeColor: '#64748b' },
};

export default function DeepAnalysisBlock({ data }: DeepAnalysisBlockProps) {
  const [expandedSections, setExpandedSections] = useState<Set<number>>(new Set([0]));

  const toggleSection = (i: number) => {
    setExpandedSections((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  };

  return (
    <div className="da-wrap">
      {/* Executive Summary */}
      <div className="da-summary">
        <h4 className="da-summary-title">Executive Summary</h4>
        <div className="da-prose">
          <Markdown>{data.executiveSummary}</Markdown>
        </div>
      </div>

      {/* Analysis Sections */}
      {data.sections.map((section, i) => {
        const colors = SIG_COLORS[section.significance] || SIG_COLORS.low;
        const isExpanded = expandedSections.has(i);

        return (
          <div
            key={i}
            className="da-section"
            style={{ borderLeftColor: colors.border, background: colors.bg }}
          >
            <button onClick={() => toggleSection(i)} className="da-section-toggle">
              <div className="da-section-left">
                {isExpanded
                  ? <ChevronDown size={14} color="#9ca3af" />
                  : <ChevronRight size={14} color="#9ca3af" />}
                <span className="da-section-heading">{section.heading}</span>
              </div>
              <span
                className="da-section-badge"
                style={{ background: colors.badgeBg, color: colors.badgeColor }}
              >
                {section.significance}
              </span>
            </button>
            {isExpanded && (
              <div className="da-section-content">
                <div className="da-prose">
                  <Markdown>{section.content}</Markdown>
                </div>
              </div>
            )}
          </div>
        );
      })}

      {/* Recommendations */}
      {data.recommendations.length > 0 && (
        <div className="da-recs">
          <div className="da-recs-header">
            <Target size={16} color="#00b894" />
            <h4>Recommendations</h4>
          </div>
          <div className="da-recs-list">
            {data.recommendations.map((rec, i) => (
              <div key={i} className="da-rec-item">
                <Lightbulb size={14} color="#00b894" />
                <p>{rec}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Methodology */}
      {data.methodology && (
        <div className="da-methodology">{data.methodology}</div>
      )}
    </div>
  );
}
