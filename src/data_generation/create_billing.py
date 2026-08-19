import pandas as pd


def _snake_case(value: object) -> str:
    s = str(value).strip()
    return (
        s.replace("-", "_")
        .replace(" ", "_")
        .replace("/", "_")
        .replace("(", "")
        .replace(")", "")
        .lower()
    )


def create_billing(df: pd.DataFrame) -> pd.DataFrame:
    billing = df[
        [
            "customerID",
            "PaperlessBilling",
            "PaymentMethod",
            "TotalCharges",
        ]
    ].copy()

    billing = billing.rename(
        columns={
            "customerID": "customer_id",
            "PaperlessBilling": "paperless_billing",
            "PaymentMethod": "payment_method",
            "TotalCharges": "total_charges",
        }
    )

    billing["paperless_billing"] = billing["paperless_billing"] == "Yes"
    billing["payment_method"] = billing["payment_method"].apply(_snake_case)

    # The source dataset has 11 blank total_charges values for new customers
    # with zero tenure. We normalize those startup rows to 0.0.
    billing["total_charges"] = pd.to_numeric(
        billing["total_charges"].replace(r"^\s*$", pd.NA, regex=True),
        errors="coerce",
    ).fillna(0.0)

    return billing
