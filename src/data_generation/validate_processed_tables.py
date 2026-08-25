from __future__ import annotations

from pathlib import Path

import pandas as pd

from data_generation.create_transactions import AUTOPAY_METHODS, SNAPSHOT_DATE
from data_generation.create_support_tickets import (
    ISSUE_TYPES,
    PRIORITIES,
    STATUSES,
)
from data_generation.create_usage_events import EVENT_TYPE_UNITS, EVENT_TYPES


PROCESSED_DIR = Path("data/processed")
EXPECTED_CUSTOMER_ROWS = 7043
AMOUNT_RECONCILE_TOLERANCE = 0.01


def _require_columns(df: pd.DataFrame, required: list[str], table_name: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"{table_name}: missing required columns: {missing}")


def _require_no_nulls(df: pd.DataFrame, columns: list[str], table_name: str) -> None:
    null_counts = df[columns].isna().sum()
    null_columns = null_counts[null_counts > 0]
    if not null_columns.empty:
        preview = null_columns.head(10).to_dict()
        raise ValueError(
            f"{table_name}: unexpected nulls in columns (showing up to 10): {preview}"
        )


def _require_unique(df: pd.DataFrame, column: str, table_name: str) -> None:
    if df[column].duplicated().any():
        dup_ids = df.loc[df[column].duplicated(), column].head(10).tolist()
        raise ValueError(
            f"{table_name}: `{column}` must be unique; examples: {dup_ids}"
        )


def _require_coverage(
    df_left: pd.DataFrame, left_key: str, df_right: pd.DataFrame, right_key: str
) -> None:
    right_ids = set(df_right[right_key].tolist())
    left_ids = set(df_left[left_key].tolist())
    missing = left_ids - right_ids
    if missing:
        missing_list = list(sorted(missing))[:10]
        raise ValueError(f"Missing `{left_key}` in base table; examples: {missing_list}")


def _require_non_negative(df: pd.DataFrame, columns: list[str], table_name: str) -> None:
    for col in columns:
        as_num = pd.to_numeric(df[col], errors="coerce")
        if as_num.isna().any():
            raise ValueError(f"{table_name}: `{col}` has non-numeric/NA values")
        if (as_num < 0).any():
            bad_rows = df.loc[as_num < 0, [col]].head(10).to_dict(orient="records")
            raise ValueError(
                f"{table_name}: `{col}` must be non-negative; examples: {bad_rows}"
            )


def _validate_transactions(
    transactions: pd.DataFrame,
    customers: pd.DataFrame,
    subscriptions: pd.DataFrame,
    billing: pd.DataFrame,
) -> None:
    expected_transaction_cols = [
        "transaction_id",
        "customer_id",
        "transaction_date",
        "billing_period",
        "amount",
        "payment_method",
        "payment_status",
        "is_autopay",
    ]

    _require_columns(transactions, expected_transaction_cols, "transactions")
    _require_no_nulls(transactions, expected_transaction_cols, "transactions")
    _require_unique(transactions, "transaction_id", "transactions")
    _require_coverage(transactions, "customer_id", customers, "customer_id")
    _require_non_negative(transactions, ["amount"], "transactions")

    txn_counts = (
        transactions.groupby("customer_id", as_index=False)
        .size()
        .rename(columns={"size": "transaction_count"})
    )
    txn_sums = (
        transactions.groupby("customer_id", as_index=False)["amount"]
        .sum()
        .rename(columns={"amount": "transaction_amount_sum"})
    )

    expected = subscriptions[["customer_id", "tenure_months"]].merge(
        billing[["customer_id", "total_charges", "payment_method"]],
        on="customer_id",
        how="inner",
    )
    expected = expected.merge(txn_counts, on="customer_id", how="left")
    expected = expected.merge(txn_sums, on="customer_id", how="left")
    expected["transaction_count"] = expected["transaction_count"].fillna(0).astype(int)
    expected["transaction_amount_sum"] = expected["transaction_amount_sum"].fillna(0.0)

    bad_counts = expected[
        expected["transaction_count"] != expected["tenure_months"].astype(int)
    ]
    if not bad_counts.empty:
        preview = bad_counts[
            ["customer_id", "tenure_months", "transaction_count"]
        ].head(10).to_dict(orient="records")
        raise ValueError(
            "transactions: transaction counts do not match tenure_months; "
            f"examples: {preview}"
        )

    amount_gap = (expected["transaction_amount_sum"] - expected["total_charges"]).abs()
    bad_amounts = expected[amount_gap > AMOUNT_RECONCILE_TOLERANCE]
    if not bad_amounts.empty:
        preview = bad_amounts[
            [
                "customer_id",
                "total_charges",
                "transaction_amount_sum",
                "tenure_months",
            ]
        ].head(10).to_dict(orient="records")
        raise ValueError(
            "transactions: amounts do not reconcile to total_charges; "
            f"examples: {preview}"
        )

    txn_methods = (
        transactions.groupby("customer_id")["payment_method"]
        .nunique()
        .reset_index(name="payment_method_nunique")
    )
    multi_method = txn_methods[txn_methods["payment_method_nunique"] > 1]
    if not multi_method.empty:
        preview = multi_method.head(10).to_dict(orient="records")
        raise ValueError(
            "transactions: customer has multiple payment_method values; "
            f"examples: {preview}"
        )

    txn_method_lookup = (
        transactions[["customer_id", "payment_method"]]
        .drop_duplicates(subset=["customer_id"])
        .rename(columns={"payment_method": "txn_payment_method"})
    )
    method_check = expected.merge(txn_method_lookup, on="customer_id", how="left")
    method_mismatch = method_check[
        (method_check["tenure_months"].astype(int) > 0)
        & (method_check["txn_payment_method"] != method_check["payment_method"])
    ]
    if not method_mismatch.empty:
        preview = method_mismatch[
            ["customer_id", "payment_method", "txn_payment_method"]
        ].head(10).to_dict(orient="records")
        raise ValueError(
            "transactions: payment_method does not match billing; "
            f"examples: {preview}"
        )

    expected_autopay = transactions["payment_method"].isin(AUTOPAY_METHODS)
    bad_autopay = transactions[transactions["is_autopay"] != expected_autopay]
    if not bad_autopay.empty:
        preview = bad_autopay[
            ["customer_id", "payment_method", "is_autopay"]
        ].head(10).to_dict(orient="records")
        raise ValueError(
            "transactions: is_autopay inconsistent with payment_method; "
            f"examples: {preview}"
        )

    expected_rows = int(subscriptions["tenure_months"].sum())
    actual_rows = len(transactions)
    if actual_rows != expected_rows:
        raise ValueError(
            "transactions: expected "
            f"{expected_rows} rows from sum(tenure_months), got {actual_rows}"
        )


