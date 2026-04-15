import { useMemo, useCallback, useRef, useState, useEffect } from 'react';
import { ResponsiveGridLayout, verticalCompactor } from 'react-grid-layout';
import 'react-grid-layout/css/styles.css';
import { Trash2, RefreshCw, X } from 'lucide-react';
import { useCanvasStore } from '../../store/canvasStore';
import CanvasBlockComponent from './CanvasBlock';
import ChartBlock from './blocks/ChartBlock';
import TableBlock from './blocks/TableBlock';
import KpiBlock from './blocks/KpiBlock';
import NarrativeBlock from './blocks/NarrativeBlock';
import DeepAnalysisBlock from './blocks/DeepAnalysisBlock';
import EmptyCanvas from './EmptyCanvas';
import type { CanvasBlock } from '../../types/canvas';
import type { ChartBlockData, TableBlockData, KpiBlockData, NarrativeBlockData, DeepAnalysisBlockData } from '../../types/canvas';

const EMPTY_BLOCKS: CanvasBlock[] = [];

interface CanvasTab {
  id: string;
  label: string;
  blockCount: number;
  isDeep: boolean;
}

interface CanvasPanelProps {
  workspaceId: string;
  activeSessionId?: string | null;
  onFollowUp?: (question: string) => void;
  canvasTitle?: string;
  onRefreshCanvas?: () => void;
  isRefreshing?: boolean;
}

function renderBlockContent(block: CanvasBlock, onFollowUp?: (question: string) => void) {
  switch (block.type) {
    case 'chart':
      return <ChartBlock data={block.data as ChartBlockData} />;
    case 'table':
      return <TableBlock data={block.data as TableBlockData} />;
    case 'kpi':
      return <KpiBlock data={block.data as KpiBlockData} />;
    case 'narrative':
      return <NarrativeBlock data={block.data as NarrativeBlockData} onFollowUp={onFollowUp} />;
    case 'deep_analysis':
      return <DeepAnalysisBlock data={block.data as DeepAnalysisBlockData} />;
    default:
      return null;
  }
}

