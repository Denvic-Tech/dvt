class SQLTemplateError(ValueError):
    """Base error for a SQL template that cannot be safely rendered."""


class SQLTemplateSyntaxError(SQLTemplateError):
    """The SQL skeleton or Jinja interpolation is malformed."""


class SQLTemplateContextError(SQLTemplateError):
    """An interpolation cannot be assigned a safe SQL context."""


class SQLTemplateSerializationError(SQLTemplateError):
    """A value cannot be represented as a SQL literal or identifier."""
