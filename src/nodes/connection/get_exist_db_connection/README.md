# GetExistDBConnection

Node type: `GetExistDBConnection`.

## Purpose and selection

Resolve a saved SQL connection for downstream nodes. This node retrieves an existing configuration; it does not create a connection or extract business data.

## Inputs and configuration

Set `connection_id` to an accessible saved connection of the matching kind. Through MCP, use the `connection_ref` returned by the connection catalog and the current input-value schema; do not supply credentials in the graph.

## Outputs

`connection` is a DB_CONNECTION object port. Connect it to a consumer's `connection` input; one producer may feed several consumers.

## Behavior and limitations

Resolution checks the executing user's access and the connection kind. Node execution caching is disabled. Metadata exposes dialect/catalog capabilities lazily; an empty table list is not proof that the database has no tables.

## Examples

GetExistDBConnection.connection → ReadTableFromDBV3.connection. Configure this node with an accessible catalog reference:

```json
{"connection_id":"<connection_ref>"}
```

This is a parameter-value sketch; replace the placeholder and use the MCP input wrapper when building a patch. The consumer receives an object, not this string.

## Common errors

Not found/access denied: inspect connections available to the current user/token. Wrong kind: choose the matching connection node. A catalog lookup does not prove that a later network operation or write will succeed.
