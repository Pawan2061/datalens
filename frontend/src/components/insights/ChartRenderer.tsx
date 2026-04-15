import { useState } from 'react';
import {
  BarChart, Bar, LineChart, Line, PieChart, Pie, Cell,
  ScatterChart, Scatter, AreaChart, Area,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
  Treemap,
  FunnelChart, Funnel, LabelList,
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  RadialBarChart, RadialBar,
} from 'recharts';
import type { ChartRecommendation } from '../../types/chat';
import { ComposedChart } from 'recharts';

interface ChartRendererProps {
  chart: ChartRecommendation;
  /** When true, fills parent height and hides title/reasoning (for canvas blocks) */
  compact?: boolean;
  /** External data toggle (used by CanvasBlock header). Overrides internal state in compact mode. */
  showData?: boolean;
}

// Rich, vibrant palette — designed for contrast & visual appeal
const PALETTE = [
  '#6366f1', '#f97316', '#10b981', '#8b5cf6',
  '#ef4444', '#06b6d4', '#ec4899', '#14b8a6',
  '#3b82f6', '#f59e0b', '#84cc16', '#e879f9',
];

/** Format a number for display: 2 decimal places, thousands separators */
function fmtNum(value: number): string {
  // Integer — just add commas
  if (Number.isInteger(value)) return value.toLocaleString('en-US');
  // Float — 2 decimal places with commas
  return value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtVal(value: unknown): string {
  if (typeof value !== 'number') return String(value ?? '');
  if (Math.abs(value) >= 1_000_000_000) return `${fmtNum(value / 1_000_000_000)}B`;
  if (Math.abs(value) >= 1_000_000) return `${fmtNum(value / 1_000_000)}M`;
  return fmtNum(value);
}

/** Check if two Y-axis series have very different scales (>10x difference) */
function needsDualAxis(data: Record<string, unknown>[], yAxes: string[]): boolean {
  if (yAxes.length < 2) return false;
  const ranges = yAxes.map((key) => {
    const vals = data.map((d) => Number(d[key]) || 0).filter((v) => v !== 0);
    if (vals.length === 0) return { min: 0, max: 0, avg: 0 };
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    return { min, max, avg: (min + max) / 2 };
  });
  // Compare max values — if ratio > 5x, use dual axes
  const maxVals = ranges.map((r) => Math.abs(r.max));
  const biggest = Math.max(...maxVals);
  const smallest = Math.max(Math.min(...maxVals), 0.001);
  return biggest / smallest > 5;
}

/** Format axis tick: shorter for space — K/M/B suffixes with 2 decimals */
function fmtTick(value: unknown): string {
  if (typeof value !== 'number') return String(value ?? '');
  if (Math.abs(value) >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(2)}B`;
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (Math.abs(value) >= 10_000) return `${(value / 1_000).toFixed(1)}K`;
  if (Number.isInteger(value)) return value.toLocaleString('en-US');
  return value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Truncate long X-axis labels and optionally angle them */
function fmtXTick(value: unknown): string {
  const s = String(value ?? '');
  if (s.length <= 14) return s;
  return s.slice(0, 13) + '…';
}

/** Detect if X-axis labels are long (>12 chars avg) — if so, angle them */
function xAxisNeedsAngle(data: Record<string, unknown>[], xKey: string): boolean {
  if (!xKey || data.length === 0) return false;
  const avgLen = data.reduce((sum, d) => sum + String(d[xKey] ?? '').length, 0) / data.length;
  return avgLen > 12;
}

const tooltipStyle = {
  borderRadius: '12px',
  border: 'none',
  fontSize: '12px',
  boxShadow: '0 8px 32px rgba(0,0,0,0.12), 0 2px 8px rgba(0,0,0,0.06)',
  padding: '10px 14px',
  background: 'rgba(255,255,255,0.96)',
  backdropFilter: 'blur(8px)',
};

/** Custom legend that wraps properly and truncates long names */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function CustomLegend({ payload }: { payload?: readonly any[] }) {
  if (!payload || payload.length === 0) return null;
  return (
    <div className="cr-legend">
      {payload.map((entry, i) => {
        const maxLen = payload.length > 4 ? 16 : 24;
        const display = entry.value.length > maxLen ? entry.value.slice(0, maxLen - 1) + '…' : entry.value;
        return (
          <span key={i} className="cr-legend-item" title={entry.value}>
            <span className="cr-legend-dot" style={{ background: entry.color }} />
            {display}
          </span>
        );
      })}
    </div>
  );
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const legendProps: any = {
  verticalAlign: 'bottom',
  align: 'center',
  content: CustomLegend,
  iconSize: 0,
};

/* ─── KPI Cards ──────────────────────────────────────────────── */

function KPICards({ chart }: { chart: ChartRecommendation }) {
  const firstItem = chart.data[0] || {};
  const keys = Object.keys(firstItem);
  const valueKeys = keys.filter(k => typeof firstItem[k] === 'number');
  const stringKeys = keys.filter(k => typeof firstItem[k] === 'string');

  // Decide grid class based on count
  const count = chart.data.length;
  const gridClass = count <= 2 ? 'cr-kpi-grid cr-kpi-grid--2'
    : count <= 4 ? 'cr-kpi-grid cr-kpi-grid--4'
    : 'cr-kpi-grid';

  // If there are numeric values, use first string key as label and numbers as values.
  // If ALL values are strings (e.g. "top collection name"), show string value as the big text.
  const hasNumeric = valueKeys.length > 0;
  const labelKey = hasNumeric
    ? (stringKeys[0] || keys[0])
    : (keys.length > 1 ? keys[0] : '');  // For text-only: first key is the "label" header

  return (
    <div className={gridClass}>
      {chart.data.map((item, i) => {
        if (hasNumeric) {
          // Standard KPI: label + numeric values
          const label = String(item[labelKey] ?? '');
          return (
            <div key={i} className="cr-kpi-card" style={{ animationDelay: `${i * 80}ms` }}>
              <p className="cr-kpi-label">{label}</p>
              {valueKeys.map(vk => (
                <div key={vk} className="cr-kpi-metric">
                  <p className="cr-kpi-value">{fmtVal(item[vk] as number)}</p>
                  {valueKeys.length > 1 && <p className="cr-kpi-metric-name">{vk.replace(/_/g, ' ')}</p>}
                </div>
              ))}
            </div>
          );
        }

        // Text-only KPI: show each key-value pair, first value is prominent
        const entries = keys.map(k => ({ key: k, value: String(item[k] ?? '') }));
        return (
          <div key={i} className="cr-kpi-card" style={{ animationDelay: `${i * 80}ms` }}>
            {entries.map((e, ei) => (
              <div key={e.key} className="cr-kpi-metric">
                <p className="cr-kpi-metric-name">{e.key.replace(/_/g, ' ')}</p>
                <p className={ei === 0 ? 'cr-kpi-value' : 'cr-kpi-label'}>{e.value}</p>
              </div>
            ))}
          </div>
        );
      })}
    </div>
  );
}

/* ─── Treemap Custom Cell ────────────────────────────────────── */

function TreemapCell(props: Record<string, unknown>) {
  const { x, y, width, height, name, fill } = props as {
    x: number; y: number; width: number; height: number; name: string; fill: string;
  };
  if (width < 4 || height < 4) return null;
  return (
    <g>
      <rect x={x} y={y} width={width} height={height} fill={fill} rx={4} stroke="#fff" strokeWidth={2} />
      {width > 50 && height > 28 && (
        <text x={x + width / 2} y={y + height / 2} textAnchor="middle" dominantBaseline="central"
              fill="#fff" fontSize={Math.min(12, width / 8)} fontWeight={600}>
          {String(name ?? '')}
        </text>
      )}
    </g>
  );
}

/* ─── Heatmap (Custom SVG) ───────────────────────────────────── */

function HeatmapChart({ rowLabels, colLabels, valueMap, minVal, maxVal }: {
  rowLabels: string[]; colLabels: string[]; valueMap: Record<string, number>;
  minVal: number; maxVal: number;
}) {
  const cellSize = Math.min(40, Math.floor(500 / Math.max(rowLabels.length, colLabels.length, 1)));
  const leftPad = 90;
  const topPad = 44;
  const width = leftPad + colLabels.length * cellSize + 8;
  const height = topPad + rowLabels.length * cellSize + 8;

  const interpolateColor = (val: number) => {
    const t = maxVal === minVal ? 0.5 : (val - minVal) / (maxVal - minVal);
    // Blue → Orange/Red scale
    const r = Math.round(59 + t * (220 - 59));
    const g = Math.round(130 + t * (53 - 130));
    const b = Math.round(246 + t * (69 - 246));
    return `rgb(${r},${g},${b})`;
  };

  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: '100%', maxHeight: 340 }}>
      {colLabels.map((col, ci) => (
        <text key={`ch-${ci}`} x={leftPad + ci * cellSize + cellSize / 2} y={topPad - 10}
              textAnchor="middle" fontSize={10} fill="#8b919d">{col}</text>
      ))}
      {rowLabels.map((row, ri) => (
        <g key={`r-${ri}`}>
          <text x={leftPad - 8} y={topPad + ri * cellSize + cellSize / 2 + 4}
                textAnchor="end" fontSize={10} fill="#8b919d">
            {row.length > 12 ? row.slice(0, 11) + '...' : row}
          </text>
          {colLabels.map((col, ci) => {
            const val = valueMap[`${row}__${col}`] ?? 0;
            return (
              <g key={`c-${ci}`}>
                <rect x={leftPad + ci * cellSize} y={topPad + ri * cellSize}
                      width={cellSize - 2} height={cellSize - 2} rx={3}
                      fill={interpolateColor(val)} />
                {cellSize > 28 && (
                  <text x={leftPad + ci * cellSize + cellSize / 2 - 1}
                        y={topPad + ri * cellSize + cellSize / 2 + 4}
                        textAnchor="middle" fontSize={9} fill="#fff" fontWeight={600}>
                    {fmtTick(val)}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      ))}
    </svg>
  );
}

/* ─── Gauge (Custom SVG Arc) ─────────────────────────────────── */

function GaugeChart({ value, max, label }: { value: number; max: number; label: string }) {
  const pct = Math.min(Math.max(value / max, 0), 1);
  const cx = 150, cy = 140, r = 100;
  const startAngle = Math.PI * 0.8;
  const totalSweep = Math.PI * 1.4; // ~252 degrees

  const polarToCart = (angle: number) => ({
    x: cx + r * Math.cos(Math.PI - angle),
    y: cy - r * Math.sin(Math.PI - angle),
  });

  const bgStart = polarToCart(startAngle);
  const bgEnd = polarToCart(startAngle - totalSweep);
  const valEnd = polarToCart(startAngle - totalSweep * pct);

  const bgArc = `M ${bgStart.x} ${bgStart.y} A ${r} ${r} 0 1 1 ${bgEnd.x} ${bgEnd.y}`;
  const valArc = `M ${bgStart.x} ${bgStart.y} A ${r} ${r} 0 ${pct > 0.5 ? 1 : 0} 1 ${valEnd.x} ${valEnd.y}`;

  const color = pct >= 0.7 ? '#059669' : pct >= 0.4 ? '#f59e0b' : '#dc2626';

  return (
    <div className="cr-gauge-wrap">
      <svg viewBox="0 0 300 200" width="280" height="190">
        <path d={bgArc} fill="none" stroke="#eef0f3" strokeWidth={20} strokeLinecap="round" />
        {pct > 0 && <path d={valArc} fill="none" stroke={color} strokeWidth={20} strokeLinecap="round" />}
        <text x={cx} y={cy + 8} textAnchor="middle" fontSize={36} fontWeight={700} fill="#111827">
          {fmtNum(Math.round(value))}{max === 100 ? '%' : ''}
        </text>
        <text x={cx} y={cy + 30} textAnchor="middle" fontSize={12} fill="#8b919d">
          {label}
        </text>
      </svg>
    </div>
  );
}

/* ─── Main ChartRenderer ─────────────────────────────────────── */

/* ─── Inline Data Table (for toggle view) ─────────────────────── */

function InlineDataTable({ data, columns }: { data: Record<string, unknown>[]; columns: string[] }) {
  const [expanded, setExpanded] = useState(false);
  const displayData = expanded ? data : data.slice(0, 10);
  const hasMore = data.length > 10;

  return (
    <div className="cr-datatable">
      <div className="cr-datatable-scroll">
        <table className="cr-datatable-table">
          <thead>
            <tr>
              {columns.map(col => (
                <th key={col} className="cr-datatable-th">{col.replace(/_/g, ' ')}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {displayData.map((row, i) => (
              <tr key={i} className="cr-datatable-row">
                {columns.map(col => (
                  <td key={col} className="cr-datatable-td">
                    {typeof row[col] === 'number' ? fmtVal(row[col] as number) : String(row[col] ?? '—')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {hasMore && (
        <button className="cr-datatable-more" onClick={() => setExpanded(!expanded)}>
          {expanded ? 'Show less' : `Show all ${data.length} rows`}
        </button>
      )}
    </div>
  );
}

export default function ChartRenderer({ chart, compact, showData: externalShowData }: ChartRendererProps) {
  const [internalShowData, setInternalShowData] = useState(false);
  // In compact mode (canvas), use external toggle from CanvasBlock header.
  // In normal mode (InsightCard), use internal toggle.
  const showData = compact ? (externalShowData ?? false) : internalShowData;
  const { chart_type, title, y_axis, data } = chart;
  if (!data || data.length === 0) return null;
  if (chart_type === 'kpi') return <div className="cr-section"><KPICards chart={chart} /></div>;
  if (chart_type === 'table') return null;

  // Defensive: resolve x_axis — handle case mismatches between recommendation and data
  const x_axis = (() => {
    const raw = chart.x_axis;
    if (!raw || data.length === 0) return raw || '';
    if (raw in data[0]) return raw;
    const lower = raw.toLowerCase();
    const match = Object.keys(data[0]).find((k) => k.toLowerCase() === lower);
    return match || raw;
  })();

  let yAxes = Array.isArray(y_axis) ? y_axis : y_axis ? [y_axis] : [];

  // Defensive: if yAxes is empty, auto-detect numeric columns from data
  if (yAxes.length === 0 && data.length > 0) {
    const firstRow = data[0];
    const numericKeys = Object.keys(firstRow).filter(
      (k) => k !== x_axis && typeof firstRow[k] === 'number'
    );
    if (numericKeys.length > 0) yAxes = numericKeys;
  }

  // Defensive: resolve yAxes keys — handle case mismatches
  if (data.length > 0) {
    const dataKeys = new Set(Object.keys(data[0]));
    yAxes = yAxes.map((y) => {
      if (dataKeys.has(y)) return y;
      const lower = y.toLowerCase();
      const match = [...dataKeys].find((k) => k.toLowerCase() === lower);
      return match || y;
    });
  }

  // Dynamic height per chart type (ignored in compact mode — fills parent instead)
  const chartHeight = (() => {
    if (compact) return undefined; // will use 100% of parent
    if (chart_type === 'gauge') return 200;
    if (chart_type === 'radar' || chart_type === 'radial_bar') return 350;
    if (chart_type === 'funnel') return Math.max(300, data.length * 55);
    if (chart_type === 'horizontal_bar') return Math.max(300, data.length * 35);
    // Add extra height for angled x-axis labels
    const hasLongLabels = xAxisNeedsAngle(data, x_axis);
    return hasLongLabels ? 360 : 300;
  })();

  // Charts that render their own SVG (not inside ResponsiveContainer)
  const isCustomSVG = chart_type === 'heatmap' || chart_type === 'gauge';

  const chartContent = (() => {
    switch (chart_type) {

      /* ── Bar (with ComposedChart for dual-axis: bars + line overlay) ── */
      case 'bar': {
        const barDualAxis = needsDualAxis(data, yAxes);
        const angled = xAxisNeedsAngle(data, x_axis);
        const xTickProps = angled
          ? { angle: -35, textAnchor: 'end' as const, fontSize: 10, fill: '#8b919d' }
          : { fontSize: 12, fill: '#8b919d' };
        const bottomMargin = angled ? 60 : 4;

        if (barDualAxis && yAxes.length >= 2) {
          // Use ComposedChart: first series as bars, rest as lines on right axis
          const barKey = yAxes[0];
          const lineKeys = yAxes.slice(1);
          return (
            <ComposedChart data={data} margin={{ top: 8, right: 48, bottom: bottomMargin, left: 4 }}>
              <defs>
                <linearGradient id="bar-grad-0" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={PALETTE[0]} stopOpacity={0.9} />
                  <stop offset="100%" stopColor={PALETTE[0]} stopOpacity={0.65} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#eef0f3" vertical={false} />
              <XAxis dataKey={x_axis || ''} tick={xTickProps} tickFormatter={fmtXTick} axisLine={{ stroke: '#eef0f3' }} tickLine={false} interval={0} height={angled ? 70 : 30} />
              <YAxis yAxisId="left" tickFormatter={fmtTick} tick={{ fontSize: 11, fill: PALETTE[0] }} axisLine={false} tickLine={false} />
              <YAxis yAxisId="right" orientation="right" tickFormatter={fmtTick} tick={{ fontSize: 11, fill: PALETTE[1] }} axisLine={false} tickLine={false} />
              <Tooltip formatter={(val) => fmtVal(val)} contentStyle={tooltipStyle} cursor={{ fill: 'rgba(0,0,0,0.03)' }} />
              <Legend {...legendProps} />
              <Bar dataKey={barKey} yAxisId="left" fill="url(#bar-grad-0)" radius={[6, 6, 0, 0]} maxBarSize={52} animationDuration={800} />
              {lineKeys.map((key, i) => (
                <Line key={key} type="monotone" dataKey={key} yAxisId="right" stroke={PALETTE[i + 1]}
                  strokeWidth={2.5} dot={{ r: 4, fill: '#fff', stroke: PALETTE[i + 1], strokeWidth: 2 }}
                  activeDot={{ r: 6, fill: PALETTE[i + 1], stroke: '#fff', strokeWidth: 2 }} />
              ))}
            </ComposedChart>
          );
        }

        // Single-axis: normal bar chart
        return (
          <BarChart data={data} margin={{ top: 8, right: 16, bottom: bottomMargin, left: 4 }}>
            <defs>
              {yAxes.map((key, i) => (
                <linearGradient key={`bar-g-${key}`} id={`bar-grad-${i}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={PALETTE[i % PALETTE.length]} stopOpacity={0.9} />
                  <stop offset="100%" stopColor={PALETTE[i % PALETTE.length]} stopOpacity={0.65} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#eef0f3" vertical={false} />
            <XAxis dataKey={x_axis || ''} tick={xTickProps} tickFormatter={fmtXTick} axisLine={{ stroke: '#eef0f3' }} tickLine={false} interval={0} height={angled ? 70 : 30} />
            <YAxis tickFormatter={fmtTick} tick={{ fontSize: 12, fill: '#8b919d' }} axisLine={false} tickLine={false} />
            <Tooltip formatter={(val) => fmtVal(val)} contentStyle={tooltipStyle} cursor={{ fill: 'rgba(0,0,0,0.03)' }} />
            {yAxes.length > 1 && <Legend {...legendProps} />}
            {yAxes.map((key, i) => (
              <Bar key={key} dataKey={key} fill={`url(#bar-grad-${i})`} radius={[6, 6, 0, 0]} maxBarSize={52} animationDuration={800} />
            ))}
          </BarChart>
        );
      }

      /* ── Grouped Bar (side-by-side) ─────────────────────── */
      case 'grouped_bar': {
        const colorByKey = chart.color_by;
        let groupedData = data as Record<string, unknown>[];
        let groupKeys = yAxes;

        if (colorByKey && yAxes.length === 1) {
          const valueKey = yAxes[0];
          const grouped: Record<string, Record<string, unknown>> = {};
          const seriesNames = new Set<string>();
          for (const row of data) {
            const xVal = String(row[x_axis || ''] ?? '');
            const series = String(row[colorByKey] ?? '');
            seriesNames.add(series);
            if (!grouped[xVal]) grouped[xVal] = { [x_axis || '']: row[x_axis || ''] };
            grouped[xVal][series] = row[valueKey];
          }
          groupedData = Object.values(grouped);
          groupKeys = Array.from(seriesNames);
        }

        const gbAngled = xAxisNeedsAngle(groupedData, x_axis);
        const gbXProps = gbAngled
          ? { angle: -35, textAnchor: 'end' as const, fontSize: 10, fill: '#8b919d' }
          : { fontSize: 12, fill: '#8b919d' };

        return (
          <BarChart data={groupedData} margin={{ top: 8, right: 16, bottom: gbAngled ? 60 : 4, left: 4 }}>
            <defs>
              {groupKeys.map((key, i) => (
                <linearGradient key={`gb-g-${key}`} id={`gb-grad-${i}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={PALETTE[i % PALETTE.length]} stopOpacity={0.9} />
                  <stop offset="100%" stopColor={PALETTE[i % PALETTE.length]} stopOpacity={0.65} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#eef0f3" vertical={false} />
            <XAxis dataKey={x_axis || ''} tick={gbXProps} tickFormatter={fmtXTick} axisLine={{ stroke: '#eef0f3' }} tickLine={false} interval={0} height={gbAngled ? 70 : 30} />
            <YAxis tickFormatter={fmtTick} tick={{ fontSize: 12, fill: '#8b919d' }} axisLine={false} tickLine={false} />
            <Tooltip formatter={(val) => fmtVal(val)} contentStyle={tooltipStyle} cursor={{ fill: 'rgba(0,0,0,0.03)' }} />
            <Legend {...legendProps} />
            {groupKeys.map((key, i) => (
              <Bar key={key} dataKey={key} fill={`url(#gb-grad-${i})`} radius={[6, 6, 0, 0]} maxBarSize={48} animationDuration={800} />
            ))}
          </BarChart>
        );
      }

      /* ── Stacked Bar ─────────────────────────────────────── */
      case 'stacked_bar': {
        const colorByKey = chart.color_by;
        let stackedData = data as Record<string, unknown>[];
        let stackKeys = yAxes;

        if (colorByKey && yAxes.length === 1) {
          const valueKey = yAxes[0];
          const grouped: Record<string, Record<string, unknown>> = {};
          const seriesNames = new Set<string>();
          for (const row of data) {
            const xVal = String(row[x_axis || ''] ?? '');
            const series = String(row[colorByKey] ?? '');
            seriesNames.add(series);
            if (!grouped[xVal]) grouped[xVal] = { [x_axis || '']: row[x_axis || ''] };
            grouped[xVal][series] = row[valueKey];
          }
          stackedData = Object.values(grouped);
          stackKeys = Array.from(seriesNames);
        }

        const sbAngled = xAxisNeedsAngle(stackedData, x_axis);
        const sbXProps = sbAngled
          ? { angle: -35, textAnchor: 'end' as const, fontSize: 10, fill: '#8b919d' }
          : { fontSize: 12, fill: '#8b919d' };

        return (
          <BarChart data={stackedData} margin={{ top: 8, right: 16, bottom: sbAngled ? 60 : 4, left: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eef0f3" vertical={false} />
            <XAxis dataKey={x_axis || ''} tick={sbXProps} tickFormatter={fmtXTick} axisLine={{ stroke: '#eef0f3' }} tickLine={false} interval={0} height={sbAngled ? 70 : 30} />
            <YAxis tickFormatter={fmtTick} tick={{ fontSize: 12, fill: '#8b919d' }} axisLine={false} tickLine={false} />
            <Tooltip formatter={(val) => fmtVal(val)} contentStyle={tooltipStyle} />
            <Legend {...legendProps} />
            {stackKeys.map((key, i) => (
              <Bar key={key} dataKey={key} stackId="a" fill={PALETTE[i % PALETTE.length]} />
            ))}
          </BarChart>
        );
      }

      /* ── Horizontal Bar ──────────────────────────────────── */
      case 'horizontal_bar':
        return (
          <BarChart data={data} layout="vertical" margin={{ top: 8, right: 16, bottom: 4, left: 80 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eef0f3" horizontal={false} />
            <YAxis type="category" dataKey={x_axis || ''} tick={{ fontSize: 11, fill: '#8b919d' }} axisLine={false} tickLine={false} width={75} />
            <XAxis type="number" tickFormatter={fmtTick} tick={{ fontSize: 12, fill: '#8b919d' }} axisLine={{ stroke: '#eef0f3' }} tickLine={false} />
            <Tooltip formatter={(val) => fmtVal(val)} contentStyle={tooltipStyle} />
            {yAxes.length > 1 && <Legend {...legendProps} />}
            {yAxes.map((key, i) => (
              <Bar key={key} dataKey={key} fill={PALETTE[i % PALETTE.length]} radius={[0, 6, 6, 0]} maxBarSize={32} />
            ))}
          </BarChart>
        );

      /* ── Line (with dual Y-axis support) ────────────────── */
      case 'line': {
        const dualAxis = needsDualAxis(data, yAxes);
        const lineAngled = xAxisNeedsAngle(data, x_axis);
        const lineXProps = lineAngled
          ? { angle: -35, textAnchor: 'end' as const, fontSize: 10, fill: '#8b919d' }
          : { fontSize: 12, fill: '#8b919d' };
        return (
          <LineChart data={data} margin={{ top: 8, right: dualAxis ? 48 : 16, bottom: lineAngled ? 60 : 4, left: 4 }}>
            <defs>
              {yAxes.map((key, i) => (
                <filter key={`glow-${key}`} id={`line-glow-${i}`}>
                  <feGaussianBlur stdDeviation="2" result="blur" />
                  <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
                </filter>
              ))}
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#eef0f3" vertical={false} />
            <XAxis dataKey={x_axis || ''} tick={lineXProps} tickFormatter={fmtXTick} axisLine={{ stroke: '#eef0f3' }} tickLine={false} interval={0} height={lineAngled ? 70 : 30} />
            {dualAxis ? (
              <>
                <YAxis yAxisId="left" tickFormatter={fmtTick} tick={{ fontSize: 11, fill: PALETTE[0] }} axisLine={false} tickLine={false} />
                <YAxis yAxisId="right" orientation="right" tickFormatter={fmtTick} tick={{ fontSize: 11, fill: PALETTE[1] }} axisLine={false} tickLine={false} />
              </>
            ) : (
              <YAxis tickFormatter={fmtTick} tick={{ fontSize: 12, fill: '#8b919d' }} axisLine={false} tickLine={false} />
            )}
            <Tooltip formatter={(val) => fmtVal(val)} contentStyle={tooltipStyle} />
            {yAxes.length > 1 && <Legend {...legendProps} />}
            {yAxes.map((key, i) => (
              <Line key={key} type="monotone" dataKey={key} stroke={PALETTE[i % PALETTE.length]}
                strokeWidth={2.5} dot={{ r: 3.5, fill: '#fff', stroke: PALETTE[i % PALETTE.length], strokeWidth: 2 }}
                activeDot={{ r: 6, fill: PALETTE[i % PALETTE.length], stroke: '#fff', strokeWidth: 2 }}
                animationDuration={1000}
                {...(dualAxis ? { yAxisId: i === 0 ? 'left' : 'right' } : {})} />
            ))}
          </LineChart>
        );
      }

      /* ── Multi-Line (with dual Y-axis for different scales) ── */
      case 'multi_line': {
        const colorByKey = chart.color_by;
        let multiLineData = data as Record<string, unknown>[];
        let lineKeys = yAxes;

        if (colorByKey && yAxes.length === 1) {
          const valueKey = yAxes[0];
          const grouped: Record<string, Record<string, unknown>> = {};
          const seriesNames = new Set<string>();
          for (const row of data) {
            const xVal = String(row[x_axis || ''] ?? '');
            const series = String(row[colorByKey] ?? '');
            seriesNames.add(series);
            if (!grouped[xVal]) grouped[xVal] = { [x_axis || '']: row[x_axis || ''] };
            grouped[xVal][series] = row[valueKey];
          }
          multiLineData = Object.values(grouped);
          lineKeys = Array.from(seriesNames);
        }

        const mlDualAxis = needsDualAxis(multiLineData, lineKeys);
        const mlAngled = xAxisNeedsAngle(multiLineData, x_axis);
        const mlXProps = mlAngled
          ? { angle: -35, textAnchor: 'end' as const, fontSize: 10, fill: '#8b919d' }
          : { fontSize: 12, fill: '#8b919d' };

        return (
          <LineChart data={multiLineData} margin={{ top: 8, right: mlDualAxis ? 48 : 16, bottom: mlAngled ? 60 : 4, left: 4 }}>
            <defs>
              {lineKeys.map((key, i) => (
                <filter key={`ml-glow-${key}`} id={`ml-glow-${i}`}>
                  <feGaussianBlur stdDeviation="2" result="blur" />
                  <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
                </filter>
              ))}
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#eef0f3" vertical={false} />
            <XAxis dataKey={x_axis || ''} tick={mlXProps} tickFormatter={fmtXTick} axisLine={{ stroke: '#eef0f3' }} tickLine={false} interval={0} height={mlAngled ? 70 : 30} />
            {mlDualAxis ? (
              <>
                <YAxis yAxisId="left" tickFormatter={fmtTick} tick={{ fontSize: 11, fill: PALETTE[0] }} axisLine={false} tickLine={false} />
                <YAxis yAxisId="right" orientation="right" tickFormatter={fmtTick} tick={{ fontSize: 11, fill: PALETTE[1] }} axisLine={false} tickLine={false} />
              </>
            ) : (
              <YAxis tickFormatter={fmtTick} tick={{ fontSize: 12, fill: '#8b919d' }} axisLine={false} tickLine={false} />
            )}
            <Tooltip formatter={(val) => fmtVal(val)} contentStyle={tooltipStyle} />
            <Legend {...legendProps} />
            {lineKeys.map((key, i) => (
              <Line key={key} type="monotone" dataKey={key} stroke={PALETTE[i % PALETTE.length]}
                strokeWidth={2.5} dot={{ r: 3.5, fill: '#fff', stroke: PALETTE[i % PALETTE.length], strokeWidth: 2 }}
                activeDot={{ r: 6, fill: PALETTE[i % PALETTE.length], stroke: '#fff', strokeWidth: 2 }}
                animationDuration={1000} connectNulls
                {...(mlDualAxis ? { yAxisId: i === 0 ? 'left' : 'right' } : {})} />
            ))}
          </LineChart>
        );
      }

      /* ── Area (with dual Y-axis support) ────────────────── */
      case 'area': {
        const areaDualAxis = needsDualAxis(data, yAxes);
        return (
          <AreaChart data={data} margin={{ top: 8, right: areaDualAxis ? 48 : 16, bottom: 4, left: 4 }}>
            <defs>
              {yAxes.map((key, i) => (
                <linearGradient key={key} id={`grad-${i}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={PALETTE[i % PALETTE.length]} stopOpacity={0.25} />
                  <stop offset="50%" stopColor={PALETTE[i % PALETTE.length]} stopOpacity={0.08} />
                  <stop offset="100%" stopColor={PALETTE[i % PALETTE.length]} stopOpacity={0} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#eef0f3" vertical={false} />
            <XAxis dataKey={x_axis || ''} tick={{ fontSize: 12, fill: '#8b919d' }} axisLine={{ stroke: '#eef0f3' }} tickLine={false} />
            {areaDualAxis ? (
              <>
                <YAxis yAxisId="left" tickFormatter={fmtTick} tick={{ fontSize: 11, fill: PALETTE[0] }} axisLine={false} tickLine={false} />
                <YAxis yAxisId="right" orientation="right" tickFormatter={fmtTick} tick={{ fontSize: 11, fill: PALETTE[1] }} axisLine={false} tickLine={false} />
              </>
            ) : (
              <YAxis tickFormatter={fmtTick} tick={{ fontSize: 12, fill: '#8b919d' }} axisLine={false} tickLine={false} />
            )}
            <Tooltip formatter={(val) => fmtVal(val)} contentStyle={tooltipStyle} />
            {yAxes.map((key, i) => (
              <Area key={key} type="monotone" dataKey={key} stroke={PALETTE[i % PALETTE.length]} fill={`url(#grad-${i})`}
                strokeWidth={2.5} animationDuration={1000} dot={{ r: 3, fill: '#fff', stroke: PALETTE[i % PALETTE.length], strokeWidth: 2 }}
                activeDot={{ r: 5, fill: PALETTE[i % PALETTE.length], stroke: '#fff', strokeWidth: 2 }}
                {...(areaDualAxis ? { yAxisId: i === 0 ? 'left' : 'right' } : {})} />
            ))}
          </AreaChart>
        );
      }

      /* ── Pie (Donut) ─────────────────────────────────────── */
      case 'pie':
        return (
          <PieChart>
            <defs>
              <filter id="pie-shadow">
                <feDropShadow dx="0" dy="2" stdDeviation="3" floodOpacity="0.1" />
              </filter>
            </defs>
            <Pie data={data} dataKey={yAxes[0] || ''} nameKey={x_axis || ''} cx="50%" cy="50%"
              outerRadius={120} innerRadius={65} paddingAngle={4} strokeWidth={2} stroke="#fff"
              label={({ name, percent }: { name?: string; percent?: number }) => `${name ?? ''} ${((percent ?? 0) * 100).toFixed(0)}%`}
              labelLine={{ stroke: '#cdd2d9', strokeWidth: 1 }}
              animationDuration={800}
            >
              {data.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
            </Pie>
            <Tooltip formatter={(val) => fmtVal(val)} contentStyle={tooltipStyle} />
          </PieChart>
        );

      /* ── Scatter ─────────────────────────────────────────── */
      case 'scatter':
        return (
          <ScatterChart margin={{ top: 8, right: 16, bottom: 4, left: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eef0f3" />
            <XAxis dataKey={x_axis || ''} name={x_axis || ''} tick={{ fontSize: 12, fill: '#8b919d' }} tickFormatter={fmtTick} axisLine={{ stroke: '#eef0f3' }} tickLine={false} />
            <YAxis dataKey={yAxes[0] || ''} name={yAxes[0] || ''} tick={{ fontSize: 12, fill: '#8b919d' }} tickFormatter={fmtTick} axisLine={false} tickLine={false} />
            <Tooltip formatter={(val) => fmtVal(val)} contentStyle={tooltipStyle} />
            <Scatter data={data} fill={PALETTE[0]} />
          </ScatterChart>
        );

      /* ── Treemap ─────────────────────────────────────────── */
      case 'treemap': {
        const nameKey = x_axis || Object.keys(data[0] || {}).find(k => typeof data[0][k] === 'string') || '';
        const valueKey = yAxes[0] || Object.keys(data[0] || {}).find(k => typeof data[0][k] === 'number') || '';
        const treemapData = data.map((row, i) => ({
          name: String(row[nameKey] ?? ''),
          size: Number(row[valueKey] ?? 0),
          fill: PALETTE[i % PALETTE.length],
        }));
        return (
          <Treemap
            data={treemapData}
            dataKey="size"
            nameKey="name"
            aspectRatio={4 / 3}
            stroke="#fff"
            content={<TreemapCell />}
          >
            <Tooltip formatter={(val) => fmtVal(val)} contentStyle={tooltipStyle} />
          </Treemap>
        );
      }

      /* ── Funnel ──────────────────────────────────────────── */
      case 'funnel': {
        const nameKey = x_axis || '';
        const valueKey = yAxes[0] || '';
        const funnelData = data.map((row, i) => ({
          name: String(row[nameKey] ?? ''),
          value: Number(row[valueKey] ?? 0),
          fill: PALETTE[i % PALETTE.length],
        }));
        return (
          <FunnelChart>
            <Tooltip formatter={(val) => fmtVal(val)} contentStyle={tooltipStyle} />
            <Funnel dataKey="value" nameKey="name" data={funnelData} isAnimationActive>
              <LabelList position="right" fill="#4b5563" fontSize={12} dataKey="name" />
              <LabelList position="center" fill="#fff" fontSize={12} fontWeight={700}
                         formatter={(val: unknown) => fmtVal(val)} />
            </Funnel>
          </FunnelChart>
        );
      }

      /* ── Radar ───────────────────────────────────────────── */
      case 'radar': {
        const entityKey = x_axis;
        const dimensions = yAxes;

        if (entityKey && dimensions.length > 0 && data.length > 1) {
          // Multi-entity: rows are entities, yAxes are dimensions
          const entities = data.map(row => String(row[entityKey] ?? ''));
          const radarData = dimensions.map(dim => {
            const point: Record<string, unknown> = { dimension: dim };
            data.forEach(row => {
              point[String(row[entityKey] ?? '')] = Number(row[dim] ?? 0);
            });
            return point;
          });
          return (
            <RadarChart cx="50%" cy="50%" outerRadius="70%" data={radarData}>
              <PolarGrid stroke="#eef0f3" />
              <PolarAngleAxis dataKey="dimension" tick={{ fontSize: 11, fill: '#8b919d' }} />
              <PolarRadiusAxis tick={{ fontSize: 10, fill: '#8b919d' }} />
              {entities.map((name, i) => (
                <Radar key={name} name={name} dataKey={name} stroke={PALETTE[i % PALETTE.length]}
                       fill={PALETTE[i % PALETTE.length]} fillOpacity={0.15} strokeWidth={2} />
              ))}
              <Legend {...legendProps} />
              <Tooltip contentStyle={tooltipStyle} />
            </RadarChart>
          );
        }

        // Single-entity: dimensions are columns
        const radarData = dimensions.map(dim => ({
          dimension: dim,
          value: Number(data[0]?.[dim] ?? 0),
        }));
        return (
          <RadarChart cx="50%" cy="50%" outerRadius="70%" data={radarData}>
            <PolarGrid stroke="#eef0f3" />
            <PolarAngleAxis dataKey="dimension" tick={{ fontSize: 11, fill: '#8b919d' }} />
            <PolarRadiusAxis tick={{ fontSize: 10, fill: '#8b919d' }} />
            <Radar dataKey="value" stroke={PALETTE[0]} fill={PALETTE[0]} fillOpacity={0.15} strokeWidth={2} />
            <Tooltip contentStyle={tooltipStyle} />
          </RadarChart>
        );
      }

      /* ── Radial Bar ──────────────────────────────────────── */
      case 'radial_bar': {
        const nameKey = x_axis || '';
        const valueKey = yAxes[0] || '';
        const radialData = data.map((row, i) => ({
          name: String(row[nameKey] ?? ''),
          value: Number(row[valueKey] ?? 0),
          fill: PALETTE[i % PALETTE.length],
        })).reverse();
        return (
          <RadialBarChart cx="50%" cy="50%" innerRadius="20%" outerRadius="90%"
                          barSize={20} data={radialData} startAngle={180} endAngle={0}>
            <RadialBar background dataKey="value" cornerRadius={10}
                       label={{ position: 'insideStart', fill: '#fff', fontSize: 12, fontWeight: 600 }} />
            <Legend {...legendProps} />
            <Tooltip formatter={(val) => fmtVal(val)} contentStyle={tooltipStyle} />
          </RadialBarChart>
        );
      }

      /* ── Heatmap (Custom SVG) ────────────────────────────── */
      case 'heatmap': {
        const cfg = chart.config || {};
        const rowKey = (cfg.row_key as string) || x_axis || '';
        const colKey = (cfg.col_key as string) || chart.color_by || '';
        const valKey = (cfg.value_key as string) || yAxes[0] || '';

        const rowLabels = [...new Set(data.map(d => String(d[rowKey] ?? '')))];
        const colLabels = [...new Set(data.map(d => String(d[colKey] ?? '')))];

        const valueMap: Record<string, number> = {};
        let minVal = Infinity, maxVal = -Infinity;
        for (const row of data) {
          const key = `${row[rowKey]}__${row[colKey]}`;
          const val = Number(row[valKey] ?? 0);
          valueMap[key] = val;
          if (val < minVal) minVal = val;
          if (val > maxVal) maxVal = val;
        }

        return <HeatmapChart rowLabels={rowLabels} colLabels={colLabels}
                             valueMap={valueMap} minVal={minVal} maxVal={maxVal} />;
      }

      /* ── Waterfall (BarChart trick) ──────────────────────── */
      case 'waterfall': {
        const nameKey = x_axis || '';
        const valueKey = yAxes[0] || '';

        let running = 0;
        const waterfallData = data.map((row, i) => {
          const val = Number(row[valueKey] ?? 0);
          const isTotal = i === data.length - 1;
          const base = isTotal ? 0 : Math.min(running, running + val);
          const barHeight = isTotal ? val : Math.abs(val);
          const isPositive = val >= 0;
          if (!isTotal) running += val;
          return {
            name: String(row[nameKey] ?? ''),
            invisible: base,
            value: barHeight,
            isPositive,
            isTotal,
            raw: val,
          };
        });

        return (
          <BarChart data={waterfallData} margin={{ top: 8, right: 16, bottom: 4, left: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eef0f3" vertical={false} />
            <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#8b919d' }} axisLine={{ stroke: '#eef0f3' }} tickLine={false} />
            <YAxis tickFormatter={fmtTick} tick={{ fontSize: 12, fill: '#8b919d' }} axisLine={false} tickLine={false} />
            <Tooltip
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              formatter={(_: unknown, __: unknown, props: any) => {
                return fmtVal(props?.payload?.raw);
              }}
              contentStyle={tooltipStyle}
            />
            <Bar dataKey="invisible" stackId="waterfall" fill="transparent" />
            <Bar dataKey="value" stackId="waterfall" radius={[4, 4, 0, 0]}>
              {waterfallData.map((entry, i) => (
                <Cell key={i} fill={entry.isTotal ? '#2b8de6' : entry.isPositive ? '#059669' : '#dc2626'} />
              ))}
            </Bar>
          </BarChart>
        );
      }

      /* ── Gauge (Custom SVG) ──────────────────────────────── */
      case 'gauge': {
        const valueKey = yAxes[0] || Object.keys(data[0] || {}).find(k => typeof data[0]?.[k] === 'number') || '';
        const value = Number(data[0]?.[valueKey] ?? 0);
        const max = Number(chart.config?.max ?? 100);
        return <GaugeChart value={value} max={max} label={valueKey} />;
      }

      /* ── Default fallback ────────────────────────────────── */
      default:
        return (
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#eef0f3" vertical={false} />
            <XAxis dataKey={x_axis || ''} tick={{ fontSize: 12, fill: '#8b919d' }} />
            <YAxis tickFormatter={fmtTick} tick={{ fontSize: 12, fill: '#8b919d' }} />
            <Tooltip contentStyle={tooltipStyle} />
            {yAxes.map((key, i) => <Bar key={key} dataKey={key} fill={PALETTE[i % PALETTE.length]} radius={[6, 6, 0, 0]} />)}
          </BarChart>
        );
    }
  })();

  // Data table columns — use all keys from first row
  const tableColumns = data.length > 0 ? Object.keys(data[0]) : [];

  // Toggle button element — only for normal (InsightCard) mode; canvas uses header buttons
  const toggleBtn = !compact && tableColumns.length > 0 && (
    <button
      className="cr-view-toggle"
      onClick={() => setInternalShowData(v => !v)}
      title={showData ? 'View Chart' : 'View Data'}
    >
      {showData ? '📊 Chart' : '📋 Data'}
    </button>
  );

  // Compact mode: fill parent, no title/reasoning chrome
  if (compact) {
    return (
      <div style={{ width: '100%', height: '100%', minHeight: 0 }}>
        {showData ? (
          <InlineDataTable data={data} columns={tableColumns} />
        ) : isCustomSVG ? (
          chartContent
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            {chartContent}
          </ResponsiveContainer>
        )}
      </div>
    );
  }

  return (
    <div className="cr-section">
      <div className="cr-chart-card">
        <div className="cr-chart-header">
          <h4 className="cr-chart-title">{title}</h4>
          {toggleBtn}
        </div>
        {showData ? (
          <InlineDataTable data={data} columns={tableColumns} />
        ) : isCustomSVG ? (
          chartContent
        ) : (
          <ResponsiveContainer width="100%" height={chartHeight}>
            {chartContent}
          </ResponsiveContainer>
        )}
      </div>
      {!showData && <p className="cr-reasoning">{chart.reasoning}</p>}
    </div>
  );
}
