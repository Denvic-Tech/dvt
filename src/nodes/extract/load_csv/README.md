# LoadCSV

Node type: `LoadCSV`.

## Purpose and selection

Read one or several CSV files into a DataFrame.

## Inputs and configuration

Connect an S3, FTP/SFTP or SMB connection object's `connection` output to `connection`. Set `path` relative to its bucket/prefix, initial directory or share; do not repeat the root or pass credentials. Optional `connection_overrides` supports S3 bucket/prefix/verify and FTP/SFTP initial directory with a matching `type`; SMB overrides are unsupported.

`path` accepts glob patterns. `delimiter` defaults to comma; escaped tab is supported. `encoding=utf-8`, optional `usecols` and `dtypes` control decoding, projection and types.

## Outputs

`output` is a Dask DataFrame of matching files.

## Behavior and limitations

At least one file must match. Schemas across files must be compatible; inference from an initial sample can miss later mixed values. FTP files are localized and read as delayed pandas partitions. Metadata inference also opens source data. The node does not expose a headerless-file setting.

## Examples

Connect an S3 object whose root contains matching CSVs with `id;amount` headers. The output combines their rows and preserves textual IDs.

Parameter values, without an MCP patch envelope:

```json
{
  "path": "incoming/orders-*.csv",
  "delimiter": ";",
  "dtypes": {
    "id": "string",
    "amount": "float64"
  }
}
```

## Common errors

No files: check root and pattern. Decode/column errors: verify encoding, separator and header. Mixed-type errors: set suitable explicit dtypes rather than trusting sample inference.
