import type { ChartRecommendation, TableData, InsightSummary, KeyFinding } from './chat';

export type CanvasBlockType = 'chart' | 'table' | 'kpi' | 'narrative' | 'deep_analysis';

export interface CanvasBlockLayout {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface BlockInsightMeta {
  narrative: string;
  keyFindings: KeyFinding[];
}

export interface ChartBlockData {
  chart: ChartRecommendation;
}

export interface TableBlockData {
  table: TableData;
}

export interface KpiBlockData {
  metrics: Array<{ label: string; value: number | string }>;
}

export interface NarrativeBlockData {
  summary: InsightSummary;
}

export interface DeepAnalysisSection {
  heading: string;
  content: string;
  charts?: ChartRecommendation[];
  significance: 'high' | 'medium' | 'low';
}

export interface DeepAnalysisBlockData {
  title: string;
  executiveSummary: string;
  sections: DeepAnalysisSection[];
  recommendations: string[];
  methodology: string;
}

export interface CanvasBlock {
  id: string;
  type: CanvasBlockType;
  title: string;
  sourceMessageId: string;
  sessionId?: string;                 // chat session that produced this block
  createdAt: number;
  layout: CanvasBlockLayout;
  data: ChartBlockData | TableBlockData | KpiBlockData | NarrativeBlockData | DeepAnalysisBlockData;
  insightMeta?: BlockInsightMeta;
  analysisMode?: 'quick' | 'deep';   // undefined treated as 'quick' for backward compat
  sourceQuery?: string;               // user's original question (for deep tab label)
}

/** Tab identifier: 'quick' for the Quick Insights tab, or a sourceMessageId for a deep tab */
export type CanvasTabId = 'quick' | string;
