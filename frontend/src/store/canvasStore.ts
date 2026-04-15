import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { CanvasBlock, CanvasBlockLayout, BlockInsightMeta, CanvasTabId } from '../types/canvas';
import type { InsightResult } from '../types/chat';
import { fetchCanvasState, saveCanvasState } from '../services/api';

const EMPTY_BLOCKS: CanvasBlock[] = [];

function generateId(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return Date.now().toString(36) + Math.random().toString(36).slice(2);
  }
}

// ── Debounce helper ─────────────────────────────────────────────────
const _canvasTimers: Record<string, ReturnType<typeof setTimeout>> = {};

function debouncedSaveCanvas(workspaceId: string) {
  if (_canvasTimers[workspaceId]) clearTimeout(_canvasTimers[workspaceId]);
  _canvasTimers[workspaceId] = setTimeout(() => {
    const state = useCanvasStore.getState();
    const blocks = state.blocks[workspaceId] || [];
    saveCanvasState(workspaceId, blocks as unknown as Record<string, unknown>[]).catch(() => {});
    delete _canvasTimers[workspaceId];
  }, 2000);
}

interface CanvasState {
  blocks: Record<string, CanvasBlock[]>;
  highlightedBlockId: string | null;
  activeTab: Record<string, CanvasTabId>;
  _canvasLoaded: Record<string, boolean>;

  addBlocksFromInsight: (workspaceId: string, insight: InsightResult, messageId: string, opts?: { skipNarrative?: boolean; analysisMode?: 'quick' | 'deep'; sourceQuery?: string; sessionId?: string }) => void;
  removeBlock: (workspaceId: string, blockId: string) => void;
  updateBlockLayout: (workspaceId: string, blockId: string, layout: CanvasBlockLayout) => void;
  updateAllLayouts: (workspaceId: string, layouts: Array<{ i: string } & CanvasBlockLayout>) => void;
  highlightBlock: (blockId: string | null) => void;
  clearCanvas: (workspaceId: string) => void;
  replaceBlocksByMessageId: (workspaceId: string, oldMessageId: string, newBlocks: CanvasBlock[]) => void;
  getBlocks: (workspaceId: string) => CanvasBlock[];
  setActiveTab: (workspaceId: string, tabId: CanvasTabId) => void;
  removeDeepTab: (workspaceId: string, sourceMessageId: string) => void;

  // Persistence sync
  loadCanvasFromBackend: (workspaceId: string) => Promise<void>;
}

