import { useState, useRef, useEffect, cloneElement, isValidElement } from 'react';
import { X, Maximize2, GripVertical, BarChart3, Table2, Hash, FileText, Brain, Sparkles, ArrowLeftRight } from 'lucide-react';
import type { CanvasBlock as CanvasBlockType, ChartBlockData } from '../../types/canvas';
import type { ChartType } from '../../types/chat';
import { useCanvasStore } from '../../store/canvasStore';

function renderBoldText(text: string) {
  const parts = text.split(/\*\*(.+?)\*\*/g);
  return parts.map((part, i) =>
    i % 2 === 1 ? <strong key={i}>{part}</strong> : part
  );
}

interface CanvasBlockProps {
  block: CanvasBlockType;
  workspaceId: string;
  isHighlighted: boolean;
  onRemove: () => void;
  children: React.ReactNode;
}

const TYPE_CONFIG: Record<string, { icon: typeof BarChart3; label: string; color: string }> = {
  chart: { icon: BarChart3, label: 'Chart', color: '#6366f1' },
  table: { icon: Table2, label: 'Table', color: '#06b6d4' },
  kpi: { icon: Hash, label: 'KPI', color: '#f97316' },
  narrative: { icon: FileText, label: 'Summary', color: '#10b981' },
  deep_analysis: { icon: Brain, label: 'Analysis', color: '#8b5cf6' },
};

const SIGNIFICANCE_COLORS: Record<string, string> = {
  high: '#0066cc',
  medium: '#f59e0b',
  low: '#6b7280',
};

// Compatible chart type groups — charts within a group can convert to each other
const CHART_TYPE_LABELS: Record<ChartType, string> = {
  bar: 'Bar', grouped_bar: 'Grouped Bar', horizontal_bar: 'Horizontal Bar',
  stacked_bar: 'Stacked Bar', line: 'Line', multi_line: 'Multi-Line',
  area: 'Area', scatter: 'Scatter', pie: 'Pie', treemap: 'Treemap',
  funnel: 'Funnel', radar: 'Radar', radial_bar: 'Radial Bar', gauge: 'Gauge',
  heatmap: 'Heatmap', waterfall: 'Waterfall', kpi: 'KPI', table: 'Table',
};

const CONVERTIBLE_TYPES: ChartType[] = [
  'bar', 'grouped_bar', 'horizontal_bar', 'stacked_bar',
  'line', 'multi_line', 'area', 'pie', 'scatter',
  'treemap', 'funnel', 'radar', 'radial_bar',
];

