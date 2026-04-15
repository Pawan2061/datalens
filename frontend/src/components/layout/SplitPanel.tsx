import { useState, useCallback, useRef, useEffect } from 'react';
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react';

interface SplitPanelProps {
  left: React.ReactNode;
  right: React.ReactNode;
  defaultLeftWidth?: number;
  minLeftWidth?: number;
  minRightWidth?: number;
}

export default function SplitPanel({
  left,
  right,
  defaultLeftWidth = 420,
  minLeftWidth = 320,
  minRightWidth = 400,
}: SplitPanelProps) {
  const [leftWidth, setLeftWidth] = useState(defaultLeftWidth);
  const [collapsed, setCollapsed] = useState(false);
  const isDragging = useRef(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const prevWidth = useRef(defaultLeftWidth);

  const handleMouseDown = useCallback(() => {
    if (collapsed) return;
    isDragging.current = true;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, [collapsed]);

  const handleMouseMove = useCallback(
    (e: MouseEvent) => {
      if (!isDragging.current || !containerRef.current) return;
      const containerRect = containerRef.current.getBoundingClientRect();
      const newWidth = e.clientX - containerRect.left;
      const maxLeftWidth = containerRect.width - minRightWidth - 6;
      setLeftWidth(Math.max(minLeftWidth, Math.min(maxLeftWidth, newWidth)));
    },
    [minLeftWidth, minRightWidth]
  );

  const handleMouseUp = useCallback(() => {
    isDragging.current = false;
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  }, []);

  useEffect(() => {
    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [handleMouseMove, handleMouseUp]);

  const toggleCollapse = useCallback(() => {
    if (collapsed) {
      setCollapsed(false);
      setLeftWidth(prevWidth.current);
    } else {
      prevWidth.current = leftWidth;
      setCollapsed(true);
    }
  }, [collapsed, leftWidth]);

  return (
    <div ref={containerRef} style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
      {/* Left panel (chat) — animated collapse */}
      <div
        style={{
          width: collapsed ? 0 : leftWidth,
          flexShrink: 0,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          transition: collapsed ? 'width 0.25s cubic-bezier(0.4,0,0.2,1)' : undefined,
        }}
      >
        {!collapsed && left}
      </div>

      {/* Split handle with collapse button */}
      <div
        className={`split-handle ${collapsed ? 'split-handle--collapsed' : ''}`}
        onMouseDown={handleMouseDown}
      >
        <button
          className="split-collapse-btn"
          onClick={toggleCollapse}
          title={collapsed ? 'Show chat panel' : 'Hide chat panel'}
        >
          {collapsed ? <PanelLeftOpen size={14} /> : <PanelLeftClose size={14} />}
        </button>
      </div>

      {/* Right panel (canvas) */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
        {right}
      </div>
    </div>
  );
}
