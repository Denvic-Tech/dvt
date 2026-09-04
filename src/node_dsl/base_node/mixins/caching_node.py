from typing import Any, Optional, TYPE_CHECKING

from .base import BaseNodeMixin

if TYPE_CHECKING:
    import pandas as pd
    from src.modules.pipeline_cache import (
        CommonOutputKey,
        DataIndexEntry,
        IndexStore,
        MetaKey,
        MetadataCacheEntry,
        ObjectStore,
    )


class CachingNodeMixin(BaseNodeMixin):
    """
    Миксин для доступа к кэшу
    """

    def __init__(
            self,
            *args,

            data_store: Optional["ObjectStore[Any]"] = None,
            data_index_store: Optional["IndexStore[CommonOutputKey, DataIndexEntry]"] = None,

            metadata_store: Optional["ObjectStore[MetadataCacheEntry]"] = None,
            metadata_index_store: Optional["IndexStore[MetaKey, str]"] = None,

            store_enabled: Optional[bool] = False,

            **kwargs
    ):
        super().__init__(*args, **kwargs)

        self.data_store = data_store
        self.data_index_store = data_index_store

        self.metadata_store = metadata_store
        self.metadata_index_store = metadata_index_store

        self._store_enabled = store_enabled

    def get_metadata_cache_key(self) -> str | None:
        return None
