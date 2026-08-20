from __future__ import annotations

from datetime import date

import pandas as pd


SNAPSHOT_DATE = date(2024, 12, 31)
AUTOPAY_METHODS = {"bank_transfer_automatic", "credit_card_automatic"}


def _generate_monthly_dates(snapshot_date: date, tenure_months: int) -> list[pd.Timestamp]:
    snapshot = pd.Timestamp(snapshot_date)
    return [
        (snapshot - pd.DateOffset(months=offset)).normalize()
        for offset in range(tenure_months)
    ]


def _allocate_amounts(total_charges: float, tenure_months: int) -> list[float]:
    total_cents = int(round(total_charges * 100))
    base_cents, remainder = divmod(total_cents, tenure_months)

    amounts = []
    for month_idx in range(tenure_months):
        cents = base_cents + (1 if month_idx < remainder else 0)
        amounts.append(cents / 100)
    return amounts


def create_transactions(
    subscriptions: pd.DataFrame, billing: pd.DataFrame
) -> pd.DataFrame:
    transaction_inputs = subscriptions[
        [
            "customer_id",
            "tenure_months",
        ]
    ].merge(
        billing[
            [
                "customer_id",
                "payment_method",
                "total_charges",
            ]
        ],
        on="customer_id",
        how="inner",
    )

    rows: list[dict[str, object]] = []

    for record in transaction_inputs.itertuples(index=False):
        tenure_months = int(record.tenure_months)
        if tenure_months <= 0:
            continue

        monthly_dates = _generate_monthly_dates(SNAPSHOT_DATE, tenure_months)
        monthly_amounts = _allocate_amounts(float(record.total_charges), tenure_months)
        is_autopay = record.payment_method in AUTOPAY_METHODS

        for idx, (txn_date, amount) in enumerate(
            zip(monthly_dates, monthly_amounts, strict=True),
            start=1,
        ):
            billing_period = txn_date.strftime("%Y-%m")
            rows.append(
                {
                    "transaction_id": f"txn_{record.customer_id}_{billing_period}_{idx:02d}",
                    "customer_id": record.customer_id,
                    "transaction_date": txn_date.date().isoformat(),
                    "billing_period": billing_period,
                    "amount": amount,
                    "payment_method": record.payment_method,
                    "payment_status": "completed",
                    "is_autopay": is_autopay,
                }
            )

    transactions = pd.DataFrame(rows)

    if transactions.empty:
        return pd.DataFrame(
            columns=[
                "transaction_id",
                "customer_id",
                "transaction_date",
                "billing_period",
                "amount",
                "payment_method",
                "payment_status",
                "is_autopay",
            ]
        )

    transactions["transaction_date"] = pd.to_datetime(transactions["transaction_date"])
    transactions["amount"] = pd.to_numeric(transactions["amount"])
    transactions["is_autopay"] = transactions["is_autopay"].astype(bool)

    transactions = transactions.sort_values(
        ["customer_id", "transaction_date"],
    ).reset_index(drop=True)

    return transactions
