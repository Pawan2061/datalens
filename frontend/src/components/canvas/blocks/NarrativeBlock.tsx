import TextSummary from '../../insights/TextSummary';
import type { NarrativeBlockData } from '../../../types/canvas';

interface NarrativeBlockProps {
  data: NarrativeBlockData;
  onFollowUp?: (question: string) => void;
}

export default function NarrativeBlock({ data, onFollowUp }: NarrativeBlockProps) {
  return <TextSummary summary={data.summary} onFollowUp={onFollowUp} />;
}
