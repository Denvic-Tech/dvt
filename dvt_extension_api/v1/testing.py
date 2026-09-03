"""Small testing surface for extension authors."""

from .metadata import get_df_metadata
from .state import get_extension_state, set_extension_state, update_extension_state
from .storage import create_s3_client, resolve_file_connection_context

__all__ = [
    "create_s3_client",
    "get_df_metadata",
    "get_extension_state",
    "resolve_file_connection_context",
    "set_extension_state",
    "update_extension_state",
]
