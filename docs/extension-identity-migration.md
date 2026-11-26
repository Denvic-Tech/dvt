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

For a managed installation, prepare and apply the supported release through
**Профиль → Обновление DVT**. The manager drains accepted executions, creates a
verified backup, runs the target release's migrator, and starts Gateway and
workers from that release. Save the operation ID and follow its log in the
independent manager. The installation guide describes the supported legacy
transition through the managed `1.24.0` release. [Installation and updates](../services/installation_manager/customer_installation.md)

For local development, run `python -m services.gateway.migrate` through the
project virtual environment with the target release and database settings
before starting Gateway and workers. This prepares core migrations and
extensions. The full Compose stack runs the same command in its one-time
`migrate` service using the Gateway image. Existing extension packages are
retained.

Migration validation runs before updating records. Unknown technical names,
duplicate canonical identities, or aliases shared by different records abort
the migration with a diagnostic error. Resolve the conflicting ownership from
package metadata and retained data before retrying; never guess identities by
slugifying display names. Runtime reconciliation also rejects conflicting
packages and multiple records that may own data.

Migration 0062 intentionally has no automatic downgrade: dropping physical
storage mappings could orphan retained schemas. Rollback requires a compatible
forward migration or restoring a consistent pre-upgrade database and release.
For a failed managed update, use the available action under the original
operation ID. Data restoration requires confirmation of the backup manifest
digest and cutoff time, followed by readiness checks and an explicit resume.
[Recovery procedure](../services/installation_manager/recovery.md)

## Verification

Regression tests cover legacy record migration, aliases after reinstalls,
canonical-only OpenAPI, shared state locks, and conflicting identities.
PostgreSQL testcontainer checks additionally prove that both names access the
same preserved tables and state, commit boundaries keep the correct search
path, and explicit schema removal addresses the retained physical schema.
