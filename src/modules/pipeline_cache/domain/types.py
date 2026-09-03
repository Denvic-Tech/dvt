from enum import StrEnum


class CacheNamespaceName(StrEnum):
    DATA = "data"
    DATA_INDEX = "data_index"
    METADATA = "metadata"
    METADATA_INDEX = "metadata_index"
