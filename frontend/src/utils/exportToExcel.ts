import * as XLSX from 'xlsx';
import type { InsightResult } from '../types/chat';

const SINGLE_VALUE_TYPES = new Set(['kpi', 'gauge']);

export function exportInsightToExcel(insight: InsightResult, filename: string): void {
  const wb = XLSX.utils.book_new();

  (insight.tables ?? []).forEach((table, i) => {
    const sheetName = sanitizeSheetName(table.title || `Table ${i + 1}`);
    const ws = XLSX.utils.json_to_sheet(table.data, { header: table.columns });
    XLSX.utils.book_append_sheet(wb, ws, sheetName);
  });

  (insight.charts ?? [])
    .filter(c => !SINGLE_VALUE_TYPES.has(c.chart_type) && (c.data?.length ?? 0) > 0)
    .forEach((chart, i) => {
      const sheetName = sanitizeSheetName(chart.title || `Chart ${i + 1}`);
      const ws = XLSX.utils.json_to_sheet(chart.data);
      XLSX.utils.book_append_sheet(wb, ws, sheetName);
    });

  if (wb.SheetNames.length === 0) return;

  const safeFile = sanitizeFilename(filename) || 'data';
  XLSX.writeFile(wb, `${safeFile}_data.xlsx`);
}

function sanitizeSheetName(name: string): string {
  return name.replace(/[\\/?*[\]:]/g, '').slice(0, 31);
}

function sanitizeFilename(name: string): string {
  return name.replace(/[^a-zA-Z0-9_\- ]/g, '').trim().replace(/\s+/g, '_');
}