export default function CanvasBlock({ block, workspaceId, isHighlighted, onRemove, children }: CanvasBlockProps) {
  const config = TYPE_CONFIG[block.type] || TYPE_CONFIG.chart;
  const Icon = config.icon;
  const [showInfo, setShowInfo] = useState(false);
  const [showChartMenu, setShowChartMenu] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);
  const chartMenuRef = useRef<HTMLDivElement>(null);

  const isChart = block.type === 'chart';
  const currentChartType = isChart ? (block.data as ChartBlockData).chart.chart_type : null;
  const [showData, setShowData] = useState(false);

  // Close popovers on outside click
  useEffect(() => {
    if (!showInfo && !showChartMenu) return;
    function handleClick(e: MouseEvent) {
      if (showInfo && popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setShowInfo(false);
      }
      if (showChartMenu && chartMenuRef.current && !chartMenuRef.current.contains(e.target as Node)) {
        setShowChartMenu(false);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [showInfo, showChartMenu]);

  const hasMeta = block.insightMeta && (block.insightMeta.narrative || block.insightMeta.keyFindings.length > 0);

  const handleConvertChart = (newType: ChartType) => {
    if (!isChart) return;
    const chartData = block.data as ChartBlockData;
    const updatedChart = { ...chartData.chart, chart_type: newType };
    const updatedBlock = { ...block, data: { chart: updatedChart } };

    // Update block in store
    const store = useCanvasStore.getState();
    const blocks = store.blocks[workspaceId] || [];
    const updatedBlocks = blocks.map((b) => (b.id === block.id ? updatedBlock : b));
    useCanvasStore.setState({
      blocks: { ...store.blocks, [workspaceId]: updatedBlocks },
    });

    setShowChartMenu(false);
  };

  return (
    <div className={`cb-wrap ${isHighlighted ? 'cb-wrap--highlight' : ''} ${showInfo ? 'cb-wrap--popover-open' : ''}`}>
      {/* Block header - drag handle */}
      <div className="cb-header drag-handle">
        <div className="cb-header-left">
          <GripVertical size={14} color="#c4c9d2" />
          <Icon size={14} color={config.color} />
          <span className="cb-title">{block.title}</span>
          <span className="cb-badge" style={{ color: config.color, background: `${config.color}12` }}>
            {config.label}
          </span>
        </div>
        <div className="cb-actions">
          {/* Data / Chart toggle */}
          {isChart && (
            <button
              className={`cb-action-btn ${showData ? 'cb-action-btn--active' : ''}`}
              onClick={() => setShowData(!showData)}
              onMouseDown={(e) => e.stopPropagation()}
              title={showData ? 'View Chart' : 'View Data'}
            >
              {showData ? <BarChart3 size={12} /> : <Table2 size={12} />}
            </button>
          )}
          {/* Chart type converter button */}
          {isChart && (
            <button
              className={`cb-action-btn cb-convert-btn ${showChartMenu ? 'cb-convert-btn--active' : ''}`}
              onClick={() => { setShowChartMenu(!showChartMenu); setShowInfo(false); }}
              onMouseDown={(e) => e.stopPropagation()}
              title="Convert chart type"
            >
              <ArrowLeftRight size={12} />
            </button>
          )}
          {hasMeta && (
            <button
              className={`cb-action-btn cb-info-btn ${showInfo ? 'cb-info-btn--active' : ''}`}
              onClick={() => { setShowInfo(!showInfo); setShowChartMenu(false); }}
              onMouseDown={(e) => e.stopPropagation()}
              title="View insight summary"
            >
              <Sparkles size={12} />
            </button>
          )}
          <button className="cb-action-btn" onMouseDown={(e) => e.stopPropagation()}>
            <Maximize2 size={12} color="#c4c9d2" />
          </button>
          <button className="cb-action-btn cb-action-btn--close" onClick={onRemove} onMouseDown={(e) => e.stopPropagation()}>
            <X size={12} color="#c4c9d2" />
          </button>
        </div>
      </div>

      {/* Chart type conversion menu */}
      {showChartMenu && isChart && (
        <div className="cb-chart-menu" ref={chartMenuRef} onMouseDown={(e) => e.stopPropagation()}>
          <div className="cb-chart-menu-header">Convert to</div>
          <div className="cb-chart-menu-grid">
            {CONVERTIBLE_TYPES.map((type) => (
              <button
                key={type}
                className={`cb-chart-menu-item ${type === currentChartType ? 'cb-chart-menu-item--active' : ''}`}
                onClick={() => handleConvertChart(type)}
                disabled={type === currentChartType}
              >
                {CHART_TYPE_LABELS[type]}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Insight info popover */}
      {showInfo && block.insightMeta && (
        <div className="cb-info-popover" ref={popoverRef} onMouseDown={(e) => e.stopPropagation()}>
          <div className="cb-info-popover-header">
            <span>Insight Summary</span>
            <button className="cb-info-popover-close" onClick={() => setShowInfo(false)}>
              <X size={12} />
            </button>
          </div>
          <div className="cb-info-popover-body">
            <p className="cb-info-narrative">{renderBoldText(block.insightMeta.narrative)}</p>
            {block.insightMeta.keyFindings.length > 0 && (
              <div className="cb-info-findings">
                <span className="cb-info-findings-label">Key Findings</span>
                {block.insightMeta.keyFindings.map((f, i) => (
                  <div key={i} className="cb-info-finding">
                    <span
                      className="cb-info-finding-dot"
                      style={{ background: SIGNIFICANCE_COLORS[f.significance] || '#6b7280' }}
                    />
                    <div>
                      <span className="cb-info-finding-headline">{f.headline}</span>
                      <span className="cb-info-finding-detail">{f.detail}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Block content */}
      <div className="cb-content">
        {isChart && isValidElement(children)
          ? cloneElement(children as React.ReactElement<{ showData?: boolean }>, { showData })
          : children}
      </div>
    </div>
  );
}
