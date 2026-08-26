from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

try:
    import snowflake.connector
except ImportError as exc:  # pragma: no cover - dependency install guidance
    raise SystemExit(
        "Missing dependency snowflake-connector-python. "
        "Install project deps with: poetry add snowflake-connector-python"
    ) from exc


ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = Path(__file__).resolve().parent / "sql"
AWS_DIR = Path(__file__).resolve().parent / "aws"

# Match validated processed CSV row counts (header excluded).
EXPECTED_COUNTS = {
    "customers": 7043,
    "subscriptions": 7043,
    "billing": 7043,
    "transactions": 227990,
    "support_tickets": 12841,
    "usage_events": 730822,
}

DEFAULT_ROLE_NAME = "cip-snowflake-s3-access"
DEFAULT_INTEGRATION_NAME = "CIP_S3_INTEGRATION"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def _load_dotenv_if_present() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(
            f"Missing required environment variable: {name}. "
            "Set it in your shell or in a local .env file."
        )
    return value


def _optional_env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value if value else default


def _render_template(text: str, mapping: dict[str, str]) -> str:
    rendered = text
    for key, value in mapping.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    leftover = re.findall(r"\{\{[A-Z0-9_]+\}\}", rendered)
    if leftover:
        raise ValueError(f"Unresolved SQL/JSON placeholders: {sorted(set(leftover))}")
    return rendered


def _read_sql(name: str, mapping: dict[str, str] | None = None) -> str:
    path = SQL_DIR / name
    text = path.read_text(encoding="utf-8")
    if mapping:
        text = _render_template(text, mapping)
    return text


def _split_sql_statements(sql_text: str) -> list[str]:
    """Split on semicolons while ignoring comment-only lines."""
    statements: list[str] = []
    buffer: list[str] = []

    for raw_line in sql_text.splitlines():
        line = raw_line
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        buffer.append(line)
        if ";" in line:
            chunk = "\n".join(buffer)
            parts = chunk.split(";")
            # Keep incomplete remainder (after last ;) in buffer.
            for part in parts[:-1]:
                stmt = part.strip()
                if stmt:
                    statements.append(stmt)
            buffer = [parts[-1]] if parts[-1].strip() else []

    trailing = "\n".join(buffer).strip()
    if trailing:
        statements.append(trailing)
    return statements


def _connect_snowflake():
    connect_kwargs: dict[str, object] = {
        "account": _require_env("SNOWFLAKE_ACCOUNT"),
        "user": _require_env("SNOWFLAKE_USER"),
        "warehouse": _optional_env("SNOWFLAKE_WAREHOUSE", "CIP_WH"),
        "role": _optional_env("SNOWFLAKE_ROLE", "ACCOUNTADMIN"),
        "session_parameters": {"QUERY_TAG": "cip_phase4_s3_load"},
    }

    private_key_path = os.environ.get("SNOWFLAKE_PRIVATE_KEY_PATH", "").strip()
    password = os.environ.get("SNOWFLAKE_PASSWORD", "").strip()

    if private_key_path:
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives import serialization

        key_bytes = Path(private_key_path).read_bytes()
        passphrase = os.environ.get("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE", "").encode() or None
        private_key = serialization.load_pem_private_key(
            key_bytes,
            password=passphrase,
            backend=default_backend(),
        )
        connect_kwargs["private_key"] = private_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    elif password:
        connect_kwargs["password"] = password
    else:
        raise ValueError(
            "Provide SNOWFLAKE_PASSWORD or SNOWFLAKE_PRIVATE_KEY_PATH "
            "(key-pair auth preferred)."
        )

    database = os.environ.get("SNOWFLAKE_DATABASE", "").strip()
    schema = os.environ.get("SNOWFLAKE_SCHEMA", "").strip()
    if database:
        connect_kwargs["database"] = database
    if schema:
        connect_kwargs["schema"] = schema

    logger.info(
        "Connecting to Snowflake account=%s user=%s role=%s",
        connect_kwargs["account"],
        connect_kwargs["user"],
        connect_kwargs["role"],
    )
    return snowflake.connector.connect(**connect_kwargs)


def _sql_preview(stmt: str, limit: int = 120) -> str:
    collapsed = " ".join(stmt.split())
    redacted = re.sub(
        r"(AWS_KEY_ID|AWS_SECRET_KEY|AWS_TOKEN)\s*=\s*'[^']*'",
        r"\1 = '***'",
        collapsed,
        flags=re.IGNORECASE,
    )
    return redacted[:limit] + ("..." if len(redacted) >= limit else "")


