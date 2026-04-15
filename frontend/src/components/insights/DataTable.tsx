import { useState, useMemo } from 'react';
import { ChevronUp, ChevronDown, Table2 } from 'lucide-react';
import type { TableData } from '../../types/chat';

interface DataTableProps {
  table: TableData;
}

function fmtCell(value: unknown): string {
  if (value === null || value === undefined) return '\u2014';
  if (typeof value === 'number') {
    if (Math.abs(value) >= 1_000_000_000) {
      return `${(value / 1_000_000_000).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}B`;
    }
    if (Math.abs(value) >= 1_000_000) {
      return `${(value / 1_000_000).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}M`;
    }
    if (Number.isInteger(value)) return value.toLocaleString('en-US');
    return value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  return String(value);
}

export default function DataTable({ table }: DataTableProps) {
  const [sortCol, setSortCol] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');
  const [expanded, setExpanded] = useState(false);

  const handleSort = (col: string) => {
    if (sortCol === col) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    } else {
      setSortCol(col);
      setSortDir('asc');
    }
  };

  const sortedData = useMemo(() => {
    if (!sortCol) return table.data;
    return [...table.data].sort((a, b) => {
      const aVal = a[sortCol];
      const bVal = b[sortCol];
      if (aVal === bVal) return 0;
      if (aVal == null) return 1;
      if (bVal == null) return -1;
      const cmp = typeof aVal === 'number' && typeof bVal === 'number' ? aVal - bVal : String(aVal).localeCompare(String(bVal));
      return sortDir === 'asc' ? cmp : -cmp;
    });
  }, [table.data, sortCol, sortDir]);

  const displayData = expanded ? sortedData : sortedData.slice(0, 8);
  const hasMore = sortedData.length > 8;

  return (
    <div className="dt-wrap">
      <div className="dt-header">
        <Table2 size={16} color="#9ca3af" />
        <h4 className="dt-title">{table.title}</h4>
        <span className="dt-count">{table.data.length} rows</span>
      </div>

      <div className="dt-table-wrap">
        <div className="dt-scroll">
          <table className="dt-table">
            <thead>
              <tr>
                {table.columns.map((col) => (
                  <th key={col} onClick={() => handleSort(col)} className="dt-th">
                    <div className="dt-th-inner">
                      {col}
                      {sortCol === col && (
                        sortDir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />
                      )}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {displayData.map((row, i) => (
                <tr key={i} className="dt-row">
                  {table.columns.map((col) => (
                    <td key={col} className="dt-cell">
                      {fmtCell(row[col])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {hasMore && (
          <div className="dt-footer">
            <button onClick={() => setExpanded(!expanded)} className="dt-expand-btn">
              {expanded ? 'Show less' : `Show all ${sortedData.length} rows`}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
