-- Phase 4: Snowflake storage integration for private S3 access.
-- Uses an IAM role trust (no access keys in SQL).
-- Placeholders are substituted by snowflake/load_from_s3.py:
--   {{STORAGE_AWS_ROLE_ARN}}  e.g. arn:aws:iam::123:role/cip-snowflake-s3-access
--   {{S3_BUCKET_NAME}}        e.g. cip-mahlaka-processed-532687321994
--
-- After first create, DESC INTEGRATION to obtain:
--   STORAGE_AWS_IAM_USER_ARN
--   STORAGE_AWS_EXTERNAL_ID
-- then update the IAM role trust policy (handled by the loader script).

CREATE STORAGE INTEGRATION IF NOT EXISTS CIP_S3_INTEGRATION
  TYPE = EXTERNAL_STAGE
  STORAGE_PROVIDER = 'S3'
  ENABLED = TRUE
  STORAGE_AWS_ROLE_ARN = '{{STORAGE_AWS_ROLE_ARN}}'
  STORAGE_ALLOWED_LOCATIONS = ('s3://{{S3_BUCKET_NAME}}/processed/')
  COMMENT = 'Read-only access to CIP processed S3 objects';

-- Keep allowed locations / role ARN in sync on reruns.
ALTER STORAGE INTEGRATION CIP_S3_INTEGRATION
  SET
    STORAGE_AWS_ROLE_ARN = '{{STORAGE_AWS_ROLE_ARN}}'
    STORAGE_ALLOWED_LOCATIONS = ('s3://{{S3_BUCKET_NAME}}/processed/')
    ENABLED = TRUE;
