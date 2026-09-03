---
name: module-context-builder
description: Create and edit bounded context modules under `src/modules` in the Visual_transformer repository. Use when Codex needs to scaffold a new module, add or modify business logic inside an existing module, split module code across `domain`/`flow`/`infra`, enforce layer boundaries, or audit a module against the project pattern used in `src/modules`.
---

# Module Context Builder

## Overview

Create bounded context modules in `src/modules` and evolve existing ones without collapsing layer
boundaries. Prefer the bundled scripts for repeatable scaffolding and structure checks.

## Workflow

1. Classify the task:

   * New module: scaffold first.
   * Existing module: audit first, then implement the feature.
2. Keep the base structure:

   * `domain/` for entities, value objects, types, policies, repository contracts, gateway
     contracts, and domain exceptions.
   * `flow/` for use cases, providers, application orchestration, and flow exceptions.
   * `infra/` for DB models, mappers, repository implementations, gateway implementations,
     external clients, and transport details.
3. Keep the dependency direction:

   * `domain` must not import `flow` or `infra`.
   * `flow` may depend on `domain`.
   * `infra` may depend on `domain`.
   * `flow` must not import `infra`.
   * `infra` must not import `flow`.
4. Treat these as infrastructure concerns even when they live outside the module:

   * `src.models`, `src.schemas`, `src.dto`, `src.crud`, `src.clients`, `src.db`
   * `fastapi`, `pydantic`, `sqlmodel`, `sqlalchemy`
   * HTTP payloads, ORM rows, DB sessions, transport DTOs
5. Keep use cases small:

   * One use case per file.
   * Expose each use case from `flow/use_cases/__init__.py`.
   * Put shared retrieval, caching, access checks, or orchestration logic into providers instead of
     duplicating it across use cases.

## Create A Module

Run `scripts/scaffold_module.py` from this skill when the task starts a new bounded context.

Recommended command shape:

```bash
python scaffold_module.py <module_name> --root <repo_root>
```

Use flags when the module needs extra domain or integration pieces:

* `--with-types`
* `--with-value-objects`
* `--with-policies`
* `--with-clients`

After scaffolding:

1. Rename placeholder classes and methods to domain-specific names.
2. Remove unused placeholder files only if the module truly does not need them.
3. Keep explicit seams for `domain`, `flow`, and `infra` even when the first feature is small.
4. Keep repository and gateway contracts in `domain`, not in `flow` or `infra`.
5. Keep use cases as classes with an `execute` method, not as plain functions.

## Edit An Existing Module

Run `scripts/audit_module.py` before structural edits.

During feature work:

1. Decide whether the new behavior belongs to `domain`, `flow`, or `infra`.
2. Add or update domain entities, value objects, policies, or contracts when business meaning
   changes.
3. Add or extend one dedicated use case file in `flow/use_cases`.
4. Put shared use case orchestration into `flow/providers.py` or focused provider files.
5. Implement adapters in `infra`.
6. Update `infra/mappers.py` when ORM rows, transport DTOs, or external responses must become
   domain objects.
7. When uncertain, choose the stricter boundary instead of the faster implementation.

Prefer targeted refactors. Do not restructure an entire module unless the current feature requires
it for correctness or maintainability.

## Required Rules

* Use `flow`, never `flows`.
* Treat `one use case = one file` as mandatory.
* Keep use cases as classes. The primary entrypoint method must be named `execute`.
* Default to `dataclass` for domain entities and value objects.
* Keep `Pydantic`, `SQLModel`, ORM rows, transport DTOs, and DB sessions out of `domain`.
* Keep `Pydantic`, `SQLModel`, ORM rows, transport DTOs, DB sessions, and direct `crud`/client access out of `flow`.
* Keep transport DTOs, HTTP clients, ORM models, and persistence details out of `domain`.
* Keep SQL queries, HTTP request construction, and ORM-specific logic out of `flow`.
* Put repository and gateway contracts in `domain`.
* Put repository and gateway implementations in `infra`.
* Do not create `flow/repositories` or `flow/gateways`.
* Put SQLModel table definitions in `infra/db_models.py`.
* Put external-to-domain and ORM-to-domain mapping code in `infra/mappers.py`.
* Repository and gateway contracts must accept and return only domain objects, application result objects, or primitives/std-lib types.
* Do not import or raise `RegisteredException` directly outside layer-specific `exceptions.py`. Create named layer-specific exception classes instead.
* Do not overload repository contracts with orchestration-heavy methods that belong in `flow` use cases.
* Domain and flow code must not import `src.models`, `src.schemas`, `src.dto`, `src.crud`, `src.clients`, `src.db`, `fastapi`, `pydantic`, `sqlmodel`, or `sqlalchemy`.
* Compatibility shims are allowed only outside the bounded context module for legacy callers.
* Never break DDD-lite boundaries for speed, migration convenience, or temporary compatibility.
* If a correct implementation would require importing infra/transport/framework concerns into `domain` or `flow`, stop and ask the user instead of making a shortcut.
* Keep exceptions split by layer:

  * `domain/exceptions.py`
  * `flow/exceptions.py`

## Audit

Use `scripts/audit_module.py <module_path>` to catch structural drift.

The audit focuses on:

* missing `domain`/`flow`/`infra` layers;
* forbidden imports across layers;
* accidental `flows/` directories;
* accidental `flow/repositories` or `flow/gateways` directories;
* monolithic `flow/use_cases.py`;
* use case files that do not expose a class with `execute`;
* transport DTO imports inside `domain`;
* infrastructure imports inside `flow`;
* framework and external boundary imports inside `domain` or `flow`;
* contract signatures that leak ORM/session/transport types;
* direct `RegisteredException` usage outside layer `exceptions.py`;
* overloaded repository contracts;
* flow imports inside `infra`.

Interpret the report as:

* `ERROR`: fix before relying on the module structure.
* `WARNING`: acceptable only if the current task has a concrete reason.

## References

Read [references/module-patterns.md](references/module-patterns.md) when:

* deciding whether code belongs in `domain`, `flow`, or `infra`;
* reviewing a module that drifted from the preferred structure;
* checking module anti-patterns and layer-boundary rules.

Before finishing any `src/modules` task, explicitly verify:

1. No imports from infra, transport, framework, or legacy persistence code into `domain`.
2. No imports from infra, transport, framework, or legacy persistence code into `flow`.
3. Repository/gateway contracts live in `domain`.
4. Repository/gateway contracts use only domain types, result objects, or primitives/std-lib types.
5. `Pydantic` exists only in `infra` or external boundaries.
6. Use cases are classes with `execute`.
7. `RegisteredException` is referenced directly only inside layer `exceptions.py`.
8. Repository contracts are not acting as substitute use case collections.
9. Any compatibility shim lives outside the bounded context module.
