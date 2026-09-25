# Extension identity and migration 0062

An extension's technical name is the validated, PEP 503 normalized
`project.name` from its package. Display names and installation directory names
do not determine API paths. Gateway publishes only
`/api/extensions/{canonical-name}/api/...` in OpenAPI.

Existing names are retained as explicit legacy aliases. Management, state,
dependency checks, and Gateway extension routes resolve aliases to the same
extension. State update locks use the retained record UUID. Frontend metadata
returns the canonical name, so the host UI requires no separate naming rule.

## Storage and existing installations

Migration 0062 canonicalizes existing records using their technical manifest
metadata, preserves UUIDs, state, installation paths and flags, and stores the
pre-migration PostgreSQL schema in `extensions.storage_schema`. It does not
rename schemas or move extension tables.

The database API, extension migrations and removal operations resolve the
persisted physical schema. Extensions must use the host database API instead of
constructing schema names from display names or URL segments. Resolving storage
requires an existing extension record.

Aliases survive install, reinstall and filesystem/catalog synchronization.
Uninstall retains the catalog record and its canonical identity. Default
uninstall preserves state and physical data; explicit removal with
`drop_extension_data=true` removes the physical schema and clears `state_json`.

## Upgrade procedure

Deploy Gateway and task workers from the same new release. Drain active
executions before the migration and restart workers with the new runtime;
running old and new storage-resolution code together is unsupported.
Apply `alembic upgrade head` before starting the updated services. Reinstallation
of extension packages is not required.

Migration validation runs before updating records. Unknown technical names,
duplicate canonical identities, or aliases shared by different records abort
the migration with a diagnostic error. Resolve the conflicting ownership from
package metadata and retained data before retrying; never guess identities by
slugifying display names. Runtime reconciliation also rejects conflicting
packages and multiple records that may own data.

Migration 0062 intentionally has no automatic downgrade: dropping physical
storage mappings could orphan retained schemas. Rollback requires a compatible
forward migration or restoring a consistent pre-upgrade database and release.

## Verification

Regression tests cover legacy record migration, aliases after reinstalls,
canonical-only OpenAPI, shared state locks, and conflicting identities.
PostgreSQL testcontainer checks additionally prove that both names access the
same preserved tables and state, commit boundaries keep the correct search
path, and explicit schema removal addresses the retained physical schema.
