export type MessageRole = 'user' | 'assistant';

export interface AgentStep {
  type: 'thinking' | 'plan' | 'sub_query_start' | 'sub_query_result' | 'api_call_start' | 'api_call_result' | 'consolidating' | 'chart_selected' | 'clarification' | 'error';
  content: string;
  sql?: string;
  data?: Record<string, unknown>;
  timestamp: number;
  completed: boolean;
}

export interface KeyFinding {
  headline: string;
  detail: string;
  significance: 'high' | 'medium' | 'low';
}

export interface InsightSummary {
  title: string;
  narrative: string;
  key_findings: KeyFinding[];
  follow_up_questions: string[];
}

export type ChartType =
  | 'bar' | 'grouped_bar' | 'line' | 'multi_line' | 'pie' | 'scatter'
  | 'stacked_bar' | 'area' | 'kpi' | 'table'
  | 'horizontal_bar' | 'treemap' | 'funnel' | 'radar' | 'radial_bar'
  | 'heatmap' | 'waterfall' | 'gauge';

export interface ChartRecommendation {
  chart_type: ChartType;
  title: string;
  x_axis: string | null;
  y_axis: string | string[] | null;
  color_by: string | null;
  data: Record<string, unknown>[];
  reasoning: string;
  config?: Record<string, unknown>;
}

export interface TableData {
  title: string;
  columns: string[];
  data: Record<string, unknown>[];
}

export interface ExecutionMetadata {
  total_duration_ms: number;
  sub_query_count: number;
  total_rows: number;
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  // Anthropic prompt-cache breakdown (0 for non-Anthropic providers)
  cache_read_tokens?: number;
  cache_creation_tokens?: number;
  model_name?: string;
  estimated_cost_usd?: number;
  // `cached` = in-app ResponseCache hit (whole LLM pipeline skipped).
  // Prompt-cache reuse is reflected in cache_read_tokens, not here.
  cached?: boolean;
  // Per-step latency breakdown in ms (e.g. {"agent_loop": 4321.0}).
  step_timings?: Record<string, number>;
}

export interface InsightResult {
  summary: InsightSummary;
  charts: ChartRecommendation[];
  tables: TableData[];
  execution_metadata: ExecutionMetadata;
}

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: number;
  steps: AgentStep[];
  insightResult?: InsightResult;
  isStreaming?: boolean;
  streamingNarrative?: string;
  analysisMode?: 'quick' | 'deep';
  feedback?: 'positive' | 'negative' | null;
}

export interface ChatSession {
  id: string;
  title: string;
  messages: ChatMessage[];
  createdAt: number;
  workspaceId?: string;
}
