import type { ConnectionInfo } from './connection';

export interface Workspace {
  id: string;
  name: string;
  description: string;
  icon: string;
  connectionIds: string[];
  connections: ConnectionInfo[];
  createdAt: number;
  updatedAt: number;
  lastActiveAt: number;
}

export interface WorkspaceCreate {
  name: string;
  description: string;
  icon: string;
}
