const configuredApiBase = (import.meta.env.VITE_API_URL || '').trim().replace(/\/+$/, '');

// In production behind Apache/nginx, default to the current origin so API calls
// stay on the same host even if VITE_API_URL wasn't injected at build time.
export const API_BASE = configuredApiBase || window.location.origin;
