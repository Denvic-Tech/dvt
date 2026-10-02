# LoadJSON

Node type: `LoadJSON`.

## Purpose and selection

Read complete JSON documents from storage. Use `JsonToDataFrame` afterward for tabular processing.

## Inputs and configuration

Connect an S3, FTP/SFTP or SMB connection object's `connection` output to `connection`. Set `path` relative to its bucket/prefix, initial directory or share; do not repeat the root or pass credentials. Optional `connection_overrides` supports S3 bucket/prefix/verify and FTP/SFTP initial directory with a matching `type`; SMB overrides are unsupported.

Set `path` to a file or glob and `encoding` (default `utf-8`).

## Outputs

`output` is the document itself for one file, or a list of documents for several files. It is a JSON value, not a DataFrame.

## Behavior and limitations

Each file is fully loaded and decoded with `json.loads`; JSON Lines is not supported as a multi-document stream. Multiple arrays are kept as nested arrays, not flattened. Metadata inference also loads documents. Size is bounded by worker memory.

## Examples

The connected storage file contains `[{"id":1}]`. `output` is that array; two matched files would produce an outer list of their documents.

Parameter values, without an MCP patch envelope:

```json
{
  "path": "incoming/orders.json",
  "encoding": "utf-8"
}
```

## Common errors

Decode/JSON error: verify encoding and a single valid JSON document per file. Unexpected nesting: account for the number of matched files before selecting a JSON path.
