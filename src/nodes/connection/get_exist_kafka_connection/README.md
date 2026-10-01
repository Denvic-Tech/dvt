# Kafka Connection

Node type: `GetExistKafkaConnection`.

## Purpose and selection

Loads an existing Kafka connection available to the executing user. This stable node is available
in UI and MCP alongside Read Kafka Messages and Commit Kafka Offsets.

## Inputs and configuration

`connection_id` is the catalog identifier (`IO.KAFKA_CONNECTION_ID`). Use a saved Kafka
connection, not a topic name. Legacy numeric identifiers are converted to strings for lookup.
The UI selector offers accessible Kafka connections and saves their catalog ID.
Credentials belong in the connection catalog, never in graph variables.

## Outputs

`connection` contains a `KafkaConnectionRecord`, suitable for Kafka consumers.
Loading the record does not create a producer or read messages.

## Behavior and limitations

Access checks use the existing connection service. The node does not commit offsets.
The connection supports PLAINTEXT, SSL, SASL_PLAINTEXT and SASL_SSL, with PLAIN,
SCRAM-SHA-256 or SCRAM-SHA-512. Optional `ssl_ca_pem` contains a custom CA in PEM;
certificate and hostname verification remain enabled. mTLS is not supported by this configuration.
Custom CA support requires the accompanying db-connections source change; the published
1.1.6 package does not contain it.

## Examples

Prerequisite: an accessible Kafka connection with catalog ID `kafka-orders`.

```json
{"connection_id": "kafka-orders"}
```

Connect the `connection` output to the `connection` input of a compatible Kafka consumer.
The expected output is the saved record, with no producer or offset side effects.

In MCP, call list_connections/get_connection, then set this node's connection_id to
`{"kind":"connection_ref","connection_id":"kafka-orders"}` in a graph patch.
Wire its connection output to Read/Commit connection inputs; those object ports do not accept
an ID string. User, organization and token scopes still apply. Passwords and CA PEM are not
returned by the public connection catalog. Topic payload is not a catalog property.

## Common errors

An inaccessible or missing ID fails lookup. A non-Kafka record fails type validation.
Supply a trusted CA for private TLS certificates; do not disable verification.
