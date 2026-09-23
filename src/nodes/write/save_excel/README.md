# SaveExcel

Node type: `SaveExcel`.

## Purpose and selection

Create XLSX workbooks from a DataFrame. This exports data; it does not upload or preserve an existing styled workbook.

## Inputs and configuration

Connect an S3, FTP/SFTP or SMB connection object's `connection` output to `connection`. Set `path` relative to its bucket/prefix, initial directory or share; do not repeat the root or pass credentials. Optional `connection_overrides` supports S3 bucket/prefix/verify and FTP/SFTP initial directory with a matching `type`; SMB overrides are unsupported.

Connect `df`. Set `path` with a filename; `.xlsx` is added if needed. Defaults: `sheet_name="Sheet1"`, `index=false`, `header=true`, `single_file=true`.

## Outputs

Creates one workbook or files named `<stem>-part-00000.xlsx`, etc. No DataFrame output is emitted.

## Behavior and limitations

Single-file mode materializes the entire DataFrame in worker memory. Partitioned mode writes one workbook per Dask partition, not multiple sheets in one workbook. Respect Excel limits including space for headers/index: 1,048,576 rows and 16,384 columns per sheet. Existing target files are opened for overwrite. Timezone-aware datetimes may need conversion before Excel export.

## Examples

Connect the DataFrame and an S3 connection object. The result is an XLSX file under the connection's bucket/prefix with an `Orders` sheet.

Parameter values, without an MCP patch envelope:

```json
{
  "path": "reports/orders.xlsx",
  "sheet_name": "Orders",
  "index": false,
  "header": true,
  "single_file": true
}
```

## Common errors

Memory/sheet-limit failure: reduce data or use suitable partitions, each fitting one sheet. Invalid sheet name or timezone dates: normalize before export. Verify file size/path after success.
