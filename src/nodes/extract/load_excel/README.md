# LoadExcel

Node type: `LoadExcel`.

## Purpose and selection

Read a worksheet from matching XLSX workbooks into a DataFrame.

## Inputs and configuration

Connect an S3, FTP/SFTP or SMB connection object's `connection` output to `connection`. Set `path` relative to its bucket/prefix, initial directory or share; do not repeat the root or pass credentials. Optional `connection_overrides` supports S3 bucket/prefix/verify and FTP/SFTP initial directory with a matching `type`; SMB overrides are unsupported.

`path` accepts globs. `sheet_name="0"` means the first sheet; numeric strings are zero-based indexes, other strings are names. `header_row=0` is zero-based. `usecols` names take precedence over `usecols_range` (e.g. `A:C`). Explicit `dtypes` support `string`, `Float64`, `Int64`, `boolean`. `thousands`, `decimal="."` and optional `read_timeout_sec` control parsing.

## Outputs

`output` is a Dask DataFrame with delayed file reads.

## Behavior and limitations

Uses openpyxl with cached formula values; it does not calculate Excel formulas. Samples 32 rows for inference and reads whole selected worksheets per file during computation. Invalid numeric/boolean cells under explicit normalization become missing values. Excel errors are treated as missing. Large individual workbooks still need memory. A timeout stops waiting but cannot forcibly terminate an already running read thread.

## Examples

Connect storage containing an XLSX sheet `Orders` with `id, amount`. The output contains its data rows; valid comma-decimal amounts become numbers.

Parameter values, without an MCP patch envelope:

```json
{
  "path": "incoming/orders.xlsx",
  "sheet_name": "Orders",
  "dtypes": {
    "id": "string",
    "amount": "Float64"
  },
  "decimal": ","
}
```

## Common errors

Missing sheet/columns: inspect names and header row. Numeric sheet names are interpreted as indexes. Empty formula cells may lack cached workbook values. Use explicit supported dtypes for mixed columns.
