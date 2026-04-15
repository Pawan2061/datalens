import type { KpiBlockData } from '../../../types/canvas';

function fmtVal(value: number | string): string {
  if (typeof value !== 'number') return String(value);
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(2)}K`;
  if (Number.isInteger(value)) return value.toLocaleString();
  return value.toFixed(2);
}

interface KpiBlockProps {
  data: KpiBlockData;
}

export default function KpiBlock({ data }: KpiBlockProps) {
  return (
    <div className="kpi-grid">
      {data.metrics.map((metric, i) => (
        <div key={i} className="kpi-card" style={{ animationDelay: `${i * 80}ms` }}>
          <p className="kpi-label">{metric.label}</p>
          <p className="kpi-value">{fmtVal(metric.value)}</p>
        </div>
      ))}
    </div>
  );
}
