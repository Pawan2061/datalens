import { useState, useEffect, useRef } from 'react';
import { Users, ChevronDown, ShieldCheck, User, Search } from 'lucide-react';
import type { ScopeCustomer } from '../../types/workspace';

interface CustomerScopeSelectorProps {
  customers: ScopeCustomer[];
  selectedScope: string;   // "" = admin, customer_id = customer
  selectedName: string;
  onScopeChange: (id: string, name: string) => void;
}

export default function CustomerScopeSelector({
  customers,
  selectedScope,
  selectedName,
  onScopeChange,
}: CustomerScopeSelectorProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false);
        setSearch('');
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const isAdmin = !selectedScope;

  const filtered = search
    ? customers.filter(
        (c) =>
          c.name.toLowerCase().includes(search.toLowerCase()) ||
          c.code.toLowerCase().includes(search.toLowerCase()) ||
          c.id.includes(search)
      )
    : customers;

  return (
    <div className="css-wrap" ref={dropdownRef}>
      <button
        className={`css-trigger ${!isAdmin ? 'css-trigger--customer' : ''}`}
        onClick={() => setOpen((o) => !o)}
      >
        {isAdmin ? (
          <ShieldCheck size={13} className="css-icon css-icon--admin" />
        ) : (
          <User size={13} className="css-icon css-icon--customer" />
        )}
        <span className="css-label">
          {isAdmin ? 'Admin' : (selectedName || `ID ${selectedScope}`)}
        </span>
        <ChevronDown size={12} className={`css-chevron ${open ? 'css-chevron--open' : ''}`} />
      </button>

      {open && (
        <div className="css-dropdown">
          <div className="css-dropdown-header">
            <Users size={14} />
            <span>Select Scope</span>
          </div>

          {customers.length > 5 && (
            <div className="css-search-wrap">
              <Search size={13} className="css-search-icon" />
              <input
                className="css-search"
                placeholder="Search customers..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                autoFocus
              />
            </div>
          )}

          <div className="css-list">
            {/* Admin always first */}
            {!search && (
              <button
                className={`css-item css-item--admin ${isAdmin ? 'css-item--active' : ''}`}
                onClick={() => { onScopeChange('', ''); setOpen(false); setSearch(''); }}
              >
                <ShieldCheck size={13} />
                <div className="css-item-text">
                  <span className="css-item-name">Admin (all data)</span>
                  <span className="css-item-sub">Unrestricted view</span>
                </div>
                {isAdmin && <span className="css-item-check">✓</span>}
              </button>
            )}

            {filtered.map((c, idx) => (
              <button
                key={`${c.id}-${idx}`}
                className={`css-item ${selectedScope === c.id ? 'css-item--active' : ''}`}
                onClick={() => { onScopeChange(c.id, c.name || c.code); setOpen(false); setSearch(''); }}
              >
                <User size={13} />
                <div className="css-item-text">
                  <span className="css-item-name">{c.name || c.code || c.id}</span>
                  {c.code && c.name && <span className="css-item-sub">{c.code}</span>}
                </div>
                {selectedScope === c.id && <span className="css-item-check">✓</span>}
              </button>
            ))}

            {filtered.length === 0 && search && (
              <div className="css-empty">No customers match "{search}"</div>
            )}

            {customers.length === 0 && !search && (
              <div className="css-empty">No customers found</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
