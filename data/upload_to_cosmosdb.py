"""Upload Agentic AP Excel reports into Azure Cosmos DB."""

import json
import uuid

import pandas as pd
from azure.cosmos import CosmosClient, PartitionKey, exceptions

# ── Cosmos DB connection ─────────────────────────────────────────────
import os

ENDPOINT = os.environ.get("COSMOS_ENDPOINT", "https://your-cosmos-account.documents.azure.com:443/")
KEY = os.environ.get("COSMOS_KEY", "your-cosmos-primary-key")
DATABASE_NAME = os.environ.get("COSMOS_DATABASE", "agentic_ap_workspace")

DATA_DIR = os.environ.get("DATA_DIR", "./data")

# ── Connect ──────────────────────────────────────────────────────────
print("Connecting to Cosmos DB...")
client = CosmosClient(ENDPOINT, KEY)

# ── Create database ──────────────────────────────────────────────────
print(f"Creating database: {DATABASE_NAME}")
try:
    database = client.create_database(DATABASE_NAME)
    print(f"  Database '{DATABASE_NAME}' created.")
except exceptions.CosmosResourceExistsError:
    database = client.get_database_client(DATABASE_NAME)
    print(f"  Database '{DATABASE_NAME}' already exists, using existing.")

# ── Container 1: accuracy_report ─────────────────────────────────────
ACCURACY_CONTAINER = "accuracy_report"
print(f"\nCreating container: {ACCURACY_CONTAINER}")
try:
    accuracy_container = database.create_container(
        id=ACCURACY_CONTAINER,
        partition_key=PartitionKey(path="/tenant_id"),
    )
    print(f"  Container '{ACCURACY_CONTAINER}' created with partition key /tenant_id")
except exceptions.CosmosResourceExistsError:
    accuracy_container = database.get_container_client(ACCURACY_CONTAINER)
    print(f"  Container '{ACCURACY_CONTAINER}' already exists, using existing.")

# ── Container 2: bucket_report ───────────────────────────────────────
BUCKET_CONTAINER = "bucket_report"
print(f"\nCreating container: {BUCKET_CONTAINER}")
try:
    bucket_container = database.create_container(
        id=BUCKET_CONTAINER,
        partition_key=PartitionKey(path="/tenant"),
    )
    print(f"  Container '{BUCKET_CONTAINER}' created with partition key /tenant")
except exceptions.CosmosResourceExistsError:
    bucket_container = database.get_container_client(BUCKET_CONTAINER)
    print(f"  Container '{BUCKET_CONTAINER}' already exists, using existing.")

# ── Helper: convert DataFrame row to Cosmos document ─────────────────
def row_to_document(row: dict, doc_id: str | None = None) -> dict:
    """Convert a pandas row dict to a Cosmos DB document."""
    doc = {}
    for key, value in row.items():
        # Parse JSON strings back into native objects
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, (dict, list)):
                    doc[key] = parsed
                    continue
            except (json.JSONDecodeError, TypeError):
                pass
        # Handle NaN / None
        if pd.isna(value):
            doc[key] = None
        else:
            doc[key] = value

    # Cosmos DB requires an 'id' field
    doc["id"] = doc_id or str(uuid.uuid4())
    return doc


# ── Upload Accuracy Report ───────────────────────────────────────────
print(f"\nUploading accuracy report...")
df_accuracy = pd.read_excel(f"{DATA_DIR}/agentic_accuracy_report.xlsx", engine="openpyxl")
print(f"  Read {len(df_accuracy)} rows from Excel")

success_count = 0
error_count = 0
for idx, row in df_accuracy.iterrows():
    doc = row_to_document(row.to_dict(), doc_id=row["case_id"])
    try:
        accuracy_container.upsert_item(doc)
        success_count += 1
        if success_count % 50 == 0:
            print(f"  ...uploaded {success_count}/{len(df_accuracy)} documents")
    except Exception as e:
        error_count += 1
        if error_count <= 3:
            print(f"  ERROR on row {idx}: {e}")

print(f"  Accuracy Report: {success_count} uploaded, {error_count} errors")

# ── Upload Bucket Report ─────────────────────────────────────────────
print(f"\nUploading bucket report...")
df_bucket = pd.read_excel(f"{DATA_DIR}/agentic_bucket_report.xlsx", engine="openpyxl")
print(f"  Read {len(df_bucket)} rows from Excel")

success_count = 0
error_count = 0
for idx, row in df_bucket.iterrows():
    doc = row_to_document(row.to_dict(), doc_id=f"bucket-{row['case_id']}")
    try:
        bucket_container.upsert_item(doc)
        success_count += 1
        if success_count % 50 == 0:
            print(f"  ...uploaded {success_count}/{len(df_bucket)} documents")
    except Exception as e:
        error_count += 1
        if error_count <= 3:
            print(f"  ERROR on row {idx}: {e}")

print(f"  Bucket Report: {success_count} uploaded, {error_count} errors")

# ── Verify ───────────────────────────────────────────────────────────
print(f"\n--- Verification ---")
acc_count = list(accuracy_container.query_items(
    query="SELECT VALUE COUNT(1) FROM c",
    enable_cross_partition_query=True,
))
bkt_count = list(bucket_container.query_items(
    query="SELECT VALUE COUNT(1) FROM c",
    enable_cross_partition_query=True,
))
print(f"  accuracy_report container: {acc_count[0]} documents")
print(f"  bucket_report container:   {bkt_count[0]} documents")

# Sample one document from each
sample_acc = list(accuracy_container.query_items(
    query="SELECT TOP 1 * FROM c",
    enable_cross_partition_query=True,
))
if sample_acc:
    doc = sample_acc[0]
    print(f"\n  Sample accuracy doc:")
    print(f"    case_number: {doc.get('case_number')}")
    print(f"    tenant_id:   {doc.get('tenant_id')}")
    print(f"    bucket:      {doc.get('bucket')}")
    print(f"    accuracy:    {doc.get('header_accuracy_pct')}%")
    fla = doc.get("field_level_accuracy", {})
    if isinstance(fla, dict):
        print(f"    fields:      {len([k for k in fla if not k.endswith('_agenticAI')])} actual + AI predictions")

sample_bkt = list(bucket_container.query_items(
    query="SELECT TOP 1 * FROM c",
    enable_cross_partition_query=True,
))
if sample_bkt:
    doc = sample_bkt[0]
    print(f"\n  Sample bucket doc:")
    print(f"    case_number:    {doc.get('case_number')}")
    print(f"    bucket:         {doc.get('bucket')}")
    print(f"    expense_type:   {doc.get('expense_type')}")
    print(f"    errors:         {doc.get('no_of_errors')}")
    print(f"    error_reasons:  {doc.get('error_reason_list')}")

print("\nDone!")
