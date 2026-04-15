from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ConnectorType = Literal["postgresql", "mysql", "sqlserver", "cosmosdb", "mongodb", "file", "powerbi"]


class ConnectionConfig(BaseModel):
    """Unified connection config that supports all connector types."""

    model_config = ConfigDict(populate_by_name=True)

    connector_type: ConnectorType = Field(default="postgresql", alias="connectorType")
    name: str

    # SQL databases (postgresql, mysql, sqlserver)
    host: str = ""
    port: int = 5432
    database: str = ""
    user: str = ""
    password: str = ""
    ssl: bool = False

    # Cosmos DB
    endpoint: str = ""
    account_key: str = Field(default="", alias="accountKey")
    container: str = ""  # default container (optional)

    # MongoDB
    connection_string: str = Field(default="", alias="connectionString")
    auth_source: str = Field(default="admin", alias="authSource")

    # Power BI
    tenant_id: str = Field(default="", alias="tenantId")
    client_id: str = Field(default="", alias="clientId")
    client_secret: str = Field(default="", alias="clientSecret")
    pbi_workspace_id: str = Field(default="", alias="pbiWorkspaceId")
    dataset_id: str = Field(default="", alias="datasetId")


class ConnectionInfo(BaseModel):
    id: str
    name: str
    connector_type: ConnectorType = Field(default="postgresql", alias="connectorType")
    host: str
    database: str
    status: Literal["connected", "disconnected"]

    model_config = ConfigDict(populate_by_name=True)


class ColumnInfo(BaseModel):
    name: str
    type: str
    is_primary_key: bool = False


class TableInfo(BaseModel):
    name: str
    columns: list[ColumnInfo]


class SchemaInfo(BaseModel):
    tables: list[TableInfo]
