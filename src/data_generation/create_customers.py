import pandas as pd


def create_customers(df: pd.DataFrame) -> pd.DataFrame:
    customers = df[
        [
            "customerID",
            "gender",
            "SeniorCitizen",
            "Partner",
            "Dependents",
            "Churn",
        ]
    ].copy()

    customers = customers.rename(
        columns={
            "customerID": "customer_id",
            "SeniorCitizen": "is_senior_citizen",
            "Partner": "has_partner",
            "Dependents": "has_dependents",
            "Churn": "is_churned",
        }
    )

    customers["is_senior_citizen"] = customers["is_senior_citizen"].astype(bool)

    customers["has_partner"] = customers["has_partner"] == "Yes"

    customers["has_dependents"] = customers["has_dependents"] == "Yes"

    customers["is_churned"] = customers["is_churned"] == "Yes"

    return customers