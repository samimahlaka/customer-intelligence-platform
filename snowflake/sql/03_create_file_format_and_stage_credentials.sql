-- Phase 4: CSV file format + external stage (runtime AWS credentials).
-- Credentials are injected by snowflake/load_from_s3.py from the AWS
-- default credential chain — never committed in source.
-- Placeholders:
--   {{S3_BUCKET_NAME}}
--   {{AWS_KEY_ID}}
--   {{AWS_SECRET_KEY}}
--   {{AWS_TOKEN_CLAUSE}}   -- either empty or: AWS_TOKEN = '...'

USE DATABASE CIP_DB;
USE SCHEMA RAW;

CREATE OR REPLACE FILE FORMAT CIP_CSV_FORMAT
  TYPE = CSV
  FIELD_DELIMITER = ','
  SKIP_HEADER = 1
  FIELD_OPTIONALLY_ENCLOSED_BY = '"'
  ESCAPE_UNENCLOSED_FIELD = NONE
  NULL_IF = ('', 'NULL', 'null')
  EMPTY_FIELD_AS_NULL = TRUE
  TRIM_SPACE = TRUE
  ERROR_ON_COLUMN_COUNT_MISMATCH = TRUE
  DATE_FORMAT = 'AUTO'
  TIMESTAMP_FORMAT = 'AUTO'
  COMMENT = 'CSV format for CIP processed datasets';

CREATE OR REPLACE STAGE CIP_S3_STAGE
  URL = 's3://{{S3_BUCKET_NAME}}/processed/'
  CREDENTIALS = (
    AWS_KEY_ID = '{{AWS_KEY_ID}}'
    AWS_SECRET_KEY = '{{AWS_SECRET_KEY}}'
    {{AWS_TOKEN_CLAUSE}}
  )
  FILE_FORMAT = CIP_CSV_FORMAT
  COMMENT = 'External stage over CIP processed/ S3 prefix (runtime credentials)';
