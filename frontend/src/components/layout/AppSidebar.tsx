import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { LayoutGrid, BarChart3, Plus, LogOut, ChevronRight, ChevronLeft } from 'lucide-react';
import DataLensLogo from '../common/DataLensLogo';
import { useAuthStore } from '../../store/authStore';

interface AppSidebarProps {
  activePage: 'home' | 'workspace';
}

export default function AppSidebar({ activePage }: AppSidebarProps) {
  const navigate = useNavigate();
  const logout = useAuthStore((s) => s.logout);
  const [expanded, setExpanded] = useState(false);

  return (
    <aside className={`app-sb ${expanded ? 'app-sb--expanded' : ''}`}>
      <div className="app-sb-top">
        {expanded ? (
          <div className="app-sb-logo-full">
            <DataLensLogo height={16} color="#fff" />
            <span className="app-sb-logo-divider" />
            <span className="app-sb-brand">DataLens</span>
          </div>
        ) : (
          <div className="app-sb-logo">
            <DataLensLogo height={16} color="#fff" />
          </div>
        )}
      </div>

      <nav className="app-sb-nav">
        <button
          className={`app-sb-item ${activePage === 'home' ? 'app-sb-item--active' : ''}`}
          onClick={() => navigate('/')}
          title="Dashboard"
        >
          <LayoutGrid size={20} />
          {expanded && <span className="app-sb-label">Dashboard</span>}
        </button>
        <button
          className={`app-sb-item ${activePage === 'workspace' ? 'app-sb-item--active' : ''}`}
          onClick={() => activePage === 'home' ? null : undefined}
          title="Workspace"
        >
          <BarChart3 size={20} />
          {expanded && <span className="app-sb-label">Workspace</span>}
        </button>
        <button
          className="app-sb-item"
          title="Create New"
        >
          <Plus size={20} />
          {expanded && <span className="app-sb-label">Create New</span>}
        </button>
      </nav>

      <div className="app-sb-bottom">
        <button
          className="app-sb-item"
          onClick={() => { logout(); navigate('/login'); }}
          title="Sign out"
        >
          <LogOut size={18} />
          {expanded && <span className="app-sb-label">Sign out</span>}
        </button>
        <button
          className="app-sb-toggle"
          onClick={() => setExpanded(!expanded)}
          title={expanded ? 'Collapse' : 'Expand'}
        >
          {expanded ? <ChevronLeft size={16} /> : <ChevronRight size={16} />}
        </button>
      </div>
    </aside>
  );
}
