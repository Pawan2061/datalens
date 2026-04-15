import ChartRenderer from '../../insights/ChartRenderer';
import type { ChartBlockData } from '../../../types/canvas';

interface ChartBlockProps {
  data: ChartBlockData;
  showData?: boolean;
}

export default function ChartBlock({ data, showData }: ChartBlockProps) {
  return (
    <div style={{ width: '100%', height: '100%', minHeight: 0 }}>
      <ChartRenderer chart={data.chart} compact showData={showData} />
    </div>
  );
}
