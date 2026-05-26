"""User management service — admin-driven CRUD against the users container.

Centralizes user lookups, creations, and customer_code assignments so the
admin and auth routes stay thin. Keeps DB-shape knowledge in one place so a
future persistence swap touches only this file.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.db.insight_db import insight_db
from app.schemas.persistence import UserDoc


def _clean(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if not k.startswith("_")}


def _normalize_email(email: str) -> str:
    return email.strip().lower()


async def find_user_by_email(email: str) -> dict | None:
    """Return the user doc for an email (case-insensitive), or None if absent."""
    if not insight_db.is_ready:
        return None
    e = _normalize_email(email)
    if not e:
        return None
    users = insight_db.container("users")
    results = list(
        users.query_items(
            query="SELECT * FROM c WHERE c.email = @email",
            parameters=[{"name": "@email", "value": e}],
            partition_key=e,
        )
    )
    return _clean(results[0]) if results else None


async def has_any_users() -> bool:
    """True if at least one user exists (used to gate the first-user bootstrap)."""
    if not insight_db.is_ready:
        return False
    users = insight_db.container("users")
    results = list(
        users.query_items(
            query="SELECT * FROM c", enable_cross_partition_query=True
        )
    )
    return len(results) > 0


async def create_user_for_customer(
    name: str,
    email: str,
    customer_code: str,
    *,
    role: str = "user",
    status: str = "active",
    avatar_url: str = "",
    max_questions_per_day: int = 0,
    max_tokens_per_day: int = 0,
    max_cost_usd_per_month: float = 0.0,
    expiry_date: str = "",
    password_hash: str = "",
) -> dict:
    """Create a new user bound to a customer. Caller must check for duplicates."""
    if not insight_db.is_ready:
        raise RuntimeError("Persistence not configured")

    user = UserDoc(
        email=_normalize_email(email),
        name=name.strip(),
        avatar_url=avatar_url,
        role=role,
        status=status,
        customer_code=customer_code.strip(),
        max_questions_per_day=max_questions_per_day,
        max_tokens_per_day=max_tokens_per_day,
        max_cost_usd_per_month=max_cost_usd_per_month,
        expiry_date=expiry_date,
        password_hash=password_hash,
    )
    users = insight_db.container("users")
    users.create_item(user.model_dump())
    return user.model_dump()


async def assign_customer_code(user_id: str, customer_code: str) -> dict | None:
    """Update a user's customer_code. Returns the updated doc, or None if missing."""
    if not insight_db.is_ready:
        return None
    users = insight_db.container("users")
    results = list(
        users.query_items(
            query="SELECT * FROM c WHERE c.id = @id",
            parameters=[{"name": "@id", "value": user_id}],
            enable_cross_partition_query=True,
        )
    )
    if not results:
        return None
    doc = results[0]
    doc["customer_code"] = customer_code.strip()
    users.upsert_item(doc)
    return _clean(doc)


async def list_users_by_customer(customer_code: str) -> list[dict]:
    """Return all users bound to a given customer_code."""
    if not insight_db.is_ready:
        return []
    users = insight_db.container("users")
    results = list(
        users.query_items(
            query="SELECT * FROM c WHERE c.customer_code = @code ORDER BY c.created_at DESC",
            parameters=[{"name": "@code", "value": customer_code.strip()}],
            enable_cross_partition_query=True,
        )
    )
    return [_clean(d) for d in results]


def touch_last_login(doc: dict) -> dict:
    """Mark the user as just logged in. Returns the mutated doc (also persists)."""
    if not insight_db.is_ready:
        return doc
    doc["last_login_at"] = datetime.now(timezone.utc).isoformat()
    users = insight_db.container("users")
    users.upsert_item(doc)
    return doc
