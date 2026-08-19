from __future__ import annotations

from pathlib import Path

import pandas as pd


PROCESSED_DIR = Path("data/processed")
EXPECTED_CUSTOMER_ROWS = 7043


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
        # Fail fast if the column isn't numeric-ish.
        as_num = pd.to_numeric(df[col], errors="coerce")
        if as_num.isna().any():
            raise ValueError(f"{table_name}: `{col}` has non-numeric/NA values")
        if (as_num < 0).any():
            bad_rows = df.loc[as_num < 0, [col]].head(10).to_dict(orient="records")
            raise ValueError(f"{table_name}: `{col}` must be non-negative; examples: {bad_rows}")


def main() -> None:
    customers_path = PROCESSED_DIR / "customers.csv"
    subscriptions_path = PROCESSED_DIR / "subscriptions.csv"
    billing_path = PROCESSED_DIR / "billing.csv"

    customers = pd.read_csv(customers_path)
    subscriptions = pd.read_csv(subscriptions_path)
    billing = pd.read_csv(billing_path)

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

    # Row count consistency
    for df, name in [
        (customers, "customers"),
        (subscriptions, "subscriptions"),
        (billing, "billing"),
    ]:
        rows = len(df)
        if rows != EXPECTED_CUSTOMER_ROWS:
            raise ValueError(f"{name}: expected {EXPECTED_CUSTOMER_ROWS} rows, got {rows}")

    # customer_id checks
    _require_no_nulls(customers, ["customer_id"], "customers")
    _require_no_nulls(subscriptions, ["customer_id"], "subscriptions")
    _require_no_nulls(billing, ["customer_id"], "billing")
    _require_unique(customers, "customer_id", "customers")
    _require_unique(subscriptions, "customer_id", "subscriptions")
    _require_unique(billing, "customer_id", "billing")

    # Referential integrity: every subscriptions/billing customer exists in customers
    _require_coverage(subscriptions, "customer_id", customers, "customer_id")
    _require_coverage(billing, "customer_id", customers, "customer_id")

    # Numeric sanity: charges are non-negative
    _require_non_negative(subscriptions, ["monthly_charges"], "subscriptions")
    _require_non_negative(billing, ["total_charges"], "billing")

    # Unexpected nulls: require all expected columns to be non-null.
    _require_no_nulls(customers, expected_customer_cols, "customers")
    _require_no_nulls(subscriptions, expected_subscription_cols, "subscriptions")
    _require_no_nulls(billing, expected_billing_cols, "billing")

    print("Validation passed: processed tables are consistent.")


if __name__ == "__main__":
    main()

