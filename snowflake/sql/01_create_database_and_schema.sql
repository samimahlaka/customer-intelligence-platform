-- Phase 4: database / warehouse / schema scaffolding (rerunnable)
-- Creates the CIP warehouse objects used by the raw S3 load.

CREATE WAREHOUSE IF NOT EXISTS CIP_WH
  WITH
    WAREHOUSE_SIZE = 'XSMALL'
    AUTO_SUSPEND = 60
    AUTO_RESUME = TRUE
    INITIALLY_SUSPENDED = TRUE
    COMMENT = 'Customer Intelligence Platform compute';

CREATE DATABASE IF NOT EXISTS CIP_DB
  COMMENT = 'Customer Intelligence Platform';

CREATE SCHEMA IF NOT EXISTS CIP_DB.RAW
  COMMENT = 'Raw layer loaded from S3 processed CSVs';

USE WAREHOUSE CIP_WH;
USE DATABASE CIP_DB;
USE SCHEMA RAW;
