import type { ConnectionInfo } from './connection';

export interface ScopeCustomer {
  id: string;
  code: string;
  name: string;
}

export interface Workspace {
  id: string;
  name: string;
  description: string;
  icon: string;
  connectionIds: string[];
  connections: ConnectionInfo[];
  scopeCustomers: ScopeCustomer[];   // loaded once on connection setup, stored permanently
  createdAt: number;
  updatedAt: number;
  lastActiveAt: number;
}

export interface WorkspaceCreate {
  name: string;
  description: string;
  icon: string;
}
