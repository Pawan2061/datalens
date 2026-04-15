"""Generate dummy Excel files for Agentic AP workspace."""

import json
import random
import uuid
from datetime import datetime, timedelta

import pandas as pd

random.seed(42)

# ── Constants ────────────────────────────────────────────────────────

TENANTS = ["Infosys-NA", "Infosys-EU", "Infosys-APAC", "Infosys-UK", "Infosys-ANZ"]
BUCKETS = ["Ready to Post", "Failed Validations", "Missing Information"]
BUCKET_WEIGHTS = [0.55, 0.25, 0.20]  # 55% ready, 25% failed, 20% missing

EXPENSE_TYPES = [
    "Maintenance", "Warehouse", "Vehicle Rental", "IT Services",
    "Office Supplies", "Utilities", "Professional Services",
    "Travel & Lodging", "Freight & Shipping", "Consulting",
    "Equipment Lease", "Telecom", "Insurance", "Facilities",
]

COMPANY_CODES = ["INF001", "INF002", "INF003", "TCS001", "WIP001", "HCL001", "COG001", "INF004", "INF005"]
VENDOR_NAMES = [
    "Acme Corp", "Global Supplies Ltd", "TechParts Inc", "Metro Logistics",
    "Prime Industrial", "Atlas Equipment", "Nexus Services", "Pinnacle Solutions",
    "Sterling Materials", "Vertex Distribution", "Quantum Fleet", "Apex Facilities",
    "Summit IT Solutions", "Pacific Freight Co", "Continental Leasing",
]
CURRENCIES = ["USD", "EUR", "GBP", "INR", "AUD"]
GL_ACCOUNTS = ["510100", "520200", "530300", "540400", "550500", "560600", "570700", "580800"]
COST_CENTERS = ["CC1001", "CC1002", "CC2001", "CC2002", "CC3001", "CC3002", "CC4001"]
PO_NUMBERS = [f"PO-{random.randint(400000, 499999)}" for _ in range(50)]

PROCESS_STATUSES = ["Completed", "In Review", "Pending", "Rejected", "Escalated"]
DOC_CATEGORIES = ["PO", "Non-PO"]
DOC_CATEGORY_WEIGHTS = [0.6, 0.4]

TRANSLATION_STATUSES = ["Completed", "Not Required", "Failed", "In Progress"]
EXTRACTION_STATUSES = ["Success", "Partial", "Failed"]
VALIDATION_STATUSES = ["Passed", "Failed", "Warnings"]
ENRICHMENT_STATUSES = ["Completed", "Partial", "Skipped", "Failed"]

ERROR_REASONS = [
    "Vendor ID mismatch",
    "PO number not found",
    "Amount exceeds tolerance",
    "GL account invalid",
    "Cost center missing",
    "Tax code mismatch",
    "Currency conversion error",
    "Duplicate invoice detected",
    "Missing payment terms",
    "Invalid date format",
    "Company code mismatch",
    "Quantity variance exceeded",
    "Unit price mismatch",
    "Missing goods receipt",
    "Vendor bank details missing",
]

# Fields that the Agentic AI extracts and validates
HEADER_FIELDS = [
    "company_code", "vendor_id", "vendor_name", "invoice_number",
    "invoice_date", "due_date", "currency", "total_amount",
    "tax_amount", "net_amount", "po_number", "payment_terms",
    "gl_account", "cost_center", "description",
]

NUM_CASES = 500
BASE_DATE = datetime(2025, 1, 1)


def random_date(start: datetime, days_range: int) -> datetime:
    return start + timedelta(days=random.randint(0, days_range))


