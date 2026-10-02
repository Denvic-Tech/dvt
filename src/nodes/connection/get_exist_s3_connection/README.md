# GetExistS3Connection

Node type: `GetExistS3Connection`.

## Purpose and selection

Resolve a saved S3 connection for downstream nodes. This node retrieves an existing configuration; it does not create a connection or extract business data.

## Inputs and configuration

Set `connection_id` to an accessible saved connection of the matching kind. Through MCP, use the `connection_ref` returned by the connection catalog and the current input-value schema; do not supply credentials in the graph.

## Outputs

`connection` is a S3_CONNECTION object port. Connect it to a consumer's `connection` input; one producer may feed several consumers.

## Behavior and limitations

Resolution checks the executing user's access and the connection kind. Node execution caching is disabled. The configured bucket/prefix defines the file root; consumer paths are relative to it. Metadata may access the object store.

## Examples

GetExistS3Connection.connection → LoadCSV.connection. Configure this node with an accessible catalog reference:

```json
{"connection_id":"<connection_ref>"}
```

This is a parameter-value sketch; replace the placeholder and use the MCP input wrapper when building a patch. The consumer receives an object, not this string.

## Common errors

Not found/access denied: inspect connections available to the current user/token. Wrong kind: choose the matching connection node. A catalog lookup does not prove that a later network operation or write will succeed.
