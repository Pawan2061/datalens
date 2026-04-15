import { LayoutGrid, MessageSquare } from 'lucide-react';

export default function EmptyCanvas() {
  return (
    <div className="wv-empty-canvas">
      <div className="wv-empty-canvas-icon">
        <LayoutGrid size={32} />
      </div>
      <h3>Your Canvas</h3>
      <p>
        Ask questions in the chat to populate your canvas with interactive charts, tables, and insights.
      </p>
      <div className="wv-empty-canvas-pill">
        <MessageSquare size={14} />
        Start by asking a question
      </div>
    </div>
  );
}