def generate_field_accuracy() -> dict:
    """Generate a field-level accuracy dict: {field: value, field_agenticAI: predicted}."""
    fields = {}
    correct_count = 0
    for field in HEADER_FIELDS:
        if field == "company_code":
            actual = random.choice(COMPANY_CODES)
            predicted = actual if random.random() < 0.92 else random.choice(COMPANY_CODES)
        elif field == "vendor_id":
            actual = f"V{random.randint(10000, 99999)}"
            predicted = actual if random.random() < 0.90 else f"V{random.randint(10000, 99999)}"
        elif field == "vendor_name":
            actual = random.choice(VENDOR_NAMES)
            predicted = actual if random.random() < 0.94 else random.choice(VENDOR_NAMES)
        elif field == "invoice_number":
            actual = f"INV-{random.randint(100000, 999999)}"
            predicted = actual if random.random() < 0.96 else f"INV-{random.randint(100000, 999999)}"
        elif field == "invoice_date":
            dt = random_date(BASE_DATE, 400)
            actual = dt.strftime("%Y-%m-%d")
            predicted = actual if random.random() < 0.93 else (dt + timedelta(days=random.choice([-1, 1, 30]))).strftime("%Y-%m-%d")
        elif field == "due_date":
            dt = random_date(BASE_DATE + timedelta(days=30), 60)
            actual = dt.strftime("%Y-%m-%d")
            predicted = actual if random.random() < 0.91 else (dt + timedelta(days=random.choice([-7, 7]))).strftime("%Y-%m-%d")
        elif field == "currency":
            actual = random.choice(CURRENCIES)
            predicted = actual if random.random() < 0.97 else random.choice(CURRENCIES)
        elif field == "total_amount":
            actual = round(random.uniform(500, 150000), 2)
            predicted = actual if random.random() < 0.88 else round(actual * random.uniform(0.95, 1.05), 2)
        elif field == "tax_amount":
            actual = round(random.uniform(50, 15000), 2)
            predicted = actual if random.random() < 0.89 else round(actual * random.uniform(0.9, 1.1), 2)
        elif field == "net_amount":
            actual = round(random.uniform(450, 135000), 2)
            predicted = actual if random.random() < 0.90 else round(actual * random.uniform(0.95, 1.05), 2)
        elif field == "po_number":
            actual = random.choice(PO_NUMBERS) if random.random() < 0.6 else ""
            predicted = actual if random.random() < 0.85 else random.choice(PO_NUMBERS)
        elif field == "payment_terms":
            terms = ["Net 30", "Net 45", "Net 60", "Net 15", "Immediate"]
            actual = random.choice(terms)
            predicted = actual if random.random() < 0.91 else random.choice(terms)
        elif field == "gl_account":
            actual = random.choice(GL_ACCOUNTS)
            predicted = actual if random.random() < 0.87 else random.choice(GL_ACCOUNTS)
        elif field == "cost_center":
            actual = random.choice(COST_CENTERS)
            predicted = actual if random.random() < 0.86 else random.choice(COST_CENTERS)
        elif field == "description":
            descs = ["Monthly maintenance", "Equipment rental Q1", "IT support services",
                     "Freight charges", "Office supplies order", "Consulting engagement"]
            actual = random.choice(descs)
            predicted = actual if random.random() < 0.93 else random.choice(descs)
        else:
            actual = "N/A"
            predicted = actual

        fields[field] = actual
        fields[f"{field}_agenticAI"] = predicted
        if actual == predicted:
            correct_count += 1

    return fields, correct_count


# ── Generate Accuracy Report ─────────────────────────────────────────

accuracy_rows = []
for i in range(NUM_CASES):
    case_id = str(uuid.uuid4())[:12]
    case_number = f"CASE-{2025000 + i}"
    tenant = random.choice(TENANTS)
    bucket = random.choices(BUCKETS, weights=BUCKET_WEIGHTS, k=1)[0]

    field_dict, fields_correct = generate_field_accuracy()

    header_accuracy = round((fields_correct / len(HEADER_FIELDS)) * 100, 1)
    human_time_min = round(random.uniform(2, 45), 1) if bucket != "Ready to Post" else round(random.uniform(0.5, 5), 1)
    case_created = random_date(BASE_DATE, 400)
    ai_processed = case_created + timedelta(minutes=random.randint(1, 15))

    accuracy_rows.append({
        "case_id": case_id,
        "case_number": case_number,
        "tenant_id": tenant,
        "bucket": bucket,
        "field_level_accuracy": json.dumps(field_dict),
        "no_of_fields_correct": fields_correct,
        "total_fields": len(HEADER_FIELDS),
        "header_accuracy_pct": header_accuracy,
        "time_spent_by_human_min": human_time_min,
        "case_created_on": case_created.strftime("%Y-%m-%d %H:%M:%S"),
        "agentic_ai_processed_on": ai_processed.strftime("%Y-%m-%d %H:%M:%S"),
    })

