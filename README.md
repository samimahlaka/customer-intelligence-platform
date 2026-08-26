# Customer Intelligence Platform

Production-grade Customer Intelligence and Churn Prediction Platform combining data engineering, machine learning, MLOps, analytics, cloud, and Generative AI.

## Data generation

```bash
PYTHONPATH=src python src/data_generation/run_generation.py
PYTHONPATH=src python src/data_generation/validate_processed_tables.py
```

## S3 ingestion

Uploads the six processed CSVs from `data/processed/` to a private project bucket:

- `processed/customers/customers.csv`
- `processed/subscriptions/subscriptions.csv`
- `processed/billing/billing.csv`
- `processed/transactions/transactions.csv`
- `processed/support_tickets/support_tickets.csv`
- `processed/usage_events/usage_events.csv`

Configure environment variables (see `.env.example`):

```bash
export S3_BUCKET_NAME=your-private-cip-bucket-name
export AWS_REGION=us-east-1
```

Use the AWS default credential chain (CLI profile, SSO, or IAM role). Do not hard-code access keys.

```bash
PYTHONPATH=src python src/ingestion/upload_to_s3.py
```

The script creates the bucket if needed, enables Block Public Access, overwrites the same object keys on rerun, and verifies all six objects exist.

## Snowflake raw ingestion (S3 → Snowflake)

Loads the six processed S3 objects into `CIP_DB.RAW` via an external stage and
`COPY INTO`. AWS access uses a Snowflake storage integration + IAM role trust
(no hard-coded AWS keys). Details: `snowflake/README.md`.

```bash
# Add Snowflake connection settings to .env (see .env.example), then:
poetry run python snowflake/load_from_s3.py
```

This phase stops at the validated raw layer. dbt staging/analytics is next.
