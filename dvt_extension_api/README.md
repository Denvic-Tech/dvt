# DVT Extension API

`dvt-extension-api` is the installable development distribution for the public
`dvt_extension_api` Python namespace used by DVT extensions.

The current V1 implementation is still a facade over DVT runtime internals. This
package therefore makes the public namespace installable/editable for extension
development, but it is not yet a standalone SDK and does not declare or vendor the
full DVT runtime dependency graph.

## Editable development install

Set `DVT_PROJECT_DIR` to the root of the DVT checkout, then install the API package
into the Python environment used by the extension:

```powershell
$env:DVT_PROJECT_DIR = "<path-to-dvt>"
python -m pip install -e "$env:DVT_PROJECT_DIR\dvt_extension_api"
```

Because V1 currently delegates to `src` and `core`, concrete API modules still need
the DVT checkout on `PYTHONPATH` during development:

```powershell
$env:PYTHONPATH = $env:DVT_PROJECT_DIR
```

After that, extensions can use normal imports such as:

```python
from dvt_extension_api.v1.metadata import DataFrameMetadata
from dvt_extension_api.v1.node import DFOutputBaseNode
from dvt_extension_api.v1.parquet import FilenameTemplate, NamingContext
```

Changes made under `dvt_extension_api/` in the DVT checkout are immediately visible
to the environment where the package was installed with `-e`.

## Cooperative cancellation

Nodes receive a read-only `self.cancellation` token when created by
`PipelineProcessor`. Existing constructors and inputs are unchanged; standalone
nodes receive an inactive token. The additive public symbols are
`CancellationToken` and `NodeExecutionCancelled` in
`dvt_extension_api.v1.execution`.

Call `self.cancellation.raise_if_requested()` between units of work, or use
`is_requested()` with an API accepting a cancellation predicate. For deferred
work, capture the token itself in the graph:

```python
token = self.cancellation

def read_page():
    token.raise_if_requested()
    # Perform one bounded request, then check again before the next request.
```

The bound token is process-local: local threaded Dask work can observe STOP,
including when a downstream node computes a source graph. Do not serialize it
to distributed/process schedulers. Blocking I/O needs its own timeouts; polling
does not interrupt an in-flight system call. Let `NodeExecutionCancelled`
propagate. The processor treats it as cancellation only when the task STOP
signal is set, without node-error callbacks or error-signal branches. Other
exceptions remain errors. Task execution still owns terminal-reason precedence.

## Scope

This packaging is intentionally development-focused. A later SDK extraction can
remove the remaining `src`/`core` runtime dependency and publish the distribution as
a fully standalone package without changing the `dvt_extension_api.v1` import path.
