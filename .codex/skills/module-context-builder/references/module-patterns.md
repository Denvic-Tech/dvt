# Module Patterns

## Base Structure

Use this skeleton for bounded contexts in `src/modules/<module_name>`:

```text
<module_name>/
  __init__.py
  domain/
    __init__.py
    entities/              # or entities.py when the number of entities is small
      __init__.py
      <one_entity>.py
    repositories/          # domain repository contracts
      __init__.py
      <one_protocol>.py
    gateways/              # optional domain-facing external contracts
      __init__.py
      <one_gateway>.py
    policies/              # or policies.py when the number of policies is small, optional
      __init__.py
      <one_policy>.py
    exceptions.py
    types.py               # optional
    value_objects.py       # optional
  flow/
    __init__.py
    use_cases/
      __init__.py
      <one_use_case>.py
    exceptions.py
    providers.py           # optional, preferred when shared orchestration appears
  infra/
    __init__.py
    db_models.py           # optional when persistence exists
    mappers.py             # optional when persistence/transport/domain mapping exists
    repositories/
      __init__.py
      <one_impl>.py
    gateways/
      __init__.py
      <one_impl>.py
    clients/               # optional when external transport exists
      __init__.py
      <one_client>.py
```

## Layer Rules

* `domain` owns business meaning.
* `flow` owns application orchestration.
* `infra` owns persistence, transport, external clients, and implementation details.

Allowed dependency direction:

```text
flow -> domain
infra -> domain
```

Forbidden dependency direction:

```text
domain -> flow
domain -> infra
flow -> infra
infra -> flow
```

Additional structure rules:

* Do not create `flow/repositories` or `flow/gateways`.
* Keep contracts in `domain/*` and implementations in `infra/*`.

## Responsibility Rules

### Domain

The `domain` layer contains the stable business model of the module.

Use `domain` for:

* entities;
* value objects;
* domain exceptions;
* domain-specific types and enums;
* reusable business policies;
* repository contracts;
* domain-facing gateway contracts.

Repository and gateway contracts belong to `domain` when they describe what the business needs, not how the data or external system is accessed.

Example:

```text
domain/repositories/connection.py
domain/gateways/license_verifier.py
```

The domain layer must not import:

* SQLAlchemy models;
* SQLModel models;
* Pydantic API schemas;
* HTTP clients;
* `src.models`, `src.schemas`, `src.dto`, `src.crud`, `src.clients`, `src.db`;
* framework dependencies;
* infrastructure implementations;
* use cases.

Default to `dataclass` for domain entities and value objects.

Do not use `Pydantic`, `SQLModel`, ORM rows, transport DTOs, or DB sessions inside domain
entities, value objects, or contracts.

### Flow

The `flow` layer coordinates application behavior.

Use `flow` for:

* use cases;
* transaction boundaries at the application level;
* orchestration between entities, repositories, policies, and gateways;
* flow-specific exceptions;
* shared providers when multiple use cases need the same orchestration path.

The `flow` layer may depend on `domain` contracts, entities, value objects, policies, and exceptions.

The `flow` layer must not import infrastructure implementations directly.
The `flow` layer must not import `src.models`, `src.schemas`, `src.dto`, `src.crud`,
`src.clients`, `src.db`, `fastapi`, `pydantic`, `sqlmodel`, or `sqlalchemy`.
Each use case file should expose one primary use case class whose entrypoint is `execute`.

Bad:

```python
from src.modules.my_module.infra.repositories.sqlalchemy_connection import (
    SQLAlchemyConnectionRepository,
)
```

Good:

```python
from src.modules.my_module.domain.repositories.connection import (
    ConnectionRepository,
)
```

### Infra

The `infra` layer implements technical details.

Use `infra` for:

* ORM models;
* database repository implementations;
* HTTP/API clients;
* external transport details;
* mappers between ORM/DTO objects and domain entities;
* implementations of domain repository contracts;
* implementations of domain gateway contracts.

Infrastructure may depend on `domain`, but must not depend on `flow`.

Repository implementations must implement domain repository contracts.

Gateway implementations must implement domain gateway contracts.

## Repository Rules

Split repository contracts by aggregate or focused responsibility.

Prefer:

```text
domain/repositories/connection.py
domain/repositories/connection_secret.py
domain/repositories/user_connection_limit.py
```

Avoid:

```text
domain/repositories.py
domain/protocols.py
```

Repository contracts should describe domain operations, not database operations.
Repository contracts should accept and return only domain entities, value objects, application
result objects, or primitives/std-lib types.
Repository contracts should stay focused on aggregate persistence and retrieval responsibilities.
If a contract starts accumulating orchestration-like commands, move that behavior into `flow`
use cases instead of expanding the repository surface further.

Prefer:

```python
class ConnectionRepository(Protocol):
    async def get_by_id(self, connection_id: ConnectionId) -> Connection | None: ...
    async def save(self, connection: Connection) -> None: ...
```

Avoid leaking persistence details:

```python
class ConnectionRepository(Protocol):
    async def get_query(self) -> Select: ...
    async def get_session(self) -> AsyncSession: ...
```

Also avoid leaking transport or framework details:

```python
class ConnectionRepository(Protocol):
    async def save(self, payload: BaseModel) -> SQLModel: ...
```

