# LoadParquet

Node type: `LoadParquet`.

## Purpose and selection

Read a Parquet file or dataset while retaining its stored schema.

## Inputs and configuration

Connect an S3, FTP/SFTP or SMB connection object's `connection` output to `connection`. Set `path` relative to its bucket/prefix, initial directory or share; do not repeat the root or pass credentials. Optional `connection_overrides` supports S3 bucket/prefix/verify and FTP/SFTP initial directory with a matching `type`; SMB overrides are unsupported.

Set `path` to the relative file/dataset path. Optional `usecols` projects selected fields.

## Outputs

`output` is a Dask DataFrame; Hive partition values are restored as columns where supported by dataset metadata.

## Behavior and limitations

Reads use pyarrow and file schemas rather than CSV-style type guessing. FTP datasets are enumerated recursively and files are read through local temporary copies. DVT logical schema metadata helps restore partition types/categories. All parts need compatible schemas; metadata inspection is not a full data-read verification.

## Examples

Connect storage containing an existing dataset with these columns. The output exposes only `id, amount`.

Parameter values, without an MCP patch envelope:

```json
{
  "path": "datasets/orders",
  "usecols": [
    "id",
    "amount"
  ]
}
```

## Common errors

No dataset: distinguish a file path from a dataset directory. Missing projected fields/schema mismatch: inspect all parts and stored partition metadata. Do not point at unrelated files.
