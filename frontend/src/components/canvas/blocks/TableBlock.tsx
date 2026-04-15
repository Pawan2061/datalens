import DataTable from '../../insights/DataTable';
import type { TableBlockData } from '../../../types/canvas';

interface TableBlockProps {
  data: TableBlockData;
}

export default function TableBlock({ data }: TableBlockProps) {
  return <DataTable table={data.table} />;
}
