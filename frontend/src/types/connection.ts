// Connector type discriminator
export type ConnectorType =
  | 'postgresql'
  | 'mysql'
  | 'sqlserver'
  | 'cosmosdb'
  | 'mongodb'
  | 'powerbi'
  | 'file';

// File-specific types
export type FileFormat = 'csv' | 'excel' | 'json';

export interface FileSource {
  fileName: string;
  fileSize: number;
  fileFormat: FileFormat;
  file?: File; // actual File object — excluded from persistence
  sheetName?: string;
}

// SQL connector config (PostgreSQL, MySQL, SQL Server)
export interface SqlConnectionConfig {
  connectorType: 'postgresql' | 'mysql' | 'sqlserver';
  name: string;
  host: string;
  port: number;
  database: string;
  user: string;
  password: string;
  ssl?: boolean;
}

// CosmoDB connector config
export interface CosmosDbConnectionConfig {
  connectorType: 'cosmosdb';
  name: string;
  endpoint: string;
  accountKey: string;
  database: string;
  container?: string;
}

// MongoDB connector config
export interface MongoDbConnectionConfig {
  connectorType: 'mongodb';
  name: string;
  connectionString: string;
  database: string;
  authSource?: string;
}

// Power BI connector config
export interface PowerBiConnectionConfig {
  connectorType: 'powerbi';
  name: string;
  tenantId: string;
  clientId: string;
  clientSecret: string;
  pbiWorkspaceId: string;
  datasetId: string;
}

// File upload config
export interface FileConnectionConfig {
  connectorType: 'file';
  name: string;
  fileSource: FileSource;
}

// Discriminated union of all connection configs
export type ConnectionConfig =
  | SqlConnectionConfig
  | CosmosDbConnectionConfig
  | MongoDbConnectionConfig
  | PowerBiConnectionConfig
  | FileConnectionConfig;

// Schema types
export interface ColumnInfo {
  name: string;
  type: string;
  isPrimaryKey: boolean;
}

export interface TableInfo {
  name: string;
  columns: ColumnInfo[];
  rowCount?: number;
}

export interface SchemaInfo {
  tables: TableInfo[];
}

// Connection info returned after successful connection
export interface ConnectionInfo {
  id: string;
  name: string;
  connectorType: ConnectorType;
  host: string;
  database: string;
  status: 'connected' | 'disconnected' | 'testing';
  schema?: SchemaInfo;
  selectedTableNames: string[];
}

// Default ports per SQL connector
export const DEFAULT_PORTS: Record<string, number> = {
  postgresql: 5432,
  mysql: 3306,
  sqlserver: 1433,
};

// Connector display info
export const CONNECTOR_INFO: Record<ConnectorType, { label: string; description: string }> = {
  postgresql: { label: 'PostgreSQL', description: 'Relational database' },
  mysql: { label: 'MySQL', description: 'Relational database' },
  sqlserver: { label: 'SQL Server', description: 'Microsoft SQL' },
  cosmosdb: { label: 'Cosmos DB', description: 'Azure NoSQL' },
  mongodb: { label: 'MongoDB', description: 'Document database' },
  powerbi: { label: 'Power BI', description: 'Microsoft Power BI' },
  file: { label: 'File Upload', description: 'CSV, Excel, JSON' },
};
