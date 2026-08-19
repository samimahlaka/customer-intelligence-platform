from pathlib import Path

import pandas as pd

from data_generation.create_customers import create_customers


RAW_DATA_PATH = Path(
    "data/raw/telco_churn/WA_Fn-UseC_-Telco-Customer-Churn.csv"
)

OUTPUT_DIR = Path("data/processed")


def main() -> None:
    df = pd.read_csv(RAW_DATA_PATH)

    customers = create_customers(df)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    output_path = OUTPUT_DIR / "customers.csv"
    customers.to_csv(output_path, index=False)

    print(f"Created {output_path}")
    print(f"Rows: {len(customers)}")
    print(customers.head())


if __name__ == "__main__":
    main()