export default function CanvasPanel({ workspaceId, activeSessionId, onFollowUp, canvasTitle, onRefreshCanvas, isRefreshing }: CanvasPanelProps) {
  const allBlocks = useCanvasStore((s) => s.blocks[workspaceId] || EMPTY_BLOCKS);

  // Filter blocks to only show ones belonging to the active session
  const blocks = useMemo(() => {
    if (!activeSessionId) return EMPTY_BLOCKS;
    return allBlocks.filter((b) => b.sessionId === activeSessionId || !b.sessionId);
  }, [allBlocks, activeSessionId]);
  const highlightedBlockId = useCanvasStore((s) => s.highlightedBlockId);
  const removeBlock = useCanvasStore((s) => s.removeBlock);
  const clearCanvas = useCanvasStore((s) => s.clearCanvas);
  const updateAllLayouts = useCanvasStore((s) => s.updateAllLayouts);
  const activeTabId = useCanvasStore((s) => s.activeTab[workspaceId] || 'quick');
  const setActiveTab = useCanvasStore((s) => s.setActiveTab);
  const removeDeepTab = useCanvasStore((s) => s.removeDeepTab);
  const containerRef = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState(800);

  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setContainerWidth(entry.contentRect.width - 32);
      }
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  // Derive tabs from blocks
  const tabs = useMemo((): CanvasTab[] => {
    const result: CanvasTab[] = [];

    // Quick Insights tab — always present
    const quickBlocks = blocks.filter((b) => b.analysisMode !== 'deep');
    result.push({
      id: 'quick',
      label: 'Quick Insights',
      blockCount: quickBlocks.length,
      isDeep: false,
    });

    // Deep insight tabs — one per unique sourceMessageId where analysisMode === 'deep'
    const deepGroups = new Map<string, { query: string; count: number }>();
    for (const block of blocks) {
      if (block.analysisMode === 'deep') {
        const existing = deepGroups.get(block.sourceMessageId);
        if (existing) {
          existing.count++;
        } else {
          deepGroups.set(block.sourceMessageId, {
            query: block.sourceQuery || 'Deep Analysis',
            count: 1,
          });
        }
      }
    }

    for (const [msgId, info] of deepGroups) {
      result.push({
        id: msgId,
        label: info.query.length > 40 ? info.query.slice(0, 40) + '...' : info.query,
        blockCount: info.count,
        isDeep: true,
      });
    }

    return result;
  }, [blocks]);

  // Filter blocks for active tab
  const filteredBlocks = useMemo(() => {
    if (activeTabId === 'quick') {
      return blocks.filter((b) => b.analysisMode !== 'deep');
    }
    return blocks.filter(
      (b) => b.analysisMode === 'deep' && b.sourceMessageId === activeTabId
    );
  }, [blocks, activeTabId]);

  const layouts = useMemo(() => {
    return {
      lg: filteredBlocks.map((b) => ({
        i: b.id,
        x: b.layout.x,
        y: b.layout.y,
        w: b.layout.w,
        h: b.layout.h,
        minW: 3,
        minH: 2,
      })),
    };
  }, [filteredBlocks]);

  const handleLayoutChange = useCallback(
    (layout: ReadonlyArray<{ readonly i: string; readonly x: number; readonly y: number; readonly w: number; readonly h: number }>, _layouts: unknown) => {
      updateAllLayouts(workspaceId, layout.map((l) => ({ i: l.i, x: l.x, y: l.y, w: l.w, h: l.h })));
    },
    [workspaceId, updateAllLayouts]
  );

  // If activeTabId points to a deep tab that no longer exists, fall back to 'quick'
  useEffect(() => {
    if (activeTabId !== 'quick' && !tabs.some((t) => t.id === activeTabId)) {
      setActiveTab(workspaceId, 'quick');
    }
  }, [activeTabId, tabs, workspaceId, setActiveTab]);

  // No blocks at all — show empty canvas (no tabs)
  if (blocks.length === 0) {
    return (
      <div className="wv-canvas-area">
        <EmptyCanvas />
      </div>
    );
  }

  const hasDeepTabs = tabs.some((t) => t.isDeep);

  return (
    <div ref={containerRef} style={{ flex: 1, minWidth: 0, height: '100%', background: '#f5f6f8', overflowY: 'auto' }}>
      {/* Canvas header */}
      <div className="cv-header">
        <div className="cv-header-left">
          <h2 className="cv-title">{canvasTitle || 'Canvas'}</h2>
          <span className="cv-block-count">{filteredBlocks.length} block{filteredBlocks.length !== 1 ? 's' : ''}</span>
        </div>
        <div className="cv-header-right">
          {onRefreshCanvas && (
            <button
              onClick={onRefreshCanvas}
              disabled={isRefreshing}
              className={`cv-refresh-btn ${isRefreshing ? 'cv-refresh-btn--loading' : ''}`}
            >
              <RefreshCw size={13} className={isRefreshing ? 'animate-spin' : ''} />
              {isRefreshing ? 'Refreshing...' : 'Refresh'}
            </button>
          )}
          <button onClick={() => clearCanvas(workspaceId)} className="cv-clear-btn">
            <Trash2 size={13} />
            Clear
          </button>
        </div>
      </div>

      {/* Tab bar — show when there are deep tabs or quick insights */}
      {(hasDeepTabs || tabs[0].blockCount > 0) && (
        <div className="cv-tab-bar">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              className={`cv-tab ${activeTabId === tab.id ? 'cv-tab--active' : ''}`}
              onClick={() => setActiveTab(workspaceId, tab.id)}
            >
              {tab.isDeep && <span className="cv-tab-dot" />}
              <span className="cv-tab-label">{tab.label}</span>
              <span className="cv-tab-count">{tab.blockCount}</span>
              {tab.isDeep && (
                <button
                  className="cv-tab-close"
                  onClick={(e) => {
                    e.stopPropagation();
                    removeDeepTab(workspaceId, tab.id);
                  }}
                  title="Remove this deep analysis"
                >
                  <X size={10} />
                </button>
              )}
            </button>
          ))}
        </div>
      )}

      {/* Grid or per-tab empty state */}
      {filteredBlocks.length === 0 ? (
        <div className="cv-tab-empty">
          <p>
            {activeTabId === 'quick'
              ? 'No quick insights yet. Ask a question in Quick mode and push results to canvas.'
              : 'This deep analysis tab is empty.'}
          </p>
        </div>
      ) : (
        <div style={{ padding: '0 16px 16px' }}>
          <ResponsiveGridLayout
            className="layout"
            layouts={layouts}
            breakpoints={{ lg: 0 }}
            cols={{ lg: 12 }}
            rowHeight={60}
            width={containerWidth}
            onLayoutChange={handleLayoutChange}
            compactor={verticalCompactor}
            margin={[12, 12] as [number, number]}
          >
            {filteredBlocks.map((block) => (
              <div key={block.id}>
                <CanvasBlockComponent
                  block={block}
                  workspaceId={workspaceId}
                  isHighlighted={highlightedBlockId === block.id}
                  onRemove={() => removeBlock(workspaceId, block.id)}
                >
                  {renderBlockContent(block, onFollowUp)}
                </CanvasBlockComponent>
              </div>
            ))}
          </ResponsiveGridLayout>
        </div>
      )}
    </div>
  );
}