def _execute_sql_file(cursor, filename: str, mapping: dict[str, str] | None = None) -> None:
    sql_text = _read_sql(filename, mapping)
    statements = _split_sql_statements(sql_text)
    logger.info("Running %s (%s statements)", filename, len(statements))
    for stmt in statements:
        preview = _sql_preview(stmt)
        logger.info("SQL: %s", preview)
        cursor.execute(stmt)


def _desc_integration(cursor, integration_name: str) -> dict[str, str]:
    cursor.execute(f"DESC STORAGE INTEGRATION {integration_name}")
    rows = cursor.fetchall()
    props: dict[str, str] = {}
    for row in rows:
        # DESC returns (property, property_type, property_value, property_default)
        props[str(row[0])] = "" if row[2] is None else str(row[2])
    required = ("STORAGE_AWS_IAM_USER_ARN", "STORAGE_AWS_EXTERNAL_ID")
    missing = [key for key in required if not props.get(key)]
    if missing:
        raise RuntimeError(
            f"DESC STORAGE INTEGRATION {integration_name} missing: {missing}"
        )
    return props


def _bootstrap_trust_policy(account_id: str) -> str:
    """Temporary trust so the role can be created before Snowflake external ID exists."""
    return json.dumps(
        {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "BootstrapPlaceholder",
                    "Effect": "Allow",
                    "Principal": {"AWS": f"arn:aws:iam::{account_id}:root"},
                    "Action": "sts:AssumeRole",
                    "Condition": {
                        "StringEquals": {"sts:ExternalId": "cip-bootstrap-placeholder"}
                    },
                }
            ],
        }
    )


def _snowflake_trust_policy(snowflake_iam_user_arn: str, external_id: str) -> str:
    return _render_template(
        (AWS_DIR / "trust_policy.json").read_text(encoding="utf-8"),
        {
            "STORAGE_AWS_IAM_USER_ARN": snowflake_iam_user_arn,
            "STORAGE_AWS_EXTERNAL_ID": external_id,
        },
    )


def _ensure_iam_role(
    *,
    role_name: str,
    bucket: str,
    snowflake_iam_user_arn: str | None = None,
    external_id: str | None = None,
) -> str:
    iam = boto3.client("iam")
    sts = boto3.client("sts")
    account_id = sts.get_caller_identity()["Account"]
    role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"

    if snowflake_iam_user_arn and external_id:
        trust_policy = _snowflake_trust_policy(snowflake_iam_user_arn, external_id)
    else:
        trust_policy = _bootstrap_trust_policy(account_id)

    s3_policy = _render_template(
        (AWS_DIR / "s3_read_policy.json").read_text(encoding="utf-8"),
        {"S3_BUCKET_NAME": bucket},
    )

    try:
        iam.get_role(RoleName=role_name)
        logger.info("Updating trust policy on existing IAM role %s", role_name)
        iam.update_assume_role_policy(
            RoleName=role_name,
            PolicyDocument=trust_policy,
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "NoSuchEntity":
            raise
        logger.info("Creating IAM role %s for Snowflake S3 access", role_name)
        iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=trust_policy,
            Description="Snowflake storage integration access to CIP processed S3 data",
            MaxSessionDuration=3600,
        )

    iam.put_role_policy(
        RoleName=role_name,
        PolicyName="cip-snowflake-s3-read",
        PolicyDocument=s3_policy,
    )
    logger.info("Attached inline S3 read policy to role %s", role_name)
    return role_arn


