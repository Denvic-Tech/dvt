from dataclasses import dataclass


@dataclass(frozen=True)
class SQLTemplateRenderingPolicy:
    """Fixed safety policy: values are literals, structural names are identifiers."""

    reject_empty_collections: bool = True
