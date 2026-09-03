from enum import StrEnum

from .node_typing import IO


class NodeInputNames(StrEnum):
    SIGNAL = "signal_in"
    VARIABLES = "input_variables"


class NodeOutputNames(StrEnum):
    SIGNAL = "signal_out"
    ERROR_SIGNAL = "signal_error"
    VARIABLES = "output_variables"


DVT_ERROR_TEXT_VARIABLE_NAME = "__dvt_error_text"


NODE_METADATA_EXCLUDE_INPUT_NAMES = [
    NodeInputNames.SIGNAL,
    NodeInputNames.VARIABLES
]

NODE_METADATA_EXCLUDE_TYPES = [
    IO.SIGNAL
]
