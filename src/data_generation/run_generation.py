from pathlib import Path

import pandas as pd

from data_generation.create_billing import create_billing
from data_generation.create_customers import create_customers
from data_generation.create_subscriptions import create_subscriptions
from data_generation.create_transactions import create_transactions


RAW_DATA_PATH = Path(
    "data/raw/telco_churn/WA_Fn-UseC_-Telco-Customer-Churn.csv"
)

OUTPUT_DIR = Path("data/processed")


def main() -> None:
    df = pd.read_csv(RAW_DATA_PATH)

    customers = create_customers(df)
    subscriptions = create_subscriptions(df)
    billing = create_billing(df)
    transactions = create_transactions(subscriptions, billing)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    customers_output_path = OUTPUT_DIR / "customers.csv"
    customers.to_csv(customers_output_path, index=False)

    subscriptions_output_path = OUTPUT_DIR / "subscriptions.csv"
    subscriptions.to_csv(subscriptions_output_path, index=False)

    billing_output_path = OUTPUT_DIR / "billing.csv"
    billing.to_csv(billing_output_path, index=False)

    transactions_output_path = OUTPUT_DIR / "transactions.csv"
    transactions.to_csv(transactions_output_path, index=False)

    print(f"Created {customers_output_path}")
    print(f"Rows: {len(customers)}")
    print(f"Created {subscriptions_output_path}")
    print(f"Rows: {len(subscriptions)}")
    print(f"Created {billing_output_path}")
    print(f"Rows: {len(billing)}")
    print(f"Created {transactions_output_path}")
    print(f"Rows: {len(transactions)}")


if __name__ == "__main__":
    main()