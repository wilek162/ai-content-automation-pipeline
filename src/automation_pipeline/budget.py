"""Conservative USD reservations. Reservations are not provider invoices."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import sqlite3
from uuid import uuid4


def month():
    return datetime.now(timezone.utc).strftime("%Y-%m")


def money(value):
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("Invalid USD amount")
    if not amount.is_finite() or amount < 0:
        raise ValueError("USD amounts must be finite and nonnegative")
    return amount


def estimate(config, request):
    profile = config.get("budget", {})
    if not profile.get("enabled") or profile.get("model") != config.get("model"):
        raise ValueError("Paid execution disabled or model cost profile missing")
    datetime.strptime(profile["pricing_verified_on"], "%Y-%m-%d")
    # UTF-8 bytes plus request framing deliberately overestimate input tokens.
    from .state import canonical

    inputs = len(canonical(request).encode()) + 1024
    return (
        (
            money(profile["input_usd_per_million"]) * inputs
            + money(profile["output_usd_per_million"]) * config["max_output_tokens"]
        )
        / 1000000,
        money(profile["monthly_limit_usd"]),
    )


class LocalBudget:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS months (month TEXT PRIMARY KEY, reserved TEXT NOT NULL)")
            db.execute(
                "CREATE TABLE IF NOT EXISTS reservations (id TEXT PRIMARY KEY, month TEXT, amount TEXT)"
            )

    def connect(self):
        return sqlite3.connect(self.path, timeout=20, isolation_level=None)

    def initialize(self, period, baseline):
        datetime.strptime(period, "%Y-%m")
        baseline = money(baseline)
        with self.connect() as db:
            db.execute("INSERT INTO months VALUES (?, ?)", (period, str(baseline)))

    def reserve(self, amount, limit):
        amount, limit = money(amount), money(limit)
        identity = uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT reserved FROM months WHERE month=?", (month(),)).fetchone()
            if row is None:
                raise ValueError("Initialize the current UTC budget month before paid execution")
            total = money(row[0]) + amount
            if total > limit:
                raise ValueError("Monthly managed reservation limit exhausted")
            db.execute("UPDATE months SET reserved=? WHERE month=?", (str(total), month()))
            db.execute("INSERT INTO reservations VALUES (?, ?, ?)", (identity, month(), str(amount)))
            db.commit()
        return identity


class GitHubBudget:
    def __init__(self, store):
        self.store = store

    def initialize(self, period, baseline):
        datetime.strptime(period, "%Y-%m")
        path = f"budget/{period}.json"
        value, sha = self.store.get(path)
        if value is not None:
            raise ValueError("Budget month already initialized")
        self.store.put(path, {"reserved_usd": str(money(baseline)), "reservations": []}, sha)

    def reserve(self, amount, limit):
        from .integrations.github import Conflict

        amount, limit = money(amount), money(limit)
        path = f"budget/{month()}.json"
        for _ in range(4):
            ledger, sha = self.store.get(path)
            if ledger is None:
                raise ValueError("Initialize the current UTC GitHub budget month first")
            total = money(ledger["reserved_usd"]) + amount
            if total > limit:
                raise ValueError("Monthly managed reservation limit exhausted")
            identity = uuid4().hex
            ledger["reserved_usd"] = str(total)
            ledger["reservations"].append({"id": identity, "usd": str(amount)})
            try:
                self.store.put(path, ledger, sha)
                return identity
            except Conflict:
                continue
        raise ValueError("Budget changed concurrently; retry after reviewing state")