export const useCanvasStore = create<CanvasState>()(
  persist(
    (set, get) => ({
      blocks: {},
      highlightedBlockId: null,
      activeTab: {},
      _canvasLoaded: {},

      addBlocksFromInsight: (workspaceId: string, insight: InsightResult, messageId: string, opts?: { skipNarrative?: boolean; analysisMode?: 'quick' | 'deep'; sourceQuery?: string; sessionId?: string }) => {
        const existingBlocks = get().blocks[workspaceId] || [];

        const relevantBlocks = opts?.analysisMode === 'deep'
          ? existingBlocks.filter((b) => b.sourceMessageId === messageId)
          : existingBlocks.filter((b) => b.analysisMode !== 'deep');
        const maxY = relevantBlocks.reduce((max, b) => Math.max(max, b.layout.y + b.layout.h), 0);

        const newBlocks: CanvasBlock[] = [];
        let currentY = maxY;

        const meta: BlockInsightMeta | undefined = insight.summary
          ? { narrative: insight.summary.narrative, keyFindings: insight.summary.key_findings }
          : undefined;

        const modeFields = {
          analysisMode: opts?.analysisMode,
          sourceQuery: opts?.sourceQuery,
          sessionId: opts?.sessionId,
        };

        if (insight.summary && !opts?.skipNarrative) {
          newBlocks.push({
            id: generateId(),
            type: 'narrative',
            title: insight.summary.title,
            sourceMessageId: messageId,
            createdAt: Date.now(),
            layout: { x: 0, y: currentY, w: 12, h: 4 },
            data: { summary: insight.summary },
            insightMeta: meta,
            ...modeFields,
          });
          currentY += 4;
        }

        if (insight.charts) {
          // Separate KPIs from real charts
          const kpiCharts = insight.charts.filter((c) => c.chart_type === 'kpi');
          const realCharts = insight.charts.filter((c) => c.chart_type !== 'kpi' && c.chart_type !== 'table');

          // KPIs first — full width
          kpiCharts.forEach((chart) => {
            const keys = chart.data.length > 0 ? Object.keys(chart.data[0]) : [];
            const labelKey = keys.find((k) => typeof chart.data[0][k] === 'string') || keys[0];
            const valueKey = keys.find((k) => typeof chart.data[0][k] === 'number') || keys[1];
            newBlocks.push({
              id: generateId(),
              type: 'kpi',
              title: chart.title,
              sourceMessageId: messageId,
              createdAt: Date.now(),
              layout: { x: 0, y: currentY, w: 12, h: 3 },
              data: {
                metrics: chart.data.map((item) => ({
                  label: String(item[labelKey] ?? ''),
                  value: (item[valueKey] as number | string) ?? '',
                })),
              },
              insightMeta: meta,
              ...modeFields,
            });
            currentY += 3;
          });

          // Smart chart layout based on count:
          // 1 chart  → full width  (w=12, h=6)
          // 2 charts → side by side (w=6, h=5)
          // 3 charts → 3 per row   (w=4, h=5)
          // 4 charts → 2x2 grid    (w=6, h=5)
          // 5+ charts → 3 per row  (w=4, h=5)
          const chartCount = realCharts.length;
          let colsPerRow: number;
          let chartW: number;
          let chartH: number;

          if (chartCount === 1) {
            colsPerRow = 1; chartW = 12; chartH = 6;
          } else if (chartCount === 2 || chartCount === 4) {
            colsPerRow = 2; chartW = 6; chartH = 5;
          } else {
            colsPerRow = 3; chartW = 4; chartH = 5;
          }

          let chartCol = 0;
          realCharts.forEach((chart) => {
            newBlocks.push({
              id: generateId(),
              type: 'chart',
              title: chart.title,
              sourceMessageId: messageId,
              createdAt: Date.now(),
              layout: { x: (chartCol % colsPerRow) * chartW, y: currentY, w: chartW, h: chartH },
              data: { chart },
              insightMeta: meta,
              ...modeFields,
            });
            chartCol++;
            if (chartCol % colsPerRow === 0) { currentY += chartH; }
          });
          // Flush any remaining partial chart row
          if (chartCol % colsPerRow !== 0) { currentY += chartH; }
        }

        if (insight.tables) {
          insight.tables.forEach((table) => {
            newBlocks.push({
              id: generateId(),
              type: 'table',
              title: table.title,
              sourceMessageId: messageId,
              createdAt: Date.now(),
              layout: { x: 0, y: currentY, w: 12, h: 5 },
              data: { table },
              insightMeta: meta,
              ...modeFields,
            });
            currentY += 5;
          });
        }

        set((state) => ({
          blocks: {
            ...state.blocks,
            [workspaceId]: [...existingBlocks, ...newBlocks],
          },
          ...(opts?.analysisMode === 'deep' ? {
            activeTab: { ...state.activeTab, [workspaceId]: messageId },
          } : {}),
        }));

        // Debounced save to backend
        if (!workspaceId.startsWith('__refresh_')) {
          debouncedSaveCanvas(workspaceId);
        }
      },

      removeBlock: (workspaceId: string, blockId: string) => {
        set((state) => ({
          blocks: {
            ...state.blocks,
            [workspaceId]: (state.blocks[workspaceId] || []).filter((b) => b.id !== blockId),
          },
        }));
        debouncedSaveCanvas(workspaceId);
      },

      updateBlockLayout: (workspaceId: string, blockId: string, layout: CanvasBlockLayout) => {
        set((state) => ({
          blocks: {
            ...state.blocks,
            [workspaceId]: (state.blocks[workspaceId] || []).map((b) =>
              b.id === blockId ? { ...b, layout } : b
            ),
          },
        }));
        debouncedSaveCanvas(workspaceId);
      },

      updateAllLayouts: (workspaceId: string, layouts: Array<{ i: string } & CanvasBlockLayout>) => {
        set((state) => ({
          blocks: {
            ...state.blocks,
            [workspaceId]: (state.blocks[workspaceId] || []).map((block) => {
              const newLayout = layouts.find((l) => l.i === block.id);
              if (newLayout) {
                return { ...block, layout: { x: newLayout.x, y: newLayout.y, w: newLayout.w, h: newLayout.h } };
              }
              return block;
            }),
          },
        }));
        debouncedSaveCanvas(workspaceId);
      },

      highlightBlock: (blockId: string | null) => {
        set({ highlightedBlockId: blockId });
        if (blockId) {
          setTimeout(() => set({ highlightedBlockId: null }), 2000);
        }
      },

      clearCanvas: (workspaceId: string) => {
        set((state) => ({
          blocks: {
            ...state.blocks,
            [workspaceId]: [],
          },
          activeTab: { ...state.activeTab, [workspaceId]: 'quick' },
        }));
        debouncedSaveCanvas(workspaceId);
      },

      replaceBlocksByMessageId: (workspaceId: string, oldMessageId: string, newBlocks: CanvasBlock[]) => {
        set((state) => {
          const existing = state.blocks[workspaceId] || [];
          const firstOldIndex = existing.findIndex((b) => b.sourceMessageId === oldMessageId);
          const filtered = existing.filter((b) => b.sourceMessageId !== oldMessageId);
          const insertAt = firstOldIndex >= 0 ? Math.min(firstOldIndex, filtered.length) : filtered.length;
          return {
            blocks: {
              ...state.blocks,
              [workspaceId]: [
                ...filtered.slice(0, insertAt),
                ...newBlocks,
                ...filtered.slice(insertAt),
              ],
            },
          };
        });
        debouncedSaveCanvas(workspaceId);
      },

      getBlocks: (workspaceId: string) => {
        return get().blocks[workspaceId] || EMPTY_BLOCKS;
      },

      setActiveTab: (workspaceId: string, tabId: CanvasTabId) => {
        set((state) => ({
          activeTab: { ...state.activeTab, [workspaceId]: tabId },
        }));
      },

      removeDeepTab: (workspaceId: string, sourceMessageId: string) => {
        set((state) => {
          const filtered = (state.blocks[workspaceId] || []).filter(
            (b) => b.sourceMessageId !== sourceMessageId
          );
          const currentTab = state.activeTab[workspaceId];
          return {
            blocks: { ...state.blocks, [workspaceId]: filtered },
            activeTab: {
              ...state.activeTab,
              [workspaceId]: currentTab === sourceMessageId ? 'quick' : currentTab,
            },
          };
        });
        debouncedSaveCanvas(workspaceId);
      },

      // ── Persistence sync ──────────────────────────────────────────

      loadCanvasFromBackend: async (workspaceId: string) => {
        if (get()._canvasLoaded[workspaceId]) return;

        try {
          const data = await fetchCanvasState(workspaceId);
          if (data.blocks && data.blocks.length > 0) {
            set((state) => {
              const existing = state.blocks[workspaceId] || [];
              // Only replace if local is empty or backend has data
              const blocks = existing.length === 0
                ? data.blocks as unknown as CanvasBlock[]
                : existing;
              return {
                blocks: { ...state.blocks, [workspaceId]: blocks },
                _canvasLoaded: { ...state._canvasLoaded, [workspaceId]: true },
              };
            });
          } else {
            set((state) => ({
              _canvasLoaded: { ...state._canvasLoaded, [workspaceId]: true },
            }));
          }
        } catch {
          set((state) => ({
            _canvasLoaded: { ...state._canvasLoaded, [workspaceId]: true },
          }));
        }
      },
    }),
    {
      name: 'datalens-canvas',
      partialize: (state) => ({
        blocks: state.blocks,
        activeTab: state.activeTab,
      }),
    }
  )
);
