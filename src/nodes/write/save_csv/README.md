# SaveCSV

Node type: `SaveCSV`.

## Purpose and selection

Export a DataFrame to CSV in connected storage.

## Inputs and configuration

Connect an S3, FTP/SFTP or SMB connection object's `connection` output to `connection`. Set `path` relative to its bucket/prefix, initial directory or share; do not repeat the root or pass credentials. Optional `connection_overrides` supports S3 bucket/prefix/verify and FTP/SFTP initial directory with a matching `type`; SMB overrides are unsupported.

Connect `df`. Set `path` including a filename (the `.csv` suffix is added if absent). Defaults: `delimiter=","`, `encoding="utf-8"`, `index=false`, `header=true`, `single_file=true`.

## Outputs

Creates CSV files; there is no DataFrame output port.

## Behavior and limitations

Writing computes the input. Single-file mode writes one header; multi-file mode delegates partition filenames to Dask. CSV does not preserve a typed schema. Existing destinations may be overwritten; this node has no append/upsert mode. Partial files may remain after failure.

## Examples

Connect a DataFrame and storage with write access. A CSV with column headers and no index column appears at the relative path.

Parameter values, without an MCP patch envelope:

```json
{
  "path": "reports/orders.csv",
  "delimiter": ";",
  "index": false,
  "header": true,
  "single_file": true
}
```

## Common errors

Path/permission error: verify root and write access. Unexpected extra index column: set index=false. After success, inspect the stored file; after failure, inspect partial output before retrying.