def _wait_for_stage_list(cursor, attempts: int = 8, delay_seconds: float = 10.0) -> None:
    """IAM trust updates can take a short time to become usable by Snowflake."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            cursor.execute("LIST @CIP_S3_STAGE/customers/")
            rows = cursor.fetchall()
            if not rows:
                raise RuntimeError("Stage list returned no objects under customers/")
            logger.info(
                "Stage list succeeded (attempt %s/%s); sample object: %s",
                attempt,
                attempts,
                rows[0][0],
            )
            return
        except Exception as exc:  # noqa: BLE001 - retry until IAM settles
            last_error = exc
            logger.warning(
                "Stage list not ready yet (attempt %s/%s): %s",
                attempt,
                attempts,
                exc,
            )
            if attempt < attempts:
                time.sleep(delay_seconds)
    raise RuntimeError(
        "Unable to LIST @CIP_S3_STAGE after IAM/storage integration setup. "
        f"Last error: {last_error}"
    )


def _run_copy_and_collect(cursor) -> list[dict[str, object]]:
    sql_text = _read_sql("05_copy_into_raw.sql")
    statements = _split_sql_statements(sql_text)
    copy_results: list[dict[str, object]] = []

    for stmt in statements:
        preview = _sql_preview(stmt)
        logger.info("SQL: %s", preview)
        cursor.execute(stmt)
        if stmt.upper().lstrip().startswith("COPY INTO"):
            rows = cursor.fetchall()
            cols = [col[0] for col in cursor.description] if cursor.description else []
            for row in rows:
                record = dict(zip(cols, row))
                copy_results.append(record)
                errors = record.get("errors_seen") or record.get("ERRORS_SEEN") or 0
                status = str(record.get("status") or record.get("STATUS") or "")
                if int(errors) > 0 or status.upper().startswith("LOAD_FAILED"):
                    raise RuntimeError(f"COPY INTO reported load errors: {record}")
                logger.info("COPY result: %s", record)
    return copy_results


def _validate_counts(cursor) -> dict[str, int]:
    cursor.execute(
        """
        SELECT 'customers' AS table_name, COUNT(*) AS row_count FROM CUSTOMERS
        UNION ALL
        SELECT 'subscriptions', COUNT(*) FROM SUBSCRIPTIONS
        UNION ALL
        SELECT 'billing', COUNT(*) FROM BILLING
        UNION ALL
        SELECT 'transactions', COUNT(*) FROM TRANSACTIONS
        UNION ALL
        SELECT 'support_tickets', COUNT(*) FROM SUPPORT_TICKETS
        UNION ALL
        SELECT 'usage_events', COUNT(*) FROM USAGE_EVENTS
        """
    )
    counts = {str(name).lower(): int(count) for name, count in cursor.fetchall()}

    mismatches: list[str] = []
    for table, expected in EXPECTED_COUNTS.items():
        actual = counts.get(table)
        if actual != expected:
            mismatches.append(f"{table}: expected {expected}, got {actual}")

    if mismatches:
        raise RuntimeError(
            "Row-count validation failed:\n  - " + "\n  - ".join(mismatches)
        )

    # Confirm nullable open-ticket behavior survived the load.
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM SUPPORT_TICKETS
        WHERE STATUS = 'open' AND CLOSED_AT IS NULL
        """
    )
    open_null_closed = int(cursor.fetchone()[0])
    if open_null_closed <= 0:
        raise RuntimeError(
            "Expected open support tickets with NULL closed_at; found none."
        )

    logger.info("Validated row counts: %s", json.dumps(counts, sort_keys=True))
    logger.info("Open tickets with NULL closed_at: %s", open_null_closed)
    return counts


def _aws_session_credentials() -> dict[str, str]:
    session = boto3.session.Session()
    creds = session.get_credentials()
    if creds is None:
        raise RuntimeError(
            "AWS credentials not found. Configure the AWS CLI profile or "
            "environment variables before creating the Snowflake stage."
        )
    frozen = creds.get_frozen_credentials()
    payload = {
        "AWS_KEY_ID": frozen.access_key,
        "AWS_SECRET_KEY": frozen.secret_key,
    }
    if frozen.token:
        # Escape single quotes for SQL literal safety.
        token = frozen.token.replace("'", "''")
        payload["AWS_TOKEN_CLAUSE"] = f"AWS_TOKEN = '{token}'"
    else:
        payload["AWS_TOKEN_CLAUSE"] = ""
    return payload


def _resolve_s3_auth_mode() -> str:
    """
    SNOWFLAKE_S3_AUTH:
      - credentials (default): stage uses AWS credential chain at runtime
      - storage_integration: IAM role + Snowflake storage integration
      - auto: try storage_integration, fall back to credentials on IAM denial
    """
    mode = _optional_env("SNOWFLAKE_S3_AUTH", "auto").lower()
    if mode not in {"auto", "credentials", "storage_integration"}:
        raise ValueError(
            "SNOWFLAKE_S3_AUTH must be one of: auto, credentials, storage_integration"
        )
    return mode


