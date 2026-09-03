# `core/db/write_v3`

Strict write layer for database output nodes.

## What it does
- supports `append`, `truncate`, `upsert`;
- uses typed request models instead of raw dicts;
- writes only to existing tables;
- avoids global accumulators and unbounded `pd.concat` buffering;
- raises explicit config, planning, execution, and dialect errors.

## Column mismatch policy
- `on_extra_df_columns="error"` keeps the default strict contract and fails on unknown DataFrame columns;
- `on_extra_df_columns="ignore"` drops DataFrame columns that do not exist in the target table;
- `on_missing_df_columns="ignore_if_default"` is the default and allows omitted target columns only when reflected metadata says the database can fill them (`nullable`, default, autoincrement, PK);
- `on_missing_df_columns="ignore"` skips the precheck and lets the database decide whether omitted columns are acceptable;
- `on_missing_df_columns="error"` fails fast on any target column missing from the DataFrame.

## Upsert contract
- v1 supports a single key column;
- duplicate keys in input are allowed;
- `NULL` keys are allowed and participate in matching as regular values;
- target rows with keys from the input are deleted first, then the full input batch is inserted as-is.

## Responsibility boundary
- `write_v3` does not create databases, schemas, or tables;
- all DDL operations live in `core/db/ddl`;
- missing target tables fail fast at planning time with an explicit error.
