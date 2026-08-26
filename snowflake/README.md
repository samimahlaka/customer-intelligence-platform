# Snowflake raw-layer ingestion (Phase 4)

Loads the six processed CSVs from the private S3 bucket into Snowflake `CIP_DB.RAW`
using an external stage and `COPY INTO`. AWS secrets are never hard-coded in SQL or
Python source.

## Prerequisites

1. Processed objects already in S3 (from `src/ingestion/upload_to_s3.py`)
2. Snowflake account with permission to create warehouse/database/schema, stages,
   file formats, tables, and run `COPY INTO`
3. AWS credentials that can read the processed S3 objects

## Environment

Extend `.env` (see repo `.env.example`):

```bash
# Existing S3 settings
S3_BUCKET_NAME=your-private-cip-bucket-name
AWS_REGION=us-east-1

# Snowflake connection (do not commit secrets)
SNOWFLAKE_ACCOUNT=xy12345.us-east-1
SNOWFLAKE_USER=your_user
SNOWFLAKE_PASSWORD=...                 # or use key-pair auth below
# SNOWFLAKE_PRIVATE_KEY_PATH=/path/to/rsa_key.p8
# SNOWFLAKE_PRIVATE_KEY_PASSPHRASE=... # if the key is encrypted
SNOWFLAKE_ROLE=ACCOUNTADMIN
SNOWFLAKE_WAREHOUSE=CIP_WH

# S3 auth mode for the Snowflake stage:
#   auto (default) | credentials | storage_integration
# SNOWFLAKE_S3_AUTH=auto
```

### S3 authentication modes

| Mode | Behavior |
|------|----------|
| `credentials` | Stage uses AWS keys from the default credential chain at runtime |
| `storage_integration` | Snowflake storage integration + IAM role trust (preferred with IAM admin) |
| `auto` | Tries storage integration first; falls back to runtime credentials if IAM is denied |

## Run

```bash
poetry install
poetry run python snowflake/load_from_s3.py
```

The loader is rerunnable: it upserts warehouse objects, refreshes stage auth,
recreates tables from the SQL definitions, truncates raw tables, and reloads via
`COPY INTO`.

## Layout

| Path | Purpose |
|------|---------|
| `sql/01_create_database_and_schema.sql` | Warehouse, database, `RAW` schema |
| `sql/02_create_storage_integration.sql` | S3 storage integration (IAM role) |
| `sql/03_create_file_format_and_stage.sql` | CSV format + stage (storage integration) |
| `sql/03_create_file_format_and_stage_credentials.sql` | CSV format + stage (runtime credentials) |
| `sql/04_create_raw_tables.sql` | Six raw tables |
| `sql/05_copy_into_raw.sql` | Truncate + `COPY INTO` |
| `sql/06_validate_load.sql` | Row counts + samples |
| `aws/*.json` | IAM trust + S3 read policy templates |
| `load_from_s3.py` | Orchestrates SQL + optional IAM + validation |

## Expected row counts

| Table | Rows |
|-------|------|
| `CUSTOMERS` | 7,043 |
| `SUBSCRIPTIONS` | 7,043 |
| `BILLING` | 7,043 |
| `TRANSACTIONS` | 227,990 |
| `SUPPORT_TICKETS` | 12,841 |
| `USAGE_EVENTS` | 730,822 |

dbt staging/analytics modeling is intentionally out of scope for this phase.
