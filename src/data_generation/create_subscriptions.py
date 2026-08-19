import pandas as pd


def _snake_case(value: object) -> str:
    """
    Convert a categorical string like "Fiber optic" to "fiber_optic".
    """
    s = str(value).strip()
    return (
        s.replace("-", "_")
        .replace(" ", "_")
        .replace("/", "_")
        .lower()
    )


def _multiple_lines_status(value: object) -> str:
    s = str(value).strip()
    if s == "No phone service":
        return "no_phone_service"
    # "No" -> "no", "Yes" -> "yes"
    return _snake_case(s)


def _service_status(value: object) -> str:
    """
    Map Yes/No/No internet service into a normalized string status.
    """
    s = str(value).strip()
    if s == "Yes":
        return "enabled"
    if s == "No":
        return "disabled"
    # Includes "No internet service" and any unexpected categories.
    return _snake_case(s)


def create_subscriptions(df: pd.DataFrame) -> pd.DataFrame:
    subscriptions = df[
        [
            "customerID",
            "tenure",
            "PhoneService",
            "MultipleLines",
            "InternetService",
            "OnlineSecurity",
            "OnlineBackup",
            "DeviceProtection",
            "TechSupport",
            "StreamingTV",
            "StreamingMovies",
            "Contract",
            "MonthlyCharges",
        ]
    ].copy()

    subscriptions = subscriptions.rename(
        columns={
            "customerID": "customer_id",
            "tenure": "tenure_months",
            "PhoneService": "has_phone_service",
            "MultipleLines": "multiple_lines_status",
            "InternetService": "internet_service_type",
            "OnlineSecurity": "online_security_status",
            "OnlineBackup": "online_backup_status",
            "DeviceProtection": "device_protection_status",
            "TechSupport": "tech_support_status",
            "StreamingTV": "streaming_tv_status",
            "StreamingMovies": "streaming_movies_status",
            "Contract": "contract_type",
            "MonthlyCharges": "monthly_charges",
        }
    )

    # Types
    subscriptions["tenure_months"] = pd.to_numeric(
        subscriptions["tenure_months"], errors="coerce"
    ).astype("Int64")
    subscriptions["monthly_charges"] = pd.to_numeric(iujjdksw cc   vcxx
        _multiple_lines_status
    )
    subscriptions["internet_service_type"] = subscriptions["internet_service_type"].apply(
        _snake_case
    )

    service_status_columns = [
        "online_security_status",
        "online_backup_status",
        "device_protection_status",
        "tech_support_status",
        "streaming_tv_status",
        "streaming_movies_status",
    ]
    for col in service_status_columns:
        subscriptions[col] = subscriptions[col].apply(_service_status)

    subscriptions["contract_type"] = subscriptions["contract_type"].apply(_snake_case)

    return subscriptions