Also avoid turning repository contracts into use case collections:

```python
class ConnectionRepository(Protocol):
    async def create_connection(self, ...): ...
    async def update_connection(self, ...): ...
    async def activate_connection(self, ...): ...
    async def validate_connection(self, ...): ...
    async def rotate_connection_secret(self, ...): ...
```

## Gateway Rules

Use `domain/gateways` for contracts to external systems when the domain or use cases need an abstract capability.

Examples:

```text
domain/gateways/secret_vault.py
domain/gateways/license_verifier.py
domain/gateways/event_publisher.py
```

Use `infra/gateways` or `infra/clients` for concrete implementations.

Examples:

```text
infra/gateways/yandex_secret_vault.py
infra/gateways/http_license_verifier.py
infra/clients/license_api_client.py
```

Keep external schema, request payloads, response DTOs, auth headers, and client configuration inside `infra`.

Use mappers to convert transport DTOs to domain entities or value objects.

## Use Case Rules

Split application logic into dedicated use case files.

Prefer:

```text
flow/use_cases/create_connection.py
flow/use_cases/update_connection.py
flow/use_cases/delete_connection.py
flow/use_cases/get_connection.py
```

Avoid:

```text
flow/use_cases.py
```

A use case should usually:

1. accept input from the API/service layer;
2. load entities through domain repository contracts;
3. apply entity methods or domain policies;
4. call domain gateway contracts when needed;
5. save changes through repository contracts;
6. return a domain entity, value object, or application result.

Use case shape:

```python
class CreateConnection:
    async def execute(self, ...):
        ...
```

A use case should not:

* build SQL queries directly;
* know about ORM models;
* call HTTP clients directly;
* parse external API responses;
* depend on FastAPI, SQLAlchemy, or transport-specific DTOs;
* import `src.models`, `src.schemas`, `src.dto`, `src.crud`, `src.clients`, or `src.db`.

## Provider Rules

Use `flow/providers.py` only when multiple use cases share the same orchestration path.

Good examples:

* cache-aware entity retrieval;
* common access checks;
* loading an aggregate with related domain data;
* shared preparation logic before use case execution.

Avoid turning `providers.py` into a service locator or a grab-bag helper module.

If provider logic becomes large, split it into focused files:

```text
flow/providers/
  __init__.py
  connection_loader.py
  access_checker.py
```

## Mapper Rules

Use `infra/mappers.py` when infrastructure objects must be translated into domain objects.

Examples:

* ORM row to domain entity;
* external API response DTO to domain value object;
* domain entity to ORM model;
* domain entity to transport payload.

Mappers belong to `infra` because they know about infrastructure formats.

The domain layer must not know how it is persisted or transported.
Compatibility shims for legacy callers may exist outside the bounded context module, but they must
not pull transport/framework/persistence concerns into `domain` or `flow`.

## Anti-Patterns

* Directory named `flows/` instead of `flow/`.
* Single-file `flow/use_cases.py` containing unrelated actions.
* Single-file `domain/protocols.py` or `domain/repositories.py` containing unrelated contracts.
* Domain files importing transport schemas, SQLModel classes, SQLAlchemy models, or framework dependencies.
* Flow files importing infrastructure implementations.
* Infrastructure files importing flow use cases or providers.
* Repository implementations defining their own contracts instead of implementing `domain` protocols.
* Feature work that adds HTTP or DB details directly to `domain` or `flow`.
* Use cases that contain SQL queries, HTTP request construction, or ORM-specific logic.
* Refactors that keep old persistence or transport types inside `domain` or `flow` for migration speed.
* `flow/repositories` or `flow/gateways` directories.
* Use case files implemented only as functions instead of classes with `execute`.
* Direct `RegisteredException` imports or raises outside layer-specific `exceptions.py`.
* Repository contracts bloated with use-case-level commands.

## Feature Work Checklist

Before editing an existing module:

1. Run the audit script.
2. Decide which layer owns the new behavior.
3. Check whether the behavior belongs to the domain before adding adapters.
4. Add or update domain entities, value objects, policies, or contracts when business meaning changes.
5. Add or update use cases when application orchestration changes.
6. Add or update infrastructure implementations only after the required domain contracts are clear.
7. Add a new use case file instead of extending a grab-bag module.
8. Keep provider logic shared if multiple use cases need the same retrieval, validation, or caching path.
9. Keep external schemas, clients, and persistence details inside `infra`.
10. Stop and ask if the fastest implementation would violate layer boundaries.

## When To Add Optional Files

* Add `domain/types.py` when enums or constrained aliases become part of the ubiquitous language.
* Add `domain/value_objects.py` when validation, parsing, normalization, or derived behavior belongs to a value, not a service.
* Add `domain/policies.py` when reusable business rules would make entities noisy.
* Add `domain/gateways/` when the module needs external capabilities behind domain-facing contracts.
* Add `infra/db_models.py` when the module persists its own tables.
* Add `infra/mappers.py` when adapters must translate DTOs, ORM rows, or transport objects to domain objects.
* Add `infra/clients/` when the module integrates with an external API, SDK, protocol, or transport.
* Add `flow/providers.py` when multiple use cases share orchestration that should not be duplicated.
