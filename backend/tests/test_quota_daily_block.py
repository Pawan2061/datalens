"""Tests for the daily cost hard-block branch in auth.quota.check_quota.

The block is derived (no persistent flag): a regular customer is blocked once
today_cost_usd reaches cost_block_threshold_usd_per_day, unless an admin has
stamped cost_block_cleared_date == today. Privileged roles are never blocked.
"""
import asyncio
from datetime import datetime, timezone

from app.auth.quota import check_quota
from app.config import settings


TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
CAP = settings.cost_block_threshold_usd_per_day  # default 4.0


def _run(doc):
    return asyncio.run(check_quota(doc))


def _user(**over):
    doc = {"role": "user", "status": "active", "today_cost_usd": 0.0}
    doc.update(over)
    return doc


def test_below_cap_allowed():
    assert _run(_user(today_cost_usd=CAP - 0.5)).allowed is True


def test_at_cap_blocked():
    res = _run(_user(today_cost_usd=CAP))
    assert res.allowed is False
    assert "admin" in res.reason.lower()


def test_above_cap_blocked():
    assert _run(_user(today_cost_usd=CAP + 10)).allowed is False


def test_admin_cleared_today_not_blocked():
    # Admin re-approved today → block suppressed for the rest of the day.
    doc = _user(today_cost_usd=CAP + 5, cost_block_cleared_date=TODAY)
    assert _run(doc).allowed is True


def test_cleared_yesterday_reblocks():
    # A stale clear date (yesterday) must NOT suppress today's block.
    doc = _user(today_cost_usd=CAP + 1, cost_block_cleared_date="2000-01-01")
    assert _run(doc).allowed is False


def test_privileged_roles_never_blocked():
    for role in ("admin", "manager", "moderator"):
        doc = _user(role=role, today_cost_usd=CAP + 100)
        assert _run(doc).allowed is True, f"{role} should never be cost-blocked"


def test_zero_cap_disables_block(monkeypatch):
    monkeypatch.setattr(settings, "cost_block_threshold_usd_per_day", 0.0)
    assert _run(_user(today_cost_usd=999)).allowed is True