df_accuracy = pd.DataFrame(accuracy_rows)

# ── Generate Bucket Report ───────────────────────────────────────────

bucket_rows = []
for i in range(NUM_CASES):
    case_id = accuracy_rows[i]["case_id"]
    case_number = accuracy_rows[i]["case_number"]
    bucket = accuracy_rows[i]["bucket"]
    tenant = accuracy_rows[i]["tenant_id"]

    process_status = "Completed" if bucket == "Ready to Post" else random.choice(PROCESS_STATUSES)
    doc_category = random.choices(DOC_CATEGORIES, weights=DOC_CATEGORY_WEIGHTS, k=1)[0]
    processing_time = accuracy_rows[i]["time_spent_by_human_min"]
    expense_type = random.choice(EXPENSE_TYPES)

    if bucket == "Ready to Post":
        num_errors = 0
        error_list = []
    elif bucket == "Failed Validations":
        num_errors = random.randint(1, 5)
        error_list = random.sample(ERROR_REASONS, min(num_errors, len(ERROR_REASONS)))
    else:  # Missing Information
        num_errors = random.randint(1, 3)
        error_list = random.sample(
            ["Cost center missing", "GL account invalid", "Missing payment terms",
             "Vendor bank details missing", "Missing goods receipt", "PO number not found"],
            min(num_errors, 6),
        )

    translation = random.choices(
        TRANSLATION_STATUSES, weights=[0.5, 0.35, 0.1, 0.05], k=1
    )[0]
    extraction = random.choices(
        EXTRACTION_STATUSES, weights=[0.75, 0.18, 0.07], k=1
    )[0]
    validation = "Passed" if bucket == "Ready to Post" else random.choices(
        VALIDATION_STATUSES, weights=[0.2, 0.5, 0.3], k=1
    )[0]
    enrichment = random.choices(
        ENRICHMENT_STATUSES, weights=[0.6, 0.2, 0.1, 0.1], k=1
    )[0]
    invoice_pages = random.choices(
        [1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 15],
        weights=[0.25, 0.25, 0.15, 0.1, 0.08, 0.05, 0.04, 0.03, 0.02, 0.02, 0.01],
        k=1,
    )[0]

    bucket_rows.append({
        "case_id": case_id,
        "case_number": case_number,
        "process_status": process_status,
        "document_category": doc_category,
        "bucket": bucket,
        "processing_time_min": processing_time,
        "expense_type": expense_type,
        "no_of_errors": num_errors,
        "error_reason_list": json.dumps(error_list),
        "translation_status": translation,
        "extraction_status": extraction,
        "validation_status": validation,
        "enrichment_status": enrichment,
        "invoice_pages": invoice_pages,
        "tenant": tenant,
    })

df_bucket = pd.DataFrame(bucket_rows)

# ── Write to Excel ───────────────────────────────────────────────────

output_dir = "C:/Users/naimi/Data Insights engine/data"

df_accuracy.to_excel(f"{output_dir}/agentic_accuracy_report.xlsx", index=False, engine="openpyxl")
df_bucket.to_excel(f"{output_dir}/agentic_bucket_report.xlsx", index=False, engine="openpyxl")

print(f"Accuracy Report: {len(df_accuracy)} rows")
print(f"  Columns: {list(df_accuracy.columns)}")
print(f"  Bucket distribution:\n{df_accuracy['bucket'].value_counts().to_string()}")
print(f"\nBucket Report: {len(df_bucket)} rows")
print(f"  Columns: {list(df_bucket.columns)}")
print(f"  Avg accuracy: {df_accuracy['header_accuracy_pct'].mean():.1f}%")
print(f"  Avg human time: {df_accuracy['time_spent_by_human_min'].mean():.1f} min")
