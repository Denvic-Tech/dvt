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
```

Changes made under `dvt_extension_api/` in the DVT checkout are immediately visible
to the environment where the package was installed with `-e`.

## Scope

This packaging is intentionally development-focused. A later SDK extraction can
remove the remaining `src`/`core` runtime dependency and publish the distribution as
a fully standalone package without changing the `dvt_extension_api.v1` import path.
