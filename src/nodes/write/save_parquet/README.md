# SaveParquet

Node type: `SaveParquet`.

## Purpose and selection

Write typed Parquet files or datasets to storage. Prefer it over CSV when schema preservation matters.

## Inputs and configuration

Connect an S3, FTP/SFTP or SMB connection object's `connection` output to `connection`. Set `path` relative to its bucket/prefix, initial directory or share; do not repeat the root or pass credentials. Optional `connection_overrides` supports S3 bucket/prefix/verify and FTP/SFTP initial directory with a matching `type`; SMB overrides are unsupported.

Connect `df`; set `path` and required `mode`: `create`, `overwrite`, `append`. Defaults: `compression="snappy"`, `write_index=false`, `compatibility_mode="new"`. Optional `parquet_types` defines Arrow type contracts. `row_cap` limits rows per file; `partition_on` selects Hive keys; `filename_template` supports `<partition_index>`, `<increment>`, `<uuid>`.

## Outputs

Writes physical Parquet output without a DataFrame result port. New mode uses a single `.parquet` file for simple layout; advanced layout uses a dataset directory.

## Behavior and limitations

Simple layout is chosen without row_cap, partition keys, template or append. Any of those selects advanced layout. Create rejects an existing target; overwrite replaces its contents; append requires an existing compatible dataset. Independent writers to one dataset must be serialized. Overwrite of a detected input-source path is rejected. Legacy mode follows the older Dask dataset layout and append-missing fallback; do not switch compatibility mode without inspecting existing storage.

## Examples

With default new mode and an unused target path, the connected DataFrame is written to one physical file. To start an appendable dataset, create a directory layout explicitly, for example with `row_cap=100000`, then append to that same directory.

Parameter values, without an MCP patch envelope:

```json
{
  "path": "reports/orders.parquet",
  "mode": "create",
  "compression": "snappy",
  "write_index": false
}
```

## Common errors

Existing-target error: choose the intended mode. Append schema mismatch: align dtypes/partition keys with the stored contract. File-vs-directory mismatch: keep the original layout. Failed overwrite is not a guarantee that the old data survives.
