import sqlalchemy as sa
from pydantic import BaseModel, TypeAdapter
from sqlalchemy.dialects.postgresql import JSONB


class JSONBCompat(sa.types.TypeDecorator):
    impl = sa.JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(sa.JSON())


class PydanticType(sa.types.TypeDecorator):
    """Pydantic type.
    SAVING:
    - Uses SQLAlchemy JSON type under the hood.
    - Acceps the pydantic model and converts it to a dict on save.
    - SQLAlchemy engine JSON-encodes the dict to a string.
    RETRIEVING:
    - Pulls the string from the database.
    - SQLAlchemy engine JSON-decodes the string to a dict.
    - Uses the dict to create a pydantic model.
    """

    # If you work with PostgreSQL, you can consider using
    # sqlalchemy.dialects.postgresql.JSONB instead of a
    # generic sa.types.JSON
    #
    # Ref: https://www.postgresql.org/docs/13/datatype-json.html
    impl = sa.JSON
    cache_ok = True

    def __init__(self, pydantic_type):
        super().__init__()
        self.pydantic_type = pydantic_type
        self._type_adapter = TypeAdapter(pydantic_type)

    def load_dialect_impl(self, dialect):
        # Use JSONB for PostgreSQL and JSON for other databases.
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        else:
            return dialect.type_descriptor(sa.JSON())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, BaseModel):
            return value.model_dump()
        try:
            return self._type_adapter.dump_python(value, mode="json")
        except Exception as exc:
            raise TypeError(
                f"Expected JSON-compatible data for {self.pydantic_type}, got {type(value)}"
            ) from exc

    def process_result_value(self, value, dialect):
        return self._type_adapter.validate_python(value) if value is not None else None
