from __future__ import annotations

import numpy as np
import pandas as pd

from data_generation.create_transactions import SNAPSHOT_DATE


RANDOM_SEED = 42

EVENT_TYPE_UNITS = {
    "data_usage": "gb",
    "voice_minutes": "minutes",
    "sms_count": "count",
    "streaming_hours": "hours",
}
EVENT_TYPES = tuple(EVENT_TYPE_UNITS.keys())

EMPTY_COLUMNS = [
    "event_id",
    "customer_id",
    "event_date",
    "billing_period",
    "event_type",
    "quantity",
    "unit",
]


def _enabled(status: object) -> bool:
    return str(status) == "enabled"


def _sample_quantities(
    rng: np.random.Generator,
    event_type: str,
    internet_types: np.ndarray,
    monthly_charges: np.ndarray,
) -> np.ndarray:
    charge_factor = 0.85 + np.minimum(monthly_charges.astype(float), 120.0) / 200.0

    if event_type == "data_usage":
        base = np.where(internet_types == "fiber_optic", 80.0, 35.0)
        sigma = 0.35
        raw = rng.lognormal(mean=np.log(base), sigma=sigma)
        return np.round(raw * charge_factor, 2)

    if event_type == "voice_minutes":
        raw = rng.lognormal(mean=np.log(180.0), sigma=0.40, size=len(monthly_charges))
        return np.round(raw * charge_factor, 1)

    if event_type == "sms_count":
        raw = rng.lognormal(mean=np.log(45.0), sigma=0.50, size=len(monthly_charges))
        return np.maximum(np.round(raw * charge_factor), 0.0)

    base = np.where(internet_types == "fiber_optic", 40.0, 18.0)
    raw = rng.lognormal(mean=np.log(base), sigma=0.40)
    return np.round(raw * charge_factor, 1)


def create_usage_events(subscriptions: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(RANDOM_SEED)
    snapshot = pd.Timestamp(SNAPSHOT_DATE)

    active = subscriptions.loc[
        subscriptions["tenure_months"].astype(int) > 0,
        [
            "customer_id",
            "tenure_months",
            "has_phone_service",
            "internet_service_type",
            "streaming_tv_status",
            "streaming_movies_status",
            "monthly_charges",
        ],
    ].copy()

    if active.empty:
        return pd.DataFrame(columns=EMPTY_COLUMNS)

    active["tenure_months"] = active["tenure_months"].astype(int)
    active["has_phone_service"] = active["has_phone_service"].astype(bool)
    active["has_streaming"] = active["streaming_tv_status"].map(_enabled) | active[
        "streaming_movies_status"
    ].map(_enabled)
    active["has_internet"] = active["internet_service_type"].isin(
        ["dsl", "fiber_optic"]
    )

    month_offsets = np.concatenate(
        [np.arange(tenure, dtype=int) for tenure in active["tenure_months"].to_numpy()]
    )
    repeat_counts = active["tenure_months"].to_numpy()

    total_months = (
        snapshot.year * 12 + (snapshot.month - 1) - month_offsets.astype(int)
    )
    years = total_months // 12
    months = total_months % 12 + 1
    event_dates = (
        pd.to_datetime({"year": years, "month": months, "day": 1})
        + pd.offsets.MonthEnd(0)
    ).dt.normalize()

    month_frame = pd.DataFrame(
        {
            "customer_id": np.repeat(active["customer_id"].to_numpy(), repeat_counts),
            "event_date": event_dates,
            "internet_service_type": np.repeat(
                active["internet_service_type"].to_numpy(), repeat_counts
            ),
            "monthly_charges": np.repeat(
                active["monthly_charges"].to_numpy(), repeat_counts
            ),
            "has_phone_service": np.repeat(
                active["has_phone_service"].to_numpy(), repeat_counts
            ),
            "has_internet": np.repeat(active["has_internet"].to_numpy(), repeat_counts),
            "has_streaming": np.repeat(
                active["has_streaming"].to_numpy(), repeat_counts
            ),
        }
    )
    month_frame["billing_period"] = month_frame["event_date"].dt.strftime("%Y-%m")

    event_frames: list[pd.DataFrame] = []

    def _append_event_type(mask: pd.Series, event_type: str) -> None:
        subset = month_frame.loc[mask, [
            "customer_id",
            "event_date",
            "billing_period",
            "internet_service_type",
            "monthly_charges",
        ]].copy()
        if subset.empty:
            return

        quantities = _sample_quantities(
            rng,
            event_type,
            subset["internet_service_type"].to_numpy(),
            subset["monthly_charges"].to_numpy(),
        )
        subset["event_type"] = event_type
        subset["quantity"] = quantities
        subset["unit"] = EVENT_TYPE_UNITS[event_type]
        subset["event_id"] = (
            "usage_"
            + subset["customer_id"].astype(str)
            + "_"
            + subset["billing_period"]
            + "_"
            + event_type
        )
        event_frames.append(
            subset[
                [
                    "event_id",
                    "customer_id",
                    "event_date",
                    "billing_period",
                    "event_type",
                    "quantity",
                    "unit",
                ]
            ]
        )

    _append_event_type(month_frame["has_internet"], "data_usage")
    _append_event_type(month_frame["has_phone_service"], "voice_minutes")
    _append_event_type(month_frame["has_phone_service"], "sms_count")
    _append_event_type(
        month_frame["has_internet"] & month_frame["has_streaming"],
        "streaming_hours",
    )

    if not event_frames:
        return pd.DataFrame(columns=EMPTY_COLUMNS)

    usage_events = pd.concat(event_frames, ignore_index=True)
    usage_events["quantity"] = pd.to_numeric(usage_events["quantity"])

    return usage_events.sort_values(
        ["customer_id", "event_date", "event_type"]
    ).reset_index(drop=True)
