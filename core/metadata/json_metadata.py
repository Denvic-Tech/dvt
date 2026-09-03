from core.types.metadata import JSONMetadata

from .json_structure import infer_json_structure
from .json_tabular import normalize_tabular_json
from .json_utils import json_safe


def get_json_metadata(obj):
    safe_obj = json_safe(obj)
    normalized = normalize_tabular_json(safe_obj)
    inference = infer_json_structure(normalized.value)
    return JSONMetadata(
        response=safe_obj,
        root=inference.root,
        flatten_candidates=inference.flatten_candidates,
        stats=inference.stats,
        inferred_schema=inference.inferred_schema,
        structure_truncated=inference.structure_truncated,
    )
