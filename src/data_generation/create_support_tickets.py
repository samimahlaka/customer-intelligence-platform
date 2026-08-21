from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from data_generation.create_transactions import SNAPSHOT_DATE


RANDOM_SEED = 42
BASE_TICKET_RATE_PER_MONTH = 0.04
MAX_TICKETS_PER_CUSTOMER = 8
OPEN_TICKET_LOOKBACK_DAYS = 30

ISSUE_TYPES = ("billing", "technical", "service", "account", "cancellation")
PRIORITIES = ("low", "medium", "high")
STATUSES = ("closed", "open", "escalated")

EMPTY_COLUMNS = [
    "ticket_id",
    "customer_id",
    "created_at",
    "closed_at",
    "issue_type",
    "priority",
    "status",
    "resolution_time_hours",
    "satisfaction_score",
]


def _ticket_rate_multiplier(
    internet_service_type: str,
    tech_support_status: str,
    monthly_charges: float,
) -> float:
    multiplier = 1.0

    if internet_service_type == "fiber_optic":
        multiplier *= 1.4
    if tech_support_status == "disabled":
        multiplier *= 1.5
    elif tech_support_status == "enabled":
        multiplier *= 0.7
    if monthly_charges >= 80:
        multiplier *= 1.2

    return multiplier


def _sample_issue_type(
    rng: np.random.Generator,
    internet_service_type: str,
    tech_support_status: str,
    monthly_charges: float,
) -> str:
    if internet_service_type == "no":
        weights = np.array([0.35, 0.05, 0.20, 0.34, 0.06])
    elif internet_service_type == "fiber_optic" and tech_support_status == "disabled":
        weights = np.array([0.18, 0.42, 0.18, 0.16, 0.06])
    elif monthly_charges >= 80:
        weights = np.array([0.38, 0.20, 0.18, 0.18, 0.06])
    else:
        weights = np.array([0.24, 0.24, 0.24, 0.22, 0.06])

    return str(rng.choice(ISSUE_TYPES, p=weights / weights.sum()))


def _sample_priority(rng: np.random.Generator, issue_type: str) -> str:
    if issue_type in {"technical", "cancellation"}:
        weights = np.array([0.20, 0.45, 0.35])
    elif issue_type == "billing":
        weights = np.array([0.30, 0.50, 0.20])
    else:
        weights = np.array([0.45, 0.40, 0.15])

    return str(rng.choice(PRIORITIES, p=weights))


def _sample_status(rng: np.random.Generator) -> str:
    # ~85% closed, ~10% escalated, ~5% open
    return str(rng.choice(STATUSES, p=[0.85, 0.05, 0.10]))


def _sample_resolution_hours(
    rng: np.random.Generator, priority: str, status: str
) -> float:
    if status == "escalated" or priority == "high":
        low, high = 24.0, 168.0
    elif priority == "medium":
        low, high = 12.0, 96.0
    else:
        low, high = 4.0, 48.0

    return float(rng.uniform(low, high))


def _sample_satisfaction(
    rng: np.random.Generator,
    status: str,
    priority: str,
    resolution_hours: float,
) -> int:
    score = 4.0

    if status == "escalated":
        score -= 1.2
    if priority == "high":
        score -= 0.4
    if resolution_hours > 72:
        score -= 0.8
    elif resolution_hours > 36:
        score -= 0.3
    elif resolution_hours < 12:
        score += 0.5

    score += float(rng.normal(0.0, 0.35))
    return int(np.clip(round(score), 1, 5))


def _sample_created_at(
    rng: np.random.Generator,
    window_start: pd.Timestamp,
    window_end: pd.Timestamp,
    status: str,
) -> pd.Timestamp:
    if status == "open":
        open_start = max(
            window_start,
            window_end - pd.Timedelta(days=OPEN_TICKET_LOOKBACK_DAYS),
        )
        start = open_start
    else:
        start = window_start

    start_ns = int(pd.Timestamp(start).value)
    end_ns = int(pd.Timestamp(window_end).value)
    if end_ns <= start_ns:
        return pd.Timestamp(window_end).floor("s")

    created_ns = int(rng.integers(start_ns, end_ns + 1))
    return pd.Timestamp(created_ns).floor("s")


def create_support_tickets(subscriptions: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(RANDOM_SEED)
    snapshot = pd.Timestamp(SNAPSHOT_DATE)
    rows: list[dict[str, object]] = []

    ticket_inputs = subscriptions[
        [
            "customer_id",
            "tenure_months",
            "internet_service_type",
            "tech_support_status",
            "monthly_charges",
        ]
    ].copy()

    for record in ticket_inputs.itertuples(index=False):
        tenure_months = int(record.tenure_months)
        if tenure_months <= 0:
            continue

        window_end = snapshot
        window_start = snapshot - pd.DateOffset(months=tenure_months)

        multiplier = _ticket_rate_multiplier(
            record.internet_service_type,
            record.tech_support_status,
            float(record.monthly_charges),
        )
        expected_tickets = BASE_TICKET_RATE_PER_MONTH * tenure_months * multiplier
        ticket_count = int(
            min(rng.poisson(expected_tickets), MAX_TICKETS_PER_CUSTOMER)
        )
        if ticket_count <= 0:
            continue

        for ticket_idx in range(1, ticket_count + 1):
            issue_type = _sample_issue_type(
                rng,
                record.internet_service_type,
                record.tech_support_status,
                float(record.monthly_charges),
            )
            priority = _sample_priority(rng, issue_type)
            status = _sample_status(rng)
            created_at = _sample_created_at(rng, window_start, window_end, status)

            if status == "open":
                closed_at = pd.NaT
                resolution_time_hours = np.nan
                satisfaction_score = pd.NA
            else:
                resolution_time_hours = _sample_resolution_hours(rng, priority, status)
                closed_at = created_at + timedelta(hours=resolution_time_hours)
                if closed_at > window_end:
                    closed_at = window_end
                    resolution_time_hours = max(
                        (closed_at - created_at).total_seconds() / 3600.0,
                        0.0,
                    )
                satisfaction_score = _sample_satisfaction(
                    rng, status, priority, resolution_time_hours
                )

            rows.append(
                {
                    "ticket_id": (
                        f"tkt_{record.customer_id}_"
                        f"{created_at.strftime('%Y%m%d')}_{ticket_idx:02d}"
                    ),
                    "customer_id": record.customer_id,
                    "created_at": created_at,
                    "closed_at": closed_at,
                    "issue_type": issue_type,
                    "priority": priority,
                    "status": status,
                    "resolution_time_hours": (
                        None
                        if pd.isna(resolution_time_hours)
                        else round(float(resolution_time_hours), 2)
                    ),
                    "satisfaction_score": satisfaction_score,
                }
            )

    tickets = pd.DataFrame(rows)
    if tickets.empty:
        return pd.DataFrame(columns=EMPTY_COLUMNS)

    tickets["created_at"] = pd.to_datetime(tickets["created_at"])
    tickets["closed_at"] = pd.to_datetime(tickets["closed_at"])
    tickets["resolution_time_hours"] = pd.to_numeric(
        tickets["resolution_time_hours"], errors="coerce"
    )
    tickets["satisfaction_score"] = pd.to_numeric(
        tickets["satisfaction_score"], errors="coerce"
    ).astype("Int64")

    return tickets.sort_values(
        ["customer_id", "created_at", "ticket_id"]
    ).reset_index(drop=True)
