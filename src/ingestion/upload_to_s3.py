from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError


PROCESSED_DIR = Path("data/processed")

# Stable object keys: reruns overwrite the same key (no duplicate filenames).
DATASET_OBJECTS = {
    "customers": "processed/customers/customers.csv",
    "subscriptions": "processed/subscriptions/subscriptions.csv",
    "billing": "processed/billing/billing.csv",
    "transactions": "processed/transactions/transactions.csv",
    "support_tickets": "processed/support_tickets/support_tickets.csv",
    "usage_events": "processed/usage_events/usage_events.csv",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def _load_dotenv_if_present() -> None:
    """Optionally load .env without requiring python-dotenv."""
    env_path = Path(".env")
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
            f"Set it in your shell or in a local .env file."
        )
    return value


def _local_path_for(dataset: str) -> Path:
    return PROCESSED_DIR / f"{dataset}.csv"


def _validate_local_files() -> list[tuple[str, Path, str]]:
    missing: list[str] = []
    uploads: list[tuple[str, Path, str]] = []

    for dataset, s3_key in DATASET_OBJECTS.items():
        local_path = _local_path_for(dataset)
        if not local_path.is_file():
            missing.append(str(local_path))
            continue
        uploads.append((dataset, local_path, s3_key))

    if missing:
        raise FileNotFoundError(
            "Required processed files are missing:\n  - "
            + "\n  - ".join(missing)
            + "\nRun data generation first, then retry S3 upload."
        )

    return uploads


def _create_s3_client(region: str):
    return boto3.client("s3", region_name=region)


def _ensure_private_bucket(s3_client, bucket: str, region: str) -> None:
    try:
        s3_client.head_bucket(Bucket=bucket)
        logger.info("Using existing S3 bucket s3://%s", bucket)
    except ClientError as exc:
        error_code = str(exc.response.get("Error", {}).get("Code", ""))
        http_status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")

        if error_code in {"403", "AccessDenied"} or http_status == 403:
            raise PermissionError(
                f"Access denied for bucket s3://{bucket}. "
                "Check IAM permissions or choose a bucket you own."
            ) from exc

        if error_code not in {"404", "NoSuchBucket"} and http_status != 404:
            raise

        logger.info("Bucket s3://%s not found; creating private bucket", bucket)
        create_kwargs: dict[str, object] = {"Bucket": bucket}
        if region != "us-east-1":
            create_kwargs["CreateBucketConfiguration"] = {
                "LocationConstraint": region
            }
        s3_client.create_bucket(**create_kwargs)

    # Always enforce Block Public Access on the project bucket.
    s3_client.put_public_access_block(
        Bucket=bucket,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    logger.info("Block Public Access enabled for s3://%s", bucket)


def upload_processed_datasets(s3_client, bucket: str) -> list[str]:
    uploads = _validate_local_files()
    uploaded_keys: list[str] = []

    for dataset, local_path, s3_key in uploads:
        destination = f"s3://{bucket}/{s3_key}"
        logger.info(
            "Uploading %s -> %s (%s bytes)",
            local_path,
            destination,
            local_path.stat().st_size,
        )
        s3_client.upload_file(
            Filename=str(local_path),
            Bucket=bucket,
            Key=s3_key,
        )
        uploaded_keys.append(s3_key)

    return uploaded_keys


def verify_uploaded_objects(s3_client, bucket: str, keys: list[str]) -> None:
    missing: list[str] = []

    for key in keys:
        try:
            response = s3_client.head_object(Bucket=bucket, Key=key)
            size = response.get("ContentLength", 0)
            logger.info("Verified s3://%s/%s (%s bytes)", bucket, key, size)
        except ClientError:
            missing.append(f"s3://{bucket}/{key}")

    if missing:
        raise RuntimeError(
            "S3 verification failed. Missing objects:\n  - "
            + "\n  - ".join(missing)
        )


def main() -> int:
    try:
        _load_dotenv_if_present()
        bucket = _require_env("S3_BUCKET_NAME")
        region = _require_env("AWS_REGION")

        credentials = boto3.session.Session().get_credentials()
        if credentials is None:
            raise NoCredentialsError()

        s3_client = _create_s3_client(region)
        _ensure_private_bucket(s3_client, bucket, region)
        uploaded_keys = upload_processed_datasets(s3_client, bucket)
        verify_uploaded_objects(s3_client, bucket, uploaded_keys)

        logger.info(
            "S3 ingestion complete. Uploaded and verified %s objects.",
            len(uploaded_keys),
        )
        return 0

    except NoCredentialsError:
        logger.error(
            "AWS credentials not found. Configure the AWS CLI profile, "
            "environment variables (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY), "
            "or another supported credential source. Do not hard-code keys."
        )
        return 1
    except (FileNotFoundError, ValueError, RuntimeError, PermissionError) as exc:
        logger.error("%s", exc)
        return 1
    except (ClientError, BotoCoreError) as exc:
        logger.error("AWS/S3 error during ingestion: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