def _validate_support_tickets(
    support_tickets: pd.DataFrame,
    customers: pd.DataFrame,
    subscriptions: pd.DataFrame,
) -> None:
    expected_ticket_cols = [
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

    _require_columns(support_tickets, expected_ticket_cols, "support_tickets")
    _require_unique(support_tickets, "ticket_id", "support_tickets")
    _require_coverage(support_tickets, "customer_id", customers, "customer_id")

    required_non_null = [
        "ticket_id",
        "customer_id",
        "created_at",
        "issue_type",
        "priority",
        "status",
    ]
    _require_no_nulls(support_tickets, required_non_null, "support_tickets")

    invalid_issue = ~support_tickets["issue_type"].isin(ISSUE_TYPES)
    if invalid_issue.any():
        preview = support_tickets.loc[invalid_issue, "issue_type"].head(10).tolist()
        raise ValueError(f"support_tickets: invalid issue_type values: {preview}")

    invalid_priority = ~support_tickets["priority"].isin(PRIORITIES)
    if invalid_priority.any():
        preview = support_tickets.loc[invalid_priority, "priority"].head(10).tolist()
        raise ValueError(f"support_tickets: invalid priority values: {preview}")

    invalid_status = ~support_tickets["status"].isin(STATUSES)
    if invalid_status.any():
        preview = support_tickets.loc[invalid_status, "status"].head(10).tolist()
        raise ValueError(f"support_tickets: invalid status values: {preview}")

    tickets = support_tickets.copy()
    tickets["created_at"] = pd.to_datetime(tickets["created_at"])
    tickets["closed_at"] = pd.to_datetime(tickets["closed_at"], errors="coerce")

    open_mask = tickets["status"] == "open"
    closedish_mask = ~open_mask

    if tickets.loc[open_mask, "closed_at"].notna().any():
        raise ValueError("support_tickets: open tickets must have null closed_at")
    if tickets.loc[open_mask, "resolution_time_hours"].notna().any():
        raise ValueError(
            "support_tickets: open tickets must have null resolution_time_hours"
        )
    if tickets.loc[open_mask, "satisfaction_score"].notna().any():
        raise ValueError(
            "support_tickets: open tickets must have null satisfaction_score"
        )

    if tickets.loc[closedish_mask, "closed_at"].isna().any():
        raise ValueError(
            "support_tickets: closed/escalated tickets must have closed_at"
        )
    if tickets.loc[closedish_mask, "resolution_time_hours"].isna().any():
        raise ValueError(
            "support_tickets: closed/escalated tickets must have resolution_time_hours"
        )
    if tickets.loc[closedish_mask, "satisfaction_score"].isna().any():
        raise ValueError(
            "support_tickets: closed/escalated tickets must have satisfaction_score"
        )

    bad_resolution = tickets.loc[
        closedish_mask & (tickets["resolution_time_hours"] < 0)
    ]
    if not bad_resolution.empty:
        preview = bad_resolution.head(10).to_dict(orient="records")
        raise ValueError(
            "support_tickets: resolution_time_hours must be non-negative; "
            f"examples: {preview}"
        )

    score = pd.to_numeric(tickets["satisfaction_score"], errors="coerce")
    bad_scores = tickets.loc[
        closedish_mask & ((score < 1) | (score > 5))
    ]
    if not bad_scores.empty:
        preview = bad_scores.head(10).to_dict(orient="records")
        raise ValueError(
            "support_tickets: satisfaction_score must be between 1 and 5; "
            f"examples: {preview}"
        )

    chronology = tickets.loc[
        closedish_mask & (tickets["closed_at"] < tickets["created_at"])
    ]
    if not chronology.empty:
        preview = chronology[
            ["ticket_id", "created_at", "closed_at"]
        ].head(10).to_dict(orient="records")
        raise ValueError(
            f"support_tickets: closed_at before created_at; examples: {preview}"
        )

    tenure_lookup = subscriptions.set_index("customer_id")["tenure_months"].to_dict()
    snapshot = pd.Timestamp(SNAPSHOT_DATE)

    zero_tenure_ids = {
        customer_id
        for customer_id, tenure in tenure_lookup.items()
        if int(tenure) <= 0
    }
    if zero_tenure_ids:
        bad_zero = tickets[tickets["customer_id"].isin(zero_tenure_ids)]
        if not bad_zero.empty:
            preview = bad_zero["customer_id"].head(10).tolist()
            raise ValueError(
                "support_tickets: tenure=0 customers must have 0 tickets; "
                f"examples: {preview}"
            )

    for row in tickets.itertuples(index=False):
        tenure_months = int(tenure_lookup[row.customer_id])
        window_start = snapshot - pd.DateOffset(months=tenure_months)
        created_at = pd.Timestamp(row.created_at)
        if created_at < window_start or created_at > snapshot:
            raise ValueError(
                "support_tickets: created_at outside tenure window for "
                f"{row.ticket_id}"
            )
        if pd.notna(row.closed_at):
            closed_at = pd.Timestamp(row.closed_at)
            if closed_at > snapshot:
                raise ValueError(
                    "support_tickets: closed_at after snapshot for "
                    f"{row.ticket_id}"
                )


def _validate_usage_events(
    usage_events: pd.DataFrame,
    customers: pd.DataFrame,
    subscriptions: pd.DataFrame,
) -> None:
    expected_usage_cols = [
        "event_id",
        "customer_id",
        "event_date",
        "billing_period",
        "event_type",
        "quantity",
        "unit",
    ]

    _require_columns(usage_events, expected_usage_cols, "usage_events")
    _require_no_nulls(usage_events, expected_usage_cols, "usage_events")
    _require_unique(usage_events, "event_id", "usage_events")
    _require_coverage(usage_events, "customer_id", customers, "customer_id")
    _require_non_negative(usage_events, ["quantity"], "usage_events")

    invalid_type = ~usage_events["event_type"].isin(EVENT_TYPES)
    if invalid_type.any():
        preview = usage_events.loc[invalid_type, "event_type"].head(10).tolist()
        raise ValueError(f"usage_events: invalid event_type values: {preview}")

    unit_mismatch = usage_events[
        usage_events["unit"] != usage_events["event_type"].map(EVENT_TYPE_UNITS)
    ]
    if not unit_mismatch.empty:
        preview = unit_mismatch[
            ["event_id", "event_type", "unit"]
        ].head(10).to_dict(orient="records")
        raise ValueError(
            f"usage_events: unit does not match event_type; examples: {preview}"
        )

    events = usage_events.copy()
    events["event_date"] = pd.to_datetime(events["event_date"])
    period_mismatch = events[
        events["billing_period"] != events["event_date"].dt.strftime("%Y-%m")
    ]
    if not period_mismatch.empty:
        preview = period_mismatch[
            ["event_id", "event_date", "billing_period"]
        ].head(10).to_dict(orient="records")
        raise ValueError(
            "usage_events: billing_period does not match event_date; "
            f"examples: {preview}"
        )

    tenure_lookup = subscriptions.set_index("customer_id")["tenure_months"].to_dict()
    service_lookup = subscriptions.set_index("customer_id")[
        [
            "has_phone_service",
            "internet_service_type",
            "streaming_tv_status",
            "streaming_movies_status",
        ]
    ].to_dict(orient="index")
    snapshot = pd.Timestamp(SNAPSHOT_DATE)

    zero_tenure_ids = {
        customer_id
        for customer_id, tenure in tenure_lookup.items()
        if int(tenure) <= 0
    }
    if zero_tenure_ids:
        bad_zero = events[events["customer_id"].isin(zero_tenure_ids)]
        if not bad_zero.empty:
            preview = bad_zero["customer_id"].head(10).tolist()
            raise ValueError(
                "usage_events: tenure=0 customers must have 0 events; "
                f"examples: {preview}"
            )

    for row in events.itertuples(index=False):
        tenure_months = int(tenure_lookup[row.customer_id])
        window_start = snapshot - pd.DateOffset(months=tenure_months)
        event_date = pd.Timestamp(row.event_date)
        if event_date < window_start or event_date > snapshot:
            raise ValueError(
                f"usage_events: event_date outside tenure window for {row.event_id}"
            )

        service = service_lookup[row.customer_id]
        internet = service["internet_service_type"]
        has_phone = bool(service["has_phone_service"])
        has_streaming = (
            service["streaming_tv_status"] == "enabled"
            or service["streaming_movies_status"] == "enabled"
        )

        if row.event_type == "data_usage" and internet not in {"dsl", "fiber_optic"}:
            raise ValueError(
                f"usage_events: data_usage without internet for {row.event_id}"
            )
        if row.event_type in {"voice_minutes", "sms_count"} and not has_phone:
            raise ValueError(
                f"usage_events: phone event without phone service for {row.event_id}"
            )
        if row.event_type == "streaming_hours" and (
            internet not in {"dsl", "fiber_optic"} or not has_streaming
        ):
            raise ValueError(
                f"usage_events: streaming_hours without streaming/internet for "
                f"{row.event_id}"
            )


def main() -> None:
    customers_path = PROCESSED_DIR / "customers.csv"
    subscriptions_path = PROCESSED_DIR / "subscriptions.csv"
    billing_path = PROCESSED_DIR / "billing.csv"
    transactions_path = PROCESSED_DIR / "transactions.csv"
    support_tickets_path = PROCESSED_DIR / "support_tickets.csv"
    usage_events_path = PROCESSED_DIR / "usage_events.csv"

    customers = pd.read_csv(customers_path)
    subscriptions = pd.read_csv(subscriptions_path)
    billing = pd.read_csv(billing_path)
    transactions = pd.read_csv(transactions_path)
    support_tickets = pd.read_csv(support_tickets_path)
    usage_events = pd.read_csv(usage_events_path)

    expected_customer_cols = [
        "customer_id",
        "gender",
        "is_senior_citizen",
        "has_partner",
        "has_dependents",
        "is_churned",
    ]
    expected_subscription_cols = [
        "customer_id",
        "tenure_months",
        "has_phone_service",
        "multiple_lines_status",
        "internet_service_type",
        "online_security_status",
        "online_backup_status",
        "device_protection_status",
        "tech_support_status",
        "streaming_tv_status",
        "streaming_movies_status",
        "contract_type",
        "monthly_charges",
    ]
    expected_billing_cols = [
        "customer_id",
        "paperless_billing",
        "payment_method",
        "total_charges",
    ]

    _require_columns(customers, expected_customer_cols, "customers")
    _require_columns(subscriptions, expected_subscription_cols, "subscriptions")
    _require_columns(billing, expected_billing_cols, "billing")

    for df, name in [
        (customers, "customers"),
        (subscriptions, "subscriptions"),
        (billing, "billing"),
    ]:
        rows = len(df)
        if rows != EXPECTED_CUSTOMER_ROWS:
            raise ValueError(
                f"{name}: expected {EXPECTED_CUSTOMER_ROWS} rows, got {rows}"
            )

    _require_no_nulls(customers, ["customer_id"], "customers")
    _require_no_nulls(subscriptions, ["customer_id"], "subscriptions")
    _require_no_nulls(billing, ["customer_id"], "billing")
    _require_unique(customers, "customer_id", "customers")
    _require_unique(subscriptions, "customer_id", "subscriptions")
    _require_unique(billing, "customer_id", "billing")

    _require_coverage(subscriptions, "customer_id", customers, "customer_id")
    _require_coverage(billing, "customer_id", customers, "customer_id")

    _require_non_negative(subscriptions, ["monthly_charges"], "subscriptions")
    _require_non_negative(billing, ["total_charges"], "billing")

    _require_no_nulls(customers, expected_customer_cols, "customers")
    _require_no_nulls(subscriptions, expected_subscription_cols, "subscriptions")
    _require_no_nulls(billing, expected_billing_cols, "billing")

    _validate_transactions(transactions, customers, subscriptions, billing)
    _validate_support_tickets(support_tickets, customers, subscriptions)
    _validate_usage_events(usage_events, customers, subscriptions)

    print("Validation passed: processed tables are consistent.")
    print(f"Transactions rows validated: {len(transactions)}")
    print(f"Support tickets rows validated: {len(support_tickets)}")
    print(f"Usage events rows validated: {len(usage_events)}")


if __name__ == "__main__":
    main()