def _setup_stage_with_storage_integration(
    cursor,
    *,
    bucket: str,
    role_name: str,
    integration_name: str,
) -> None:
    role_arn = _ensure_iam_role(role_name=role_name, bucket=bucket)
    mapping = {
        "S3_BUCKET_NAME": bucket,
        "STORAGE_AWS_ROLE_ARN": role_arn,
    }
    _execute_sql_file(cursor, "02_create_storage_integration.sql", mapping)

    integration_props = _desc_integration(cursor, integration_name)
    snowflake_user_arn = integration_props["STORAGE_AWS_IAM_USER_ARN"]
    external_id = integration_props["STORAGE_AWS_EXTERNAL_ID"]
    logger.info("Snowflake IAM user ARN: %s", snowflake_user_arn)

    _ensure_iam_role(
        role_name=role_name,
        bucket=bucket,
        snowflake_iam_user_arn=snowflake_user_arn,
        external_id=external_id,
    )
    _execute_sql_file(cursor, "03_create_file_format_and_stage.sql", mapping)
    _wait_for_stage_list(cursor)


def _setup_stage_with_credentials(cursor, *, bucket: str) -> None:
    aws_creds = _aws_session_credentials()
    # Escape secrets for SQL string literals.
    mapping = {
        "S3_BUCKET_NAME": bucket,
        "AWS_KEY_ID": aws_creds["AWS_KEY_ID"].replace("'", "''"),
        "AWS_SECRET_KEY": aws_creds["AWS_SECRET_KEY"].replace("'", "''"),
        "AWS_TOKEN_CLAUSE": aws_creds["AWS_TOKEN_CLAUSE"],
    }
    logger.info(
        "Creating external stage with runtime AWS credentials "
        "(not stored in source files)"
    )
    _execute_sql_file(
        cursor,
        "03_create_file_format_and_stage_credentials.sql",
        mapping,
    )
    cursor.execute("LIST @CIP_S3_STAGE/customers/")
    rows = cursor.fetchall()
    if not rows:
        raise RuntimeError("Stage list returned no objects under customers/")
    logger.info("Stage list succeeded; sample object: %s", rows[0][0])


def main() -> int:
    try:
        _load_dotenv_if_present()

        bucket = _require_env("S3_BUCKET_NAME")
        role_name = _optional_env("SNOWFLAKE_S3_ROLE_NAME", DEFAULT_ROLE_NAME)
        integration_name = _optional_env(
            "SNOWFLAKE_STORAGE_INTEGRATION",
            DEFAULT_INTEGRATION_NAME,
        )
        auth_mode = _resolve_s3_auth_mode()

        conn = _connect_snowflake()
        try:
            cursor = conn.cursor()
            _execute_sql_file(cursor, "01_create_database_and_schema.sql")

            if auth_mode == "credentials":
                _setup_stage_with_credentials(cursor, bucket=bucket)
            elif auth_mode == "storage_integration":
                _setup_stage_with_storage_integration(
                    cursor,
                    bucket=bucket,
                    role_name=role_name,
                    integration_name=integration_name,
                )
            else:
                try:
                    logger.info(
                        "SNOWFLAKE_S3_AUTH=auto: trying storage integration first"
                    )
                    _setup_stage_with_storage_integration(
                        cursor,
                        bucket=bucket,
                        role_name=role_name,
                        integration_name=integration_name,
                    )
                except ClientError as exc:
                    error_code = str(exc.response.get("Error", {}).get("Code", ""))
                    if error_code not in {
                        "AccessDenied",
                        "UnauthorizedOperation",
                        "NoSuchEntity",
                    }:
                        raise
                    logger.warning(
                        "IAM role setup denied (%s); falling back to runtime "
                        "AWS credentials for the external stage.",
                        error_code or exc,
                    )
                    _setup_stage_with_credentials(cursor, bucket=bucket)

            _execute_sql_file(cursor, "04_create_raw_tables.sql")
            _run_copy_and_collect(cursor)
            counts = _validate_counts(cursor)
            _execute_sql_file(cursor, "06_validate_load.sql")

            logger.info(
                "Snowflake raw load complete. Tables: %s",
                ", ".join(f"{k}={v}" for k, v in sorted(counts.items())),
            )
            return 0
        finally:
            conn.close()

    except ValueError as exc:
        logger.error("%s", exc)
        return 1
    except ClientError as exc:
        logger.error("AWS IAM/S3 error during Snowflake setup: %s", exc)
        return 1
    except Exception as exc:  # noqa: BLE001 - top-level CLI failure path
        logger.error("Snowflake ingestion failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
