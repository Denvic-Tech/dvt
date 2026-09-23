# HTTPRequest

Node type: `HTTPRequest`.

## Purpose and selection

Make one HTTP request and expose its JSON response. Use for API access; the node does not automatically paginate or flatten responses.

## Inputs and configuration

Set `url`, `method` (default GET), dictionary `headers` and `params`. POST/PUT/PATCH can use `json_payload` (object/list) or form `data`. Defaults: timeout=30 seconds (1–300), verify_ssl=true, auth={"type":"none"}. Auth variants include basic/digest username/password, oauth2 token (Bearer), and file_cert cert_file_path/key_file_path. Auth fields support expressions from input/project variables.

## Outputs

`output` contains the parsed JSON response, not status/headers or raw text. Feed it to JSONEditor/JsonToDataFrame as appropriate.

## Behavior and limitations

HTTP error statuses fail the node; a successful non-JSON/empty response also fails JSON decoding. GET bodies are cleared. For body-capable methods JSON wins over form data, except legacy empty JSON object plus non-empty form data. OAuth2 uses an existing bearer token, without token acquisition/refresh. Metadata inference can send a real request and can repeat it for a falsey response; consider this for POST/PUT/DELETE side effects. Certificate paths refer to the worker filesystem.

## Examples

Replace the example URL with an authorized endpoint returning JSON. If it returns `{"items":[{"id":1}]}`, that object is emitted unchanged; pagination needs separate graph logic.

Parameter values, without an MCP patch envelope:

```json
{
  "url": "https://api.example.com/orders",
  "method": "GET",
  "params": {
    "limit": 100
  },
  "timeout": 30
}
```

## Common errors

Timeout/network errors: verify endpoint reachability from the worker. 401/403: inspect the selected auth configuration without exposing secrets. JSON error: verify the response content and status; HEAD/204 endpoints commonly have no JSON body.
