# DB Fixture Specification

Use DB fixture commands only for developer or test setup. Creating a stored connection mutates the
local DVT database. Seeding creates or changes a table in the target database.

## Connection spec

Pass a UTF-8 JSON file with this shape:

```json
{
  "name": "integration-postgres",
  "kind": "sql",
  "type": "postgres",
  "driver": null,
  "driver_options": null,
  "properties": {
    "host": "127.0.0.1",
    "port": 5432,
    "database": "postgres",
    "username": "postgres"
  },
  "secrets_from_env": {
    "password": "DVT_FIXTURE_POSTGRES_PASSWORD"
  },
  "labels": {
    "purpose": "integration-test"
  },
  "metadata": {}
}
```

Required fields are `name`, `kind`, and `type`. `properties`, `labels`, and `metadata` default to
empty mappings. `driver` and `driver_options` are optional. Owner fields are intentionally absent:
the current default privileged service user is the actor and owner.

Raw `secrets` are rejected. Each `secrets_from_env` value names an environment variable that must
already be set in the caller environment. Do not print or echo its value.

## Create policy

The default `--if-exists error` refuses a same-name/same-type connection. `--if-exists reuse`
returns the single existing connection without changing it; ambiguity is an error. There is no
implicit update or upsert.

## Seed policy

Supported SQL types are PostgreSQL, MySQL, ClickHouse, MSSQL, and Oracle. The default table is
`dvt_sample_data` with columns `id`, `label`, `amount`, and `created_at`.

An optional rows file must be a JSON list whose items contain all four columns. `created_at` uses
ISO date format (`YYYY-MM-DD`). Table names are restricted to letters, digits, and underscores and
must begin with a letter or underscore.

`--if-exists fail` is the safe default. `truncate` and `drop` require both explicit user approval
and `--allow-destructive`.